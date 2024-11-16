class Constants:
    DEBUG = False
    
    # MPE Constants
    DEFAULT_MPE_PITCH_BEND_RANGE = 48  # Default 48 semitones for MPE
    DEFAULT_PRESSURE_SENSITIVITY = 0.7
    
    # MIDI CC Range
    MIN_CC = 0
    MAX_CC = 127

class Instrument:
    available_instruments = []
    current_instrument_index = 0

    def __init__(self, name):
        self.name = name
        self.oscillator = {'waveform': 'sine'}  # Default waveform
        self.filter = None
        self.envelope = None
        self.midi = None
        self.pots = {}
        self.logger = None
        self.pitch_bend = {
            'enabled': True,  # Default to enabled for MPE
            'range': Constants.DEFAULT_MPE_PITCH_BEND_RANGE,
            'curve': 2   # Default quadratic curve factor
        }
        self.pressure = {
            'enabled': True,  # Default to enabled for MPE
            'sensitivity': Constants.DEFAULT_PRESSURE_SENSITIVITY,
            'targets': [
                {
                    'param': 'filter.cutoff',
                    'min': 500,
                    'max': 8000,
                    'curve': 'exponential'
                },
                {
                    'param': 'envelope.sustain',
                    'min': 0.3,
                    'max': 1.0,
                    'curve': 'linear'
                }
            ]
        }
        Instrument.available_instruments.append(self)

    def get_configuration(self):
        config = {'name': self.name}
        for attr in ['oscillator', 'filter', 'envelope', 'midi', 'pitch_bend', 'pressure']:
            if hasattr(self, attr) and getattr(self, attr) is not None:
                config[attr] = getattr(self, attr)
        if self.pots:
            config['pots'] = self.pots
        return config

    def generate_cc_config(self):
        """Generate CC configuration string in format expected by Bartleby.
        Returns string in format: cc:0=74,1=71,2=73,...
        Validates CC numbers are in valid range.
        """
        try:
            cc_mappings = []
            for pot_num, pot_config in sorted(self.pots.items()):
                cc_num = pot_config['cc']
                # Validate CC number range
                if not Constants.MIN_CC <= cc_num <= Constants.MAX_CC:
                    print(f"Warning: Invalid CC number {cc_num} for pot {pot_num}")
                    continue
                cc_mappings.append(f"{pot_num}={cc_num}")
            
            if not cc_mappings:
                print("Warning: No valid CC mappings found")
                return None
                
            config_string = "cc: " + ",".join(cc_mappings)
            
            if Constants.DEBUG:
                print(f"Generated config for {self.name}: {config_string}")
                
            return config_string
            
        except Exception as e:
            print(f"Error generating CC config: {str(e)}")
            return None

    @classmethod
    def handle_instrument_change(cls, direction):
        if Constants.DEBUG:
            print(f"Handling instrument change, direction={direction}")
            print(f"Available instruments: {[i.name for i in cls.available_instruments]}")
        cls.current_instrument_index = (cls.current_instrument_index + direction) % len(cls.available_instruments)
        current_instrument = cls.get_current_instrument()
        return current_instrument

    @classmethod
    def get_current_instrument(cls):
        return cls.available_instruments[cls.current_instrument_index]


class Piano(Instrument):
    def __init__(self):
        super().__init__("Piano")
        self.oscillator = {
            'waveform': 'triangle',  # Base waveform for piano-like harmonics
            'detune': 0.002  # Subtle detuning for natural string behavior
        }
        self.filter = {
            'type': 'low_pass',
            'cutoff': 5000,  # Higher cutoff for brighter piano tone
            'resonance': 0.2  # Low resonance for natural sound
        }
        self.envelope = {
            'attack': 0.001,  # Very fast attack for hammer strike
            'decay': 0.8,    # Natural decay for piano strings
            'sustain': 0.0,  # No sustain - realistic piano behavior
            'release': 0.3   # Quick release when key is released
        }
        self.midi = {
            'velocity_sensitivity': 1.0  # Full velocity sensitivity for dynamics
        }
        self.pots = {
            0: {'cc': 74, 'name': 'Brightness', 'min': 3000, 'max': 8000},  # Filter cutoff for tone control
            1: {'cc': 71, 'name': 'Resonance', 'min': 0.1, 'max': 0.4},     # Subtle resonance control
            2: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.01}, # Very short attack range
            3: {'cc': 75, 'name': 'Decay Time', 'min': 0.6, 'max': 1.2},     # Natural decay range
            4: {'cc': 72, 'name': 'Release Time', 'min': 0.1, 'max': 0.5}    # Natural release range
        }
        self.pitch_bend = {
            'enabled': False,  # Pianos don't pitch bend
            'range': 0,
            'curve': 1
        }
        self.pressure = {
            'enabled': False,  # No pressure sensitivity for realistic piano
            'sensitivity': 0,
            'targets': []
        }


