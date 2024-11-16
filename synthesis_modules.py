import board
import synthio
import audiobusio
import math
import array
import audiomixer
import supervisor

# Custom Enum implementation for CircuitPython
class Enum:
    def __init__(self, *args):
        self._values = {}
        self._names = {}
        for i, name in enumerate(args):
            value = 1 << i  # Use bit shifting for unique values
            setattr(self, name, value)
            self._values[name] = value
            self._names[value] = name

    def __contains__(self, item):
        return item in self._values or item in self._names

    def __getitem__(self, key):
        return self._names.get(key) or self._values.get(key)

    def __iter__(self):
        return iter(self._values)

def auto():
    """Placeholder for auto() functionality"""
    return None

# Modulation Sources and Targets using custom Enum
ModSource = Enum(
    'PRESSURE', 'PITCH_BEND', 'TIMBRE', 
    'LFO1', 'LFO2', 'ENV1', 'ENV2', 
    'VELOCITY', 'NOTE'
)

ModTarget = Enum(
    'FILTER_CUTOFF', 'FILTER_RESONANCE', 'OSC_DETUNE', 
    'ENV_ATTACK', 'ENV_DECAY', 'ENV_SUSTAIN', 'ENV_RELEASE', 
    'AMP_LEVEL', 'PAN'
)

class FixedPoint:
    SCALE = 1 << 16  # 16-bit fractional part
    MAX_VALUE = (1 << 31) - 1
    MIN_VALUE = -(1 << 31)
    
    # Pre-calculated common scaling factors
    MIDI_SCALE = 516  # 1/127 in fixed point (saves division)
    PITCH_BEND_SCALE = 8  # 1/8192 in fixed point (saves division)
    PITCH_BEND_CENTER = 8192 << 16  # 8192 in fixed point
    ONE = 1 << 16  # 1.0 in fixed point
    HALF = 1 << 15  # 0.5 in fixed point
    ZERO = 0
    
    @staticmethod
    def from_float(value):
        """Convert float to fixed-point integer with safe bounds"""
        try:
            value = max(min(value, 32767.0), -32768.0)
            return int(value * FixedPoint.SCALE)
        except (TypeError, OverflowError):
            return 0
        
    @staticmethod
    def to_float(fixed):
        """Convert fixed-point integer to float with safe handling"""
        try:
            if isinstance(fixed, (int, float)):
                return float(fixed) / float(FixedPoint.SCALE)
            return 0.0
        except (TypeError, OverflowError):
            return 0.0
        
    @staticmethod
    def multiply(a, b):
        """Multiply two fixed-point numbers"""
        if not isinstance(a, int):
            a = FixedPoint.from_float(float(a))
        if not isinstance(b, int):
            b = FixedPoint.from_float(float(b))
        return (a * b) >> 16

    @staticmethod
    def normalize_midi_value(value):
        """Normalize MIDI value (0-127) to 0-1 range using pre-calculated scale"""
        return value * FixedPoint.MIDI_SCALE

    @staticmethod
    def normalize_pitch_bend(value):
        """Normalize pitch bend value (0-16383) to -1 to 1 range using pre-calculated values"""
        return ((value << 16) - FixedPoint.PITCH_BEND_CENTER) * FixedPoint.PITCH_BEND_SCALE

    @staticmethod
    def clamp(value, min_val, max_val):
        """Clamp a fixed-point value between min and max"""
        return max(min(value, max_val), min_val)

