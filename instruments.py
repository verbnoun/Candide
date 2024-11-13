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
            'waveform': 'triangle',
            'detune': 0.05
        }
        self.filter = {
            'type': 'low_pass',
            'cutoff': 3000,
            'resonance': 0.1
        }
        self.envelope = {
            'attack': 0.002,
            'decay': 0.15,
            'sustain': 0.6,
            'release': 0.4
        }
        self.midi = {
            'velocity_sensitivity': 0.9
        }
        self.pots = {
            0: {'cc': 74, 'name': 'Filter Cutoff', 'min': 500, 'max': 8000},
            1: {'cc': 71, 'name': 'Filter Resonance', 'min': 0, 'max': 0.5},
            2: {'cc': 94, 'name': 'Detune Amount', 'min': 0, 'max': 0.1},
            3: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.02},
            4: {'cc': 75, 'name': 'Decay Time', 'min': 0.1, 'max': 2.0},
            5: {'cc': 76, 'name': 'Sustain Level', 'min': 0.3, 'max': 1.0},
            6: {'cc': 72, 'name': 'Release Time', 'min': 0.2, 'max': 1.5},
            7: {'cc': 77, 'name': 'Bend Range', 'min': 2, 'max': 48},
            8: {'cc': 78, 'name': 'Bend Curve', 'min': 1, 'max': 4}
        }
        self.pitch_bend = {
            'enabled': True,
            'range': Constants.DEFAULT_MPE_PITCH_BEND_RANGE,
            'curve': 2
        }
        self.pressure = {
            'enabled': True,
            'sensitivity': 0.8,
            'targets': [
                {
                    'param': 'filter.cutoff',
                    'min': 1000,
                    'max': 8000,
                    'curve': 'exponential'
                },
                {
                    'param': 'envelope.sustain',
                    'min': 0.3,
                    'max': 0.9,
                    'curve': 'exponential'
                }
            ]
        }


class Organ(Instrument):
    def __init__(self):
        super().__init__("Organ")
        self.oscillator = {
            'waveform': 'saw', 
            'detune': 0.2
        }
        self.filter = {
            'type': 'low_pass',
            'cutoff': 2000,
            'resonance': 0.5
        }
        self.envelope = {
            'attack': 0.01,
            'decay': 0.1, 
            'sustain': 0.8,
            'release': 0.01  # Very short release
        }
        self.midi = {
            'velocity_sensitivity': 0.7
        }
        self.pots = {
            0: {'cc': 74, 'name': 'Filter Cutoff', 'min': 500, 'max': 8000},
            1: {'cc': 71, 'name': 'Filter Resonance', 'min': 0, 'max': 1},
            2: {'cc': 94, 'name': 'Detune Amount', 'min': 0, 'max': 0.5},
            3: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.1},
            4: {'cc': 75, 'name': 'Decay Time', 'min': 0.01, 'max': 0.5},
            5: {'cc': 76, 'name': 'Sustain Level', 'min': 0.4, 'max': 1.0},
            6: {'cc': 72, 'name': 'Release Time', 'min': 0.01, 'max': 1.0},
            7: {'cc': 77, 'name': 'Bend Range', 'min': 2, 'max': 48},
            8: {'cc': 78, 'name': 'Bend Curve', 'min': 1, 'max': 4}
        }
        self.pitch_bend = {
            'enabled': True,
            'range': Constants.DEFAULT_MPE_PITCH_BEND_RANGE,
            'curve': 2
        }
        self.pressure = {
            'enabled': True,
            'sensitivity': 1.0,  # Full sensitivity for direct control
            'targets': [
                {
                    'param': 'envelope.sustain',
                    'min': 0.0,  # Full range
                    'max': 1.0,
                    'curve': 'linear'
                }
            ]
        }


