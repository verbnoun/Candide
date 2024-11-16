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

    @staticmethod
    def clamp(value, min_val, max_val):
        """Clamp a fixed-point value between min and max"""
        return max(min(value, max_val), min_val)
    
class Constants:
    DEBUG = True
    NOTE_TRACKER = True  # Added for note lifecycle tracking
    PRESSURE_TRACKER = True
    
    # Audio Pins (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2
    I2S_DATA = board.GP0

    # Synthesizer Constants
    AUDIO_BUFFER_SIZE = 8192  # Increased buffer size
    SAMPLE_RATE = 44100
    
    # Note Management Constants
    MAX_ACTIVE_NOTES = 8  # Maximum simultaneous voices
    NOTE_TIMEOUT_MS = 2000  # 5 seconds in milliseconds before force note-off
    
    # MPE Load Management Constants
    MPE_LOAD_CHECK_INTERVAL = 100  # ms between load factor recalculations
    BASE_MPE_THRESHOLD = 10  # Base threshold for MPE message filtering (ms)
    MAX_MPE_THRESHOLD_MULTIPLIER = 4  # Maximum scaling factor for thresholds

    # MPE Significance Constants
    BASE_THRESHOLD = FixedPoint.from_float(0.05)  # Base threshold for significant changes (5%)
    MAX_THRESHOLD = FixedPoint.from_float(0.20)   # Maximum threshold cap (20%)
    THRESHOLD_SCALE = FixedPoint.from_float(1.5)  # Exponential scaling factor for threshold

    # Envelope Parameter Constants
    ENVELOPE_MIN_TIME = FixedPoint.from_float(0.001)  # Minimum envelope time
    ENVELOPE_MAX_TIME = FixedPoint.from_float(10.0)   # Maximum envelope time
    ENVELOPE_MIN_LEVEL = FixedPoint.from_float(0.0)   # Minimum envelope level
    ENVELOPE_MAX_LEVEL = FixedPoint.from_float(1.0)   # Maximum envelope level

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

    # Pre-calculated MIDI note frequencies
    MIDI_FREQUENCIES = [440.0 * 2 ** ((i - 69) / 12) for i in range(128)]