class Constants:
    DEBUG = True
    NOTE_TRACKER = True
    PRESSURE_TRACKER = True
    
    # Audio Pins (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2
    I2S_DATA = board.GP0

    # Synthesizer Constants
    AUDIO_BUFFER_SIZE = 8192
    SAMPLE_RATE = 44100
    
    # Note Management Constants
    MAX_ACTIVE_NOTES = 8
    NOTE_TIMEOUT_MS = 2000
    
    # MPE Load Management Constants
    MPE_LOAD_CHECK_INTERVAL = 100
    BASE_MPE_THRESHOLD = 10
    MAX_MPE_THRESHOLD_MULTIPLIER = 4

    # MPE Significance Constants
    BASE_THRESHOLD = FixedPoint.from_float(0.05)
    MAX_THRESHOLD = FixedPoint.from_float(0.20)
    THRESHOLD_SCALE = FixedPoint.from_float(1.5)

    # Envelope Parameter Constants
    ENVELOPE_MIN_TIME = FixedPoint.from_float(0.001)
    ENVELOPE_MAX_TIME = FixedPoint.from_float(10.0)
    ENVELOPE_MIN_LEVEL = FixedPoint.from_float(0.0)
    ENVELOPE_MAX_LEVEL = FixedPoint.from_float(1.0)

    # Pre-calculated sine lookup table
    SINE_TABLE = [FixedPoint.from_float(math.sin(2 * math.pi * i / 256)) for i in range(256)]

    # Pre-calculated triangle wave scale factors
    TRIANGLE_SCALE_FACTORS = {
        128: FixedPoint.from_float(32767.0 / 64),
        256: FixedPoint.from_float(32767.0 / 128),
        512: FixedPoint.from_float(32767.0 / 256)
    }

    # Pre-calculated amplitude constants
    MAX_AMPLITUDE = FixedPoint.from_float(32767.0)
    MIN_AMPLITUDE = FixedPoint.from_float(-32767.0)

    # Pre-calculated MIDI note frequencies
    MIDI_FREQUENCIES = [440.0 * 2 ** ((i - 69) / 12) for i in range(128)]

class ModulationRoute:
    def __init__(self, source, target, amount=1.0, curve='linear'):
        self.source = source
        self.target = target
        self.amount = FixedPoint.from_float(amount)
        self.curve = curve
        self.last_value = None

class ModulationMatrix:
    def __init__(self):
        self.routes = []
        self.source_values = {source: FixedPoint.ZERO for source in ModSource._values}
        
    def add_route(self, source, target, amount=1.0, curve='linear'):
        """Add a new modulation route"""
        route = ModulationRoute(source, target, amount, curve)
        self.routes.append(route)
        
    def remove_route(self, source, target):
        """Remove a modulation route"""
        self.routes = [r for r in self.routes if not (r.source == source and r.target == target)]
        
    def set_source_value(self, source, value):
        """Set the current value of a modulation source"""
        self.source_values[source] = FixedPoint.from_float(value)
        
    def get_target_value(self, target):
        """Calculate the final value for a modulation target"""
        total = FixedPoint.ZERO
        for route in self.routes:
            if route.target == target:
                source_value = self.source_values[route.source]
                if route.curve == 'exponential':
                    processed = FixedPoint.multiply(source_value, source_value)
                else:  # linear
                    processed = source_value
                total += FixedPoint.multiply(processed, route.amount)
        return total

class MPEProcessor:
    def __init__(self, modulation_matrix):
        self.mod_matrix = modulation_matrix
        self.pressure_enabled = True
        self.pitch_bend_enabled = True
        self.timbre_enabled = True
        self.pressure_sensitivity = FixedPoint.from_float(1.0)
        self.pitch_bend_range = FixedPoint.from_float(48)
        self.pitch_bend_curve = FixedPoint.from_float(2)
        
    def process_pressure(self, voice, pressure_value):
        """Process pressure for a voice"""
        if not self.pressure_enabled:
            return False
            
        norm_pressure = FixedPoint.normalize_midi_value(pressure_value)
        relative_pressure = voice.get_relative_pressure(pressure_value)
        
        if voice.is_significant_change(voice.pressure, relative_pressure, voice.output_manager.active_voices):
            voice.pressure = relative_pressure
            scaled_pressure = FixedPoint.multiply(norm_pressure, self.pressure_sensitivity)
            self.mod_matrix.set_source_value(ModSource.PRESSURE, FixedPoint.to_float(scaled_pressure))
            return True
        return False
        
    def process_pitch_bend(self, voice, bend_value):
        """Process pitch bend for a voice"""
        if not self.pitch_bend_enabled:
            return False
            
        relative_bend = voice.get_relative_pitch_bend(bend_value)
        
        if voice.is_significant_change(voice.pitch_bend, relative_bend, voice.output_manager.active_voices):
            voice.pitch_bend = relative_bend
            norm_bend = FixedPoint.normalize_pitch_bend(relative_bend)
            bend_range = FixedPoint.multiply(self.pitch_bend_range, FixedPoint.from_float(1.0 / 12.0))
            final_bend = FixedPoint.multiply(norm_bend, bend_range)
            self.mod_matrix.set_source_value(ModSource.PITCH_BEND, FixedPoint.to_float(final_bend))
            return True
        return False
        
    def process_timbre(self, voice, timbre_value):
        """Process timbre for a voice"""
        if not self.timbre_enabled:
            return False
            
        norm_timbre = FixedPoint.normalize_midi_value(timbre_value)
        if voice.is_significant_change(voice.timbre, timbre_value, voice.output_manager.active_voices):
            voice.timbre = timbre_value
            self.mod_matrix.set_source_value(ModSource.TIMBRE, FixedPoint.to_float(norm_timbre))
            return True
        return False

class Voice:
    def __init__(self, note=None, channel=None, velocity=1.0, output_manager=None):
        self.note = note
        self.channel = channel
        self.velocity = FixedPoint.normalize_midi_value(int(velocity * 127)) if velocity != 1.0 else FixedPoint.ONE
        self.pressure = 0
        self.pitch_bend = 0
        self.timbre = 0
        self.synth_note = None
        self.timestamp = supervisor.ticks_ms()
        self.release_tracking = False
        self.active = False
        self.output_manager = output_manager
        
        # Initial parameter storage for MPE
        self.initial_parameters = {
            'pitch_bend': 0,
            'timbre': 0,
            'pressure': 0,
            'envelope': None,
        }
        
        # MPE update timestamps
        self.last_timbre_update = 0
        self.last_pressure_update = 0
        self.last_pitch_update = 0

    def store_initial_parameters(self, pitch_bend=None, timbre=None, pressure=None, envelope=None):
        """Store initial MPE parameters before note-on"""
        if pitch_bend is not None:
            self.initial_parameters['pitch_bend'] = pitch_bend
        if timbre is not None:
            self.initial_parameters['timbre'] = timbre
        if pressure is not None:
            self.initial_parameters['pressure'] = pressure
        if envelope is not None:
            self.initial_parameters['envelope'] = envelope.copy() if isinstance(envelope, dict) else envelope

    def get_relative_pressure(self, current_pressure):
        """Calculate pressure relative to initial value"""
        initial = self.initial_parameters['pressure']
        return current_pressure - initial if initial is not None else current_pressure

    def get_relative_pitch_bend(self, current_bend):
        """Calculate pitch bend relative to initial value"""
        initial = self.initial_parameters['pitch_bend']
        return current_bend - initial if initial is not None else current_bend

    def is_significant_change(self, current_value, new_value, active_voice_count):
        """Determine if a parameter change is significant enough to process"""
        threshold = min(
            FixedPoint.multiply(Constants.BASE_THRESHOLD, 
                              FixedPoint.from_float(Constants.THRESHOLD_SCALE ** (active_voice_count - 1))),
            Constants.MAX_THRESHOLD
        )
        
        if current_value == 0:
            return abs(new_value) > threshold
        
        relative_change = abs(FixedPoint.multiply(
            FixedPoint.from_float((new_value - current_value)), 
            FixedPoint.from_float(1.0 / current_value)
        ))
        return relative_change > threshold

    def refresh_timestamp(self):
        """Update the voice's timestamp"""
        self.timestamp = supervisor.ticks_ms()

class SynthEngine:
    def __init__(self):
        self.envelope_settings = {
            'attack': FixedPoint.from_float(0.01),
            'decay': FixedPoint.from_float(0.1),
            'sustain': FixedPoint.from_float(0.8),
            'release': FixedPoint.from_float(0.1)
        }
        self.instrument = None
        self.detune = FixedPoint.from_float(0)
        self.filter = None
        self.waveforms = {}
        self.filter_config = {
            'type': 'low_pass',
            'cutoff': FixedPoint.from_float(1000),
            'resonance': FixedPoint.from_float(0.5)
        }
        self.current_waveform = 'sine'
        self.pitch_bend_enabled = True
        self.pitch_bend_range = FixedPoint.from_float(48)
        self.pitch_bend_curve = FixedPoint.from_float(2)
        self.pressure_enabled = True
        self.pressure_sensitivity = FixedPoint.from_float(0.5)
        self.pressure_targets = []
        self.current_pressure = FixedPoint.from_float(0.0)

    def set_instrument(self, instrument):
        self.instrument = instrument
        self._configure_from_instrument()

    def _configure_from_instrument(self):
        if self.instrument:
            config = self.instrument.get_configuration()
            if 'envelope' in config:
                self.set_envelope(config['envelope'])
            if 'oscillator' in config:
                self.configure_oscillator(config['oscillator'])
            if 'filter' in config:
                self.set_filter(config['filter'])
            if 'pitch_bend' in config:
                self.pitch_bend_enabled = config['pitch_bend'].get('enabled', True)
                self.pitch_bend_range = FixedPoint.from_float(config['pitch_bend'].get('range', 48))
                self.pitch_bend_curve = FixedPoint.from_float(config['pitch_bend'].get('curve', 2))
            if 'pressure' in config:
                pressure_config = config['pressure']
                self.pressure_enabled = pressure_config.get('enabled', True)
                self.pressure_sensitivity = FixedPoint.from_float(pressure_config.get('sensitivity', 0.5))
                self.pressure_targets = pressure_config.get('targets', [])

    def configure_oscillator(self, osc_config):
        if 'detune' in osc_config:
            self.set_detune(osc_config['detune'])
        if 'waveform' in osc_config:
            self.set_waveform(osc_config['waveform'])

    def set_filter(self, filter_config):
        self.filter_config.update({
            'type': filter_config['type'],
            'cutoff': FixedPoint.from_float(filter_config['cutoff']),
            'resonance': FixedPoint.from_float(filter_config['resonance'])
        })
        self._update_filter()

    def set_filter_resonance(self, resonance):
        self.filter_config['resonance'] = FixedPoint.from_float(resonance)
        self._update_filter()

    def set_filter_cutoff(self, cutoff):
        safe_cutoff = max(20, min(20000, float(cutoff)))
        self.filter_config['cutoff'] = FixedPoint.from_float(safe_cutoff)
        self._update_filter()

    def _update_filter(self):
        if self.filter_config['type'] == 'low_pass':
            self.filter = lambda synth: synth.low_pass_filter(
                FixedPoint.to_float(self.filter_config['cutoff']),
                FixedPoint.to_float(self.filter_config['resonance'])
            )
        elif self.filter_config['type'] == 'high_pass':
            self.filter = lambda synth: synth.high_pass_filter(
                FixedPoint.to_float(self.filter_config['cutoff']),
                FixedPoint.to_float(self.filter_config['resonance'])
            )
        elif self.filter_config['type'] == 'band_pass':
            self.filter = lambda synth: synth.band_pass_filter(
                FixedPoint.to_float(self.filter_config['cutoff']),
                FixedPoint.to_float(self.filter_config['resonance'])
            )
        else:
            self.filter = None

    def set_detune(self, detune):
        self.detune = FixedPoint.from_float(detune)

    def set_envelope(self, env_config):
        self.envelope_settings.update({
            k: FixedPoint.from_float(v) for k, v in env_config.items()
        })

    def set_envelope_param(self, param, value):
        if param in self.envelope_settings:
            if param in ['attack', 'decay', 'release']:
                clamped_value = FixedPoint.clamp(
                    FixedPoint.from_float(value),
                    Constants.ENVELOPE_MIN_TIME,
                    Constants.ENVELOPE_MAX_TIME
                )
            elif param == 'sustain':
                clamped_value = FixedPoint.clamp(
                    FixedPoint.from_float(value),
                    Constants.ENVELOPE_MIN_LEVEL,
                    Constants.ENVELOPE_MAX_LEVEL
                )
            else:
                return
            
            self.envelope_settings[param] = clamped_value

    def create_envelope(self):
        attack_time = max(0.001, min(10.0, FixedPoint.to_float(
            self.envelope_settings.get('attack', FixedPoint.from_float(0.01))
        )))
        
        decay_time = max(0.001, min(10.0, FixedPoint.to_float(
            self.envelope_settings.get('decay', FixedPoint.from_float(0.1))
        )))
        
        release_time = max(0.001, min(10.0, FixedPoint.to_float(
            self.envelope_settings.get('release', FixedPoint.from_float(0.1))
        )))
        
        sustain_level = max(0.0, min(1.0, FixedPoint.to_float(
            self.envelope_settings.get('sustain', FixedPoint.from_float(0.8))
        )))

        return synthio.Envelope(
            attack_time=attack_time,
            decay_time=decay_time,
            release_time=release_time,
            attack_level=1.0,
            sustain_level=sustain_level
        )

    def set_waveform(self, waveform_type):
        self.current_waveform = waveform_type
        self.generate_waveform(waveform_type)

    def generate_waveform(self, waveform_type, sample_size=256):
        if waveform_type not in self.waveforms:
            if waveform_type == 'sine':
                self.waveforms[waveform_type] = self.generate_sine_wave(sample_size)
            elif waveform_type == 'saw':
                self.waveforms[waveform_type] = self.generate_saw_wave(sample_size)
            elif waveform_type == 'square':
                self.waveforms[waveform_type] = self.generate_square_wave(sample_size)
            elif waveform_type == 'triangle':
                self.waveforms[waveform_type] = self.generate_triangle_wave(sample_size)
            else:
                self.waveforms[waveform_type] = self.generate_sine_wave(sample_size)

    def get_waveform(self, waveform_type):
        if waveform_type not in self.waveforms:
            self.generate_waveform(waveform_type)
        return self.waveforms[waveform_type]

    def generate_sine_wave(self, sample_size=256):
        amplitude = FixedPoint.from_float(32767)
        return array.array("h",
            [int(FixedPoint.to_float(FixedPoint.multiply(
                Constants.SINE_TABLE[i % 256],
                amplitude
            ))) for i in range(sample_size)])

    def generate_saw_wave(self, sample_size=256):
        scale = FixedPoint.from_float(2.0 / sample_size)
        amplitude = FixedPoint.from_float(32767)
        return array.array("h",
            [int(FixedPoint.to_float(FixedPoint.multiply(
                FixedPoint.multiply(FixedPoint.from_float(i), scale) - FixedPoint.ONE,
                amplitude
            ))) for i in range(sample_size)])

    def generate_square_wave(self, sample_size=256, duty_cycle=0.5):
        duty = FixedPoint.from_float(duty_cycle)
        scale = FixedPoint.from_float(1.0 / sample_size)
        return array.array("h",
            [32767 if FixedPoint.multiply(FixedPoint.from_float(i), scale) < duty else -32767
             for i in range(sample_size)])

    def generate_triangle_wave(self, sample_size=256):
        scale = Constants.TRIANGLE_SCALE_FACTORS.get(sample_size,
            FixedPoint.from_float(32767.0 / (sample_size // 2)))
        
        half_size = sample_size // 2
        samples = array.array("h")
        
        for i in range(sample_size):
            if i < half_size:
                value = FixedPoint.multiply(FixedPoint.from_float(i), scale)
                value = value - Constants.MAX_AMPLITUDE
            else:
                value = FixedPoint.multiply(FixedPoint.from_float(sample_size - i), scale)
                value = value - Constants.MAX_AMPLITUDE
            
            samples.append(int(max(min(FixedPoint.to_float(value), 32767), -32768)))
        
        return samples

    def update(self):
        pass

class SynthAudioOutputManager:
    def __init__(self):
        self.mixer = audiomixer.Mixer(
            sample_rate=Constants.SAMPLE_RATE,
            buffer_size=Constants.AUDIO_BUFFER_SIZE,
            channel_count=2
        )
        self.audio = None
        self.synth = synthio.Synthesizer(
            sample_rate=Constants.SAMPLE_RATE,
            channel_count=2
        )
        self.volume = FixedPoint.from_float(1.0)
        
        self.active_voices = 0
        self.last_load_check = supervisor.ticks_ms()
        self.load_check_interval = Constants.MPE_LOAD_CHECK_INTERVAL
        self.load_factor = 0.0
        self.max_voices = Constants.MAX_ACTIVE_NOTES
        
        self._setup_audio()

    def calculate_load_factor(self):
        voice_load = min(1.0, self.active_voices / self.max_voices)
        
        try:
            buffer_fullness = self.synth.buffer_fullness
            buffer_load = min(1.0, buffer_fullness / Constants.AUDIO_BUFFER_SIZE)
        except Exception:
            buffer_load = 0.5
        
        load_factor = (0.7 * voice_load) + (0.3 * buffer_load)
        return min(1.0, max(0.0, load_factor))

    def update_load_factor(self):
        current_time = supervisor.ticks_ms()
        if supervisor.ticks_diff(current_time, self.last_load_check) >= self.load_check_interval:
            self.load_factor = self.calculate_load_factor()
            self.last_load_check = current_time

    def get_mpe_threshold_windows(self):
        base_windows = {
            'timbre': 20,
            'pressure': 10,
            'pitch': 5
        }
        
        return {
            key: int(window * (1 + (self.load_factor ** 2) * Constants.MAX_MPE_THRESHOLD_MULTIPLIER))
            for key, window in base_windows.items()
        }

    def should_skip_mpe_message(self, voice, message_type, new_value, last_update_time):
        current_time = supervisor.ticks_ms()
        threshold_windows = self.get_mpe_threshold_windows()
        
        time_since_last_update = supervisor.ticks_diff(current_time, last_update_time)
        threshold = threshold_windows.get(message_type, 10)
        
        if time_since_last_update < threshold:
            return not voice.is_significant_change(
                getattr(voice, message_type, 0),
                new_value,
                self.active_voices
            )
        
        return False

    def increment_active_voices(self):
        self.active_voices = min(self.active_voices + 1, self.max_voices)
        self.update_load_factor()

    def decrement_active_voices(self):
        self.active_voices = max(0, self.active_voices - 1)
        self.update_load_factor()

    def _setup_audio(self):
        if self.audio is not None:
            self.audio.deinit()

        self.audio = audiobusio.I2SOut(
            bit_clock=Constants.I2S_BIT_CLOCK,
            word_select=Constants.I2S_WORD_SELECT,
            data=Constants.I2S_DATA
        )
        self.audio.play(self.mixer)
        self.mixer.voice[0].play(self.synth)
        self.set_volume(FixedPoint.to_float(self.volume))

    def set_volume(self, volume):
        self.volume = FixedPoint.from_float(max(0.0, min(1.0, volume)))
        self.mixer.voice[0].level = FixedPoint.to_float(self.volume)

    def get_volume(self):
        return FixedPoint.to_float(self.volume)

    def get_synth(self):
        return self.synth

    def stop(self):
        self.audio.stop()