class Womp(Instrument):
    def __init__(self):
        super().__init__("Womp")
        self.oscillator = {
            'waveform': 'saw',     # Saw wave for rich harmonic content
            'detune': 0.15         # Significant detuning for thickness
        }
        self.filter = {
            'type': 'low_pass',    # Low pass filter for that classic wobble
            'cutoff': 1000,        # Start with lower cutoff for growl
            'resonance': 1.8       # High resonance for aggressive sound
        }
        self.envelope = {
            'attack': 0.01,        # Fast attack for punchy sound
            'decay': 0.2,          # Moderate decay
            'sustain': 0.7,        # Higher sustain for continuous sound
            'release': 0.15        # Quick release for tight bass drops
        }
        self.midi = {
            'velocity_sensitivity': 0.9  # High velocity sensitivity for expression
        }
        self.pots = {
            0: {'cc': 74, 'name': 'Filter Cutoff', 'min': 150, 'max': 8000},    # Wide filter range
            1: {'cc': 71, 'name': 'Filter Resonance', 'min': 0.7, 'max': 1.9},  # High resonance range
            2: {'cc': 94, 'name': 'Detune Amount', 'min': 0.1, 'max': 0.3},     # Increased detune range
            3: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.2},     # Quick attack options
            4: {'cc': 75, 'name': 'Decay Time', 'min': 0.1, 'max': 0.5},        # Moderate decay range
            5: {'cc': 76, 'name': 'Sustain Level', 'min': 0.4, 'max': 0.9},     # Higher sustain range
            6: {'cc': 72, 'name': 'Release Time', 'min': 0.1, 'max': 0.3},      # Quick release options
            7: {'cc': 77, 'name': 'Bend Range', 'min': 12, 'max': 24},          # Wider bend range
            8: {'cc': 78, 'name': 'Bend Curve', 'min': 1, 'max': 4}             # More curve options
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
                    'param': 'filter.cutoff',  # Filter movement for wobble
                    'min': 200,               # Very low cutoff for growl
                    'max': 6000,              # High cutoff for screech
                    'curve': 'exponential'    # Exponential for dramatic sweeps
                },
                {
                    'param': 'filter.resonance',  # Dynamic resonance
                    'min': 0.8,
                    'max': 1.9,
                    'curve': 'exponential'
                },
                {
                    'param': 'envelope.sustain',  # Pressure affects sustain
                    'min': 0.4,
                    'max': 0.9,
                    'curve': 'linear'
                }
            ]
        }

class WindChime(Instrument):
    def __init__(self):
        super().__init__("Wind Chime")
        self.oscillator = {
            'waveform': 'triangle',  # Triangle wave gives a more metallic tone than sine
            'detune': 0.003  # Slight detuning for that shimmering effect
        }
        self.filter = {
            'type': 'band_pass',  # Band-pass to emphasize metallic harmonics
            'cutoff': 2000,  # Center frequency for metallic character
            'resonance': 0.8  # Moderate resonance for ringing quality
        }
        self.envelope = {
            'attack': 0.001,  # Very fast attack like striking metal
            'decay': 0.1,     # Quick initial decay
            'sustain': 0.3,   # Moderate sustain level
            'release': 2.0    # Long release for that lingering ring
        }
        self.midi = {
            'velocity_sensitivity': 1.0  # Full velocity sensitivity for dynamics
        }
        self.pots = {
            0: {'cc': 74, 'name': 'Filter Cutoff', 'min': 1000, 'max': 4000},
            1: {'cc': 71, 'name': 'Filter Resonance', 'min': 0.5, 'max': 1.5},
            2: {'cc': 94, 'name': 'Detune Amount', 'min': 0.001, 'max': 0.01},
            3: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.01},
            4: {'cc': 75, 'name': 'Decay Time', 'min': 0.05, 'max': 0.3},
            5: {'cc': 76, 'name': 'Sustain Level', 'min': 0.1, 'max': 0.5},
            6: {'cc': 72, 'name': 'Release Time', 'min': 1.0, 'max': 4.0},
            7: {'cc': 77, 'name': 'Bend Range', 'min': 2, 'max': 12},
            8: {'cc': 78, 'name': 'Bend Curve', 'min': 1, 'max': 2}
        }
        self.pitch_bend = {
            'enabled': True,
            'range': 2,  # Smaller pitch bend range for subtle variations
            'curve': 1   # Linear curve for predictable bends
        }
        self.pressure = {
            'enabled': True,
            'sensitivity': 0.6,
            'targets': [
                {
                    'param': 'filter.cutoff',
                    'min': 1500,
                    'max': 3000,
                    'curve': 'exponential'
                },
                {
                    'param': 'envelope.release',
                    'min': 1.0,
                    'max': 3.0,
                    'curve': 'linear'
                }
            ]
        }