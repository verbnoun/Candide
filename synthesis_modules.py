import board
import synthio
import audiobusio
import math
import array
import audiomixer
import supervisor

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
    
    @staticmethod
    def from_float(value):
        """Convert float to fixed-point integer with safe bounds"""
        try:
            # Clamp value to prevent overflow
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

class Constants:
    DEBUG = False
    NOTE_TRACKER = False  # Added for note lifecycle tracking
    # Audio Pins (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2
    I2S_DATA = board.GP0

    # Synthesizer Constants
    AUDIO_BUFFER_SIZE = 8192 #4096
    SAMPLE_RATE = 44100
    
    # Note Management Constants
    MAX_ACTIVE_NOTES = 8  # Maximum simultaneous voices
    NOTE_TIMEOUT_MS = 2000  # 5 seconds in milliseconds before force note-off
    
    # MPE Significance Constants
    BASE_THRESHOLD = FixedPoint.from_float(0.05)  # Base threshold for significant changes (5%)
    MAX_THRESHOLD = FixedPoint.from_float(0.20)   # Maximum threshold cap (20%)
    THRESHOLD_SCALE = FixedPoint.from_float(1.5)  # Exponential scaling factor for threshold

    # Pre-calculated sine lookup table
    SINE_TABLE = [FixedPoint.from_float(math.sin(2 * math.pi * i / 256)) for i in range(256)]

    # Pre-calculated triangle wave scale factors
    TRIANGLE_SCALE_FACTORS = {
        128: FixedPoint.from_float(32767.0 / 64),   # For 128-sample wave
        256: FixedPoint.from_float(32767.0 / 128),  # For 256-sample wave
        512: FixedPoint.from_float(32767.0 / 256)   # For 512-sample wave
    }

    # Pre-calculated amplitude constants
    MAX_AMPLITUDE = FixedPoint.from_float(32767.0)
    MIN_AMPLITUDE = FixedPoint.from_float(-32767.0)

class Voice:
    def __init__(self, note=None, channel=None, velocity=1.0):
        self.note = note
        self.channel = channel
        self.velocity = FixedPoint.normalize_midi_value(int(velocity * 127)) if velocity != 1.0 else FixedPoint.ONE
        self.pressure = 0  # Store as raw value, normalize when needed
        self.pitch_bend = 0  # Store as raw value, normalize when needed
        self.synth_note = None  # Will hold the synthio.Note instance
        self.timestamp = supervisor.ticks_ms()  # Added timestamp field
        self.release_tracking = False  # Flag to track release state
        self.active = False  # Flag to track if voice is active in fixed array
        if Constants.NOTE_TRACKER and note is not None:
            print(f"[NOTE_TRACKER] Voice Created:")
            print(f"  Channel: {channel}")
            print(f"  Note: {note}")
            print(f"  Velocity: {FixedPoint.to_float(self.velocity):.3f}")
            print(f"  Time: {self.timestamp}ms")

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

    def log_release_progression(self, synth):
        """Track and log note release progression"""
        if not Constants.NOTE_TRACKER or not self.synth_note:
            return

        note_state = synth.note_info(self.synth_note)
        
        if note_state[0] is not None:
            if not self.release_tracking:
                print(f"[NOTE_TRACKER] Release Started:")
                print(f"  Channel: {self.channel}")
                print(f"  Note: {self.note}")
                self.release_tracking = True

            print(f"[NOTE_TRACKER] Release Progression:")
            print(f"  State: {note_state[0]}")
            print(f"  Envelope Value: {FixedPoint.to_float(note_state[1]):.4f}")
        elif self.release_tracking:
            print(f"[NOTE_TRACKER] Release Completed:")
            print(f"  Channel: {self.channel}")
            print(f"  Note: {self.note}")
            self.release_tracking = False

    def refresh_timestamp(self):
        """Update the timestamp to current time"""
        old_timestamp = self.timestamp
        self.timestamp = supervisor.ticks_ms()
        if Constants.NOTE_TRACKER:
            print(f"[NOTE_TRACKER] Voice Activity:")
            print(f"  Channel: {self.channel}")
            print(f"  Note: {self.note}")
            print(f"  Pressure: {FixedPoint.to_float(self.pressure):.3f}")
            print(f"  Pitch Bend: {FixedPoint.to_float(self.pitch_bend):.3f}")
            print(f"  Time: {self.timestamp}ms")

    def log_envelope_update(self, envelope):
        """Log envelope parameter changes"""
        if Constants.NOTE_TRACKER:
            print(f"[NOTE_TRACKER] Envelope Update:")
            print(f"  Channel: {self.channel}")
            print(f"  Note: {self.note}")
            print(f"  Attack: {FixedPoint.to_float(envelope.attack_time):.3f}s")
            print(f"  Decay: {FixedPoint.to_float(envelope.decay_time):.3f}s")
            print(f"  Sustain: {FixedPoint.to_float(envelope.sustain_level):.3f}")
            print(f"  Release: {FixedPoint.to_float(envelope.release_time):.3f}s")

    def log_release(self):
        """Log note release"""
        if Constants.NOTE_TRACKER:
            print(f"[NOTE_TRACKER] Voice Released:")
            print(f"  Channel: {self.channel}")
            print(f"  Note: {self.note}")
            print(f"  Final Pressure: {FixedPoint.to_float(self.pressure):.3f}")
            print(f"  Final Pitch Bend: {FixedPoint.to_float(self.pitch_bend):.3f}")
            print(f"  Total Duration: {supervisor.ticks_ms() - self.timestamp}ms")