class Voice:
    def __init__(self, note=None, channel=None, velocity=1.0, output_manager=None):
        self.note = note
        self.channel = channel
        self.velocity = FixedPoint.normalize_midi_value(int(velocity * 127)) if velocity != 1.0 else FixedPoint.ONE
        self.pressure = 0  # Store as raw value, normalize when needed
        self.pitch_bend = 0  # Store as raw value, normalize when needed
        self.synth_note = None  # Will hold the synthio.Note instance
        self.timestamp = supervisor.ticks_ms()  # Added timestamp field
        self.release_tracking = False  # Flag to track release state
        self.active = False  # Flag to track if voice is active in fixed array
        
        # New initial parameter storage for MPE
        self.initial_parameters = {
            'pitch_bend': 0,
            'timbre': 0,
            'pressure': 0,
            'envelope': None,  # Will store initial envelope settings
        }
        
        # New timestamps for tracking MPE message updates
        self.last_timbre_update = 0
        self.last_pressure_update = 0
        self.last_pitch_update = 0
        
        # Reference to output manager for load management
        self.output_manager = output_manager

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

    def process_timbre(self, timbre_value):
        """
        Process timbre message with load-aware filtering
        """
        current_time = supervisor.ticks_ms()
        
        # If output manager exists and suggests skipping, return early
        if (self.output_manager and 
            self.output_manager.should_skip_mpe_message(
                self, 'timbre', timbre_value, self.last_timbre_update
            )):
            return False
        
        # Update timbre-related parameters
        # Placeholder: Implement specific timbre processing logic
        self.last_timbre_update = current_time
        return True

    def process_pressure(self, pressure_value):
        """
        Process pressure message with load-aware filtering
        """
        current_time = supervisor.ticks_ms()
        
        # If output manager exists and suggests skipping, return early
        if (self.output_manager and 
            self.output_manager.should_skip_mpe_message(
                self, 'pressure', pressure_value, self.last_pressure_update
            )):
            return False
        
        # Update pressure
        self.pressure = pressure_value
        self.last_pressure_update = current_time
        return True

    def process_pitch_bend(self, pitch_bend_value):
        """
        Process pitch bend message with load-aware filtering
        """
        current_time = supervisor.ticks_ms()
        
        # If output manager exists and suggests skipping, return early
        if (self.output_manager and 
            self.output_manager.should_skip_mpe_message(
                self, 'pitch', pitch_bend_value, self.last_pitch_update
            )):
            return False
        
        # Update pitch bend
        self.pitch_bend = pitch_bend_value
        self.last_pitch_update = current_time
        return True

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

    def apply_pressure(self, pressure_value, initial_envelope=None):
        """
        Apply pressure modulation to the envelope, respecting initial envelope values.
        
        Args:
            pressure_value (float): Normalized pressure value (0.0 to 1.0)
            initial_envelope (dict, optional): Initial envelope parameters to reference
        """
        if not self.pressure_enabled:
            return
        
        # Use initial envelope if provided, otherwise use current settings
        reference_envelope = initial_envelope or self.envelope_settings
        
        # Clamp pressure value
        pressure_value = max(0.0, min(1.0, pressure_value))
        self.current_pressure = FixedPoint.multiply(pressure_value, self.pressure_sensitivity)
        
        # Debug print for pressure application
        print(f"Applying Pressure: value={pressure_value}, sensitivity={FixedPoint.to_float(self.pressure_sensitivity)}")
        
        # Modulate envelope parameters based on pressure
        for target in self.pressure_targets:
            param = target['param']
            min_val = FixedPoint.from_float(target.get('min', 0.0))
            max_val = FixedPoint.from_float(target.get('max', 1.0))
            curve = target.get('curve', 'linear')
            
            # Get initial value from reference envelope if applicable
            if param.startswith('envelope.'):
                param_name = param.split('.')[1]
                initial_value = FixedPoint.from_float(reference_envelope.get(param_name, 0.0))
            else:
                initial_value = min_val
            
            # Apply pressure modulation with different curve types
            if curve == 'exponential':
                pressure_squared = FixedPoint.multiply(self.current_pressure, self.current_pressure)
                range_val = max_val - initial_value
                scaled_value = initial_value + FixedPoint.multiply(range_val, pressure_squared)
            else:  # linear
                range_val = max_val - initial_value
                scaled_value = initial_value + FixedPoint.multiply(range_val, self.current_pressure)
            
            # Debug print for parameter modulation
            print(f"Modulating {param}: initial={FixedPoint.to_float(initial_value)}, scaled={FixedPoint.to_float(scaled_value)}, curve={curve}")
            
            # Apply modulated value to appropriate parameter
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
        """
        Set envelope parameter in fixed-point, with safe bounds
        """
        if param in self.envelope_settings:
            # Clamp the value to safe envelope parameter ranges
            if param in ['attack', 'decay', 'release']:
                # Time parameters
                clamped_value = FixedPoint.clamp(
                    FixedPoint.from_float(value), 
                    Constants.ENVELOPE_MIN_TIME, 
                    Constants.ENVELOPE_MAX_TIME
                )
            elif param == 'sustain':
                # Level parameter
                clamped_value = FixedPoint.clamp(
                    FixedPoint.from_float(value), 
                    Constants.ENVELOPE_MIN_LEVEL, 
                    Constants.ENVELOPE_MAX_LEVEL
                )
            else:
                return  # Ignore unknown parameters
            
            self.envelope_settings[param] = clamped_value

    def create_envelope(self):
        """
        Create synthio Envelope using fixed-point math with safe conversions
        Minimizes float conversions and maintains precision
        """
        # Safely convert fixed-point values to floats with bounds checking
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
            attack_level=1.0,  # Kept as standard float
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
        
        # New attributes for load management
        self.active_voices = 0
        self.last_load_check = supervisor.ticks_ms()
        self.load_check_interval = Constants.MPE_LOAD_CHECK_INTERVAL
        self.load_factor = 0.0  # 0.0 to 1.0 representing system load
        self.max_voices = Constants.MAX_ACTIVE_NOTES
        
        self._setup_audio()

    def calculate_load_factor(self):
        """
        Calculate instantaneous load factor based on:
        1. Active voice count
        2. I2S buffer health (approximated by checking buffer fullness)
        """
        # Voice count contribution (linear scaling)
        voice_load = min(1.0, self.active_voices / self.max_voices)
        
        # Approximate I2S buffer health 
        # Note: This is a simplified approximation and might need platform-specific tuning
        try:
            buffer_fullness = self.synth.buffer_fullness
            buffer_load = min(1.0, buffer_fullness / Constants.AUDIO_BUFFER_SIZE)
        except Exception:
            buffer_load = 0.5  # Default mid-load if cannot determine
        
        # Weighted combination of voice and buffer load
        # More weight on voice count, some weight on buffer health
        load_factor = (0.7 * voice_load) + (0.3 * buffer_load)
        
        return min(1.0, max(0.0, load_factor))

    def update_load_factor(self):
        """
        Periodically update load factor to avoid constant recalculation
        """
        current_time = supervisor.ticks_ms()
        if supervisor.ticks_diff(current_time, self.last_load_check) >= self.load_check_interval:
            self.load_factor = self.calculate_load_factor()
            self.last_load_check = current_time

    def get_mpe_threshold_windows(self):
        """
        Dynamically calculate MPE message threshold windows based on load factor
        
        Returns a dictionary with threshold windows for different MPE message types:
        - timbre: Most skippable, widest window
        - pressure: Moderate skippability
        - pitch: Least skippable, narrowest window
        """
        base_windows = {
            'timbre': 20,   # ms
            'pressure': 10, # ms
            'pitch': 5      # ms
        }
        
        # Scale windows exponentially with load factor
        scaled_windows = {
            key: int(window * (1 + (self.load_factor ** 2) * Constants.MAX_MPE_THRESHOLD_MULTIPLIER))
            for key, window in base_windows.items()
        }
        
        return scaled_windows

    def should_skip_mpe_message(self, voice, message_type, new_value, last_update_time):
        """
        Determine whether to skip an MPE message based on load factor and message type
        
        Args:
            voice (Voice): The voice processing the MPE message
            message_type (str): 'timbre', 'pressure', or 'pitch'
            new_value (float): The new value for the message
            last_update_time (int): Timestamp of last update for this message type
        
        Returns:
            bool: Whether to skip processing this message
        """
        current_time = supervisor.ticks_ms()
        threshold_windows = self.get_mpe_threshold_windows()
        
        # Check time since last update against dynamically calculated threshold
        time_since_last_update = supervisor.ticks_diff(current_time, last_update_time)
        threshold = threshold_windows.get(message_type, 10)
        
        # Skip if time since last update is less than threshold and change is insignificant
        if time_since_last_update < threshold:
            # Use voice's significance check as additional filter
            return not voice.is_significant_change(
                getattr(voice, message_type, 0), 
                new_value, 
                self.active_voices
            )
        
        return False

    def increment_active_voices(self):
        """Increment active voice count"""
        self.active_voices = min(self.active_voices + 1, self.max_voices)
        self.update_load_factor()

    def decrement_active_voices(self):
        """Decrement active voice count"""
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