class Organ(Instrument):
    def __init__(self):
        super().__init__("Organ")
        self.oscillator = {
            'waveform': 'sine',  # Pure sine waves for organ pipes
            'detune': 0.0      # No detuning for clean organ sound
        }
        self.filter = {
            'type': 'low_pass',
            'cutoff': 2000,
            'resonance': 0.3
        }
        self.envelope = {
            'attack': 0.05,    # Slight attack for pipe speak
            'decay': 0.0,      # No decay - organ pipes sustain
            'sustain': 1.0,    # Full sustain
            'release': 0.08    # Quick release when key is released
        }
        self.midi = {
            'velocity_sensitivity': 0.0  # Organs don't respond to velocity
        }
        self.pots = {
            0: {'cc': 74, 'name': 'Filter Cutoff', 'min': 500, 'max': 8000},
            1: {'cc': 71, 'name': 'Filter Resonance', 'min': 0, 'max': 0.5},
            2: {'cc': 73, 'name': 'Attack Time', 'min': 0.02, 'max': 0.1},
            3: {'cc': 72, 'name': 'Release Time', 'min': 0.05, 'max': 0.2}
        }
        self.pitch_bend = {
            'enabled': False,  # Organs don't pitch bend
            'range': 0,
            'curve': 1
        }
        self.pressure = {
            'enabled': True,
            'sensitivity': 1.0,  # Full sensitivity for expression pedal simulation
            'targets': [
                {
                    'param': 'envelope.sustain',  # Pressure controls volume like an expression pedal
                    'min': 0.0001,
                    'max': 1.0,
                    'curve': 'linear'
                }
            ]
        }


class Womp(Instrument):
    def __init__(self):
        super().__init__("Womp")
        self.oscillator = {
            'waveform': 'saw',      # Rich harmonic content for aggressive sound
            'detune': 0.2          # Heavy detuning for thickness
        }
        self.filter = {
            'type': 'low_pass',    
            'cutoff': 800,         # Low initial cutoff for growl
            'resonance': 2.0       # High resonance for aggressive character
        }
        self.envelope = {
            'attack': 0.005,       # Very fast attack for punch
            'decay': 0.1,          # Quick initial decay
            'sustain': 0.0,        # Start with no sustain
            'release': 0.1         # Quick release
        }
        self.midi = {
            'velocity_sensitivity': 1.0  # Full velocity sensitivity
        }
        self.pots = {
            0: {'cc': 74, 'name': 'Filter Cutoff', 'min': 150, 'max': 8000},
            1: {'cc': 71, 'name': 'Filter Resonance', 'min': 1.0, 'max': 2.5},
            2: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.1},
            3: {'cc': 72, 'name': 'Release Time', 'min': 0.05, 'max': 0.3}
        }
        self.pitch_bend = {
            'enabled': True,
            'range': 12,           # Full octave bend range
            'curve': 2             # Non-linear curve for expressive bends
        }
        self.pressure = {
            'enabled': True,
            'sensitivity': 1.0,    # Full pressure sensitivity
            'targets': [
                {
                    'param': 'envelope.sustain',  # Pressure controls sustain level
                    'min': 0.0,
                    'max': 0.8,
                    'curve': 'exponential'
                },
                {
                    'param': 'filter.cutoff',     # Pressure opens filter
                    'min': 800,
                    'max': 6000,
                    'curve': 'exponential'
                }
            ]
        }


class WindChime(Instrument):
    def __init__(self):
        super().__init__("Wind Chime")
        self.oscillator = {
            'waveform': 'sine',    # Pure tone for metallic sound
            'detune': 0.01         # Slight detuning for natural variation
        }
        self.filter = {
            'type': 'band_pass',   # Band-pass for resonant, metallic character
            'cutoff': 3000,        # Higher center frequency for bright tone
            'resonance': 1.5       # High resonance for ringing quality
        }
        self.envelope = {
            'attack': 0.001,       # Instant attack
            'decay': 0.2,          # Quick initial decay
            'sustain': 0.1,        # Low sustain for gentle sound
            'release': 2.0         # Long release for natural fade
        }
        self.midi = {
            'velocity_sensitivity': 0.8
        }
        self.pots = {
            0: {'cc': 74, 'name': 'Filter Cutoff', 'min': 2000, 'max': 5000},
            1: {'cc': 71, 'name': 'Filter Resonance', 'min': 1.0, 'max': 2.0},
            2: {'cc': 73, 'name': 'Decay Time', 'min': 0.1, 'max': 0.5},
            3: {'cc': 72, 'name': 'Release Time', 'min': 1.0, 'max': 4.0}
        }
        self.pitch_bend = {
            'enabled': True,
            'range': 4,            # Small range for subtle variations
            'curve': 1             # Linear response
        }
        self.pressure = {
            'enabled': True,
            'sensitivity': 0.8,
            'targets': [
                {
                    'param': 'filter.cutoff',     # Pressure affects brightness
                    'min': 2000,
                    'max': 4000,
                    'curve': 'exponential'
                },
                {
                    'param': 'filter.resonance',  # Pressure affects resonance
                    'min': 1.0,
                    'max': 2.0,
                    'curve': 'linear'
                },
                {
                    'param': 'oscillator.detune', # Pressure affects detuning
                    'min': 0.005,
                    'max': 0.02,
                    'curve': 'linear'
                }
            ]
        }


def initialize_instruments():
    Piano()
    Organ()
    Womp()
    WindChime()

# Call the function at the module level
initialize_instruments()