class SynthEngine:
    def __init__(self):
        self.envelope_settings = {}
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

    def apply_pressure(self, pressure_value):
        if not self.pressure_enabled:
            return
            
        pressure_value = max(0.0, min(1.0, pressure_value))
        self.current_pressure = FixedPoint.multiply(pressure_value, self.pressure_sensitivity)
        
        for target in self.pressure_targets:
            param = target['param']
            min_val = FixedPoint.from_float(target.get('min', 0.0))
            max_val = FixedPoint.from_float(target.get('max', 1.0))
            curve = target.get('curve', 'linear')
            
            if curve == 'exponential':
                pressure_squared = FixedPoint.multiply(self.current_pressure, self.current_pressure)
                range_val = max_val - min_val
                scaled_value = min_val + FixedPoint.multiply(range_val, pressure_squared)
            else:  # linear
                range_val = max_val - min_val
                scaled_value = min_val + FixedPoint.multiply(range_val, self.current_pressure)
            
            if param.startswith('envelope.'):
                param_name = param.split('.')[1]
                self.set_envelope_param(param_name, FixedPoint.to_float(scaled_value))
            elif param.startswith('filter.'):
                param_name = param.split('.')[1]
                if param_name == 'cutoff':
                    self.set_filter_cutoff(FixedPoint.to_float(scaled_value))
                elif param_name == 'resonance':
                    self.set_filter_resonance(FixedPoint.to_float(scaled_value))

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
            self.envelope_settings[param] = FixedPoint.from_float(value)
    
    def create_envelope(self):
        return synthio.Envelope(
            attack_time=FixedPoint.to_float(self.envelope_settings.get('attack', FixedPoint.from_float(0.01))),
            decay_time=FixedPoint.to_float(self.envelope_settings.get('decay', FixedPoint.from_float(0.1))),
            release_time=FixedPoint.to_float(self.envelope_settings.get('release', FixedPoint.from_float(0.1))),
            attack_level=1.0,
            sustain_level=FixedPoint.to_float(self.envelope_settings.get('sustain', FixedPoint.from_float(0.8)))
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
        return array.array("h", 
            [int(FixedPoint.to_float(FixedPoint.multiply(
                Constants.SINE_TABLE[i % 256],
                FixedPoint.from_float(32767)
            ))) for i in range(sample_size)])

    def generate_saw_wave(self, sample_size=256):
        return array.array("h", 
            [int(FixedPoint.to_float(FixedPoint.multiply(
                FixedPoint.from_float(i / sample_size * 2 - 1),
                FixedPoint.from_float(32767)
            ))) for i in range(sample_size)])

    def generate_square_wave(self, sample_size=256, duty_cycle=0.5):
        duty = FixedPoint.from_float(duty_cycle)
        return array.array("h", 
            [32767 if FixedPoint.from_float(i / sample_size) < duty else -32767 
             for i in range(sample_size)])

    def generate_triangle_wave(self, sample_size=256):
        """
        Optimized triangle wave generation using pre-calculated scale factors
        and fixed-point math throughout
        """
        # Use pre-calculated scale factor based on sample size
        scale = Constants.TRIANGLE_SCALE_FACTORS.get(sample_size, 
            FixedPoint.from_float(32767.0 / (sample_size // 2)))
        
        half_size = sample_size // 2
        samples = array.array("h")
        
        for i in range(sample_size):
            if i < half_size:
                # Rising phase: -32767 to 32767 over half_size samples
                value = FixedPoint.multiply(FixedPoint.from_float(i), scale)
                value = value - Constants.MAX_AMPLITUDE  # Center around zero
            else:
                # Falling phase: 32767 to -32767 over half_size samples
                value = FixedPoint.multiply(FixedPoint.from_float(sample_size - i), scale)
                value = value - Constants.MAX_AMPLITUDE  # Center around zero
            
            # Convert to 16-bit integer, ensuring bounds
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
        self._setup_audio()

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
