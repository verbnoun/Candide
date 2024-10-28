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
            'enabled': False,
            'range': 2,  # Default range of 2 semitones
            'curve': 2   # Default quadratic curve factor
        }
        Instrument.available_instruments.append(self)

    def get_configuration(self):
        config = {'name': self.name}
        for attr in ['oscillator', 'filter', 'envelope', 'midi', 'pitch_bend']:
            if hasattr(self, attr) and getattr(self, attr) is not None:
                config[attr] = getattr(self, attr)
        if self.pots:
            config['pots'] = self.pots
        return config

    @classmethod
    def handle_instrument_change(cls, direction):
        cls.current_instrument_index = (cls.current_instrument_index + direction) % len(cls.available_instruments)
        current_instrument = cls.get_current_instrument()
        return current_instrument

    @classmethod
    def get_current_instrument(cls):
        return cls.available_instruments[cls.current_instrument_index]

class Piano(Instrument):
    def __init__(self):
        super().__init__("Electric Piano")
        self.oscillator = {
            'waveform': 'triangle',
            'detune': 0.05
        }
        self.filter = {
            'type': 'low_pass',
            'cutoff': 2000,
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
            1: {'cc': 74, 'name': 'Filter Cutoff', 'min': 500, 'max': 5000},
            2: {'cc': 71, 'name': 'Filter Resonance', 'min': 0, 'max': 0.5},
            3: {'cc': 94, 'name': 'Detune Amount', 'min': 0, 'max': 0.1},
            4: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.02},
            5: {'cc': 75, 'name': 'Decay Time', 'min': 0.1, 'max': 2.0},
            6: {'cc': 76, 'name': 'Sustain Level', 'min': 0, 'max': 0},
            7: {'cc': 72, 'name': 'Release Time', 'min': 0.2, 'max': 1.5}
        }
        self.pitch_bend = {
            'enabled': False
        }

class ElectricOrgan(Instrument):
    def __init__(self):
        super().__init__("Electric Organ")
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
            'release': 0.2
        }
        self.midi = {
            'velocity_sensitivity': 0.2
        }
        self.pots = {
            1: {'cc': 74, 'name': 'Filter Cutoff', 'min': 500, 'max': 5000},
            2: {'cc': 71, 'name': 'Filter Resonance', 'min': 0, 'max': 1},
            3: {'cc': 94, 'name': 'Detune Amount', 'min': 0, 'max': 0.5},
            4: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.1},
            5: {'cc': 75, 'name': 'Decay Time', 'min': 0.01, 'max': 0.5},
            6: {'cc': 76, 'name': 'Sustain Level', 'min': 0, 'max': 1},
            7: {'cc': 72, 'name': 'Release Time', 'min': 0.01, 'max': 1}
        }
        self.pitch_bend = {
            'enabled': False
        }

class BendableOrgan(Instrument):
    def __init__(self):
        super().__init__("Bendable Organ")
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
            'release': 0.2
        }
        self.midi = {
            'velocity_sensitivity': 0.2
        }
        self.pots = {
            1: {'cc': 74, 'name': 'Filter Cutoff', 'min': 500, 'max': 5000},
            2: {'cc': 71, 'name': 'Filter Resonance', 'min': 0, 'max': 1},
            3: {'cc': 94, 'name': 'Detune Amount', 'min': 0, 'max': 0.5},
            4: {'cc': 73, 'name': 'Attack Time', 'min': 0.001, 'max': 0.1},
            5: {'cc': 75, 'name': 'Decay Time', 'min': 0.01, 'max': 0.5},
            6: {'cc': 76, 'name': 'Sustain Level', 'min': 0, 'max': 1},
            7: {'cc': 72, 'name': 'Release Time', 'min': 0.01, 'max': 1},
            8: {'cc': 77, 'name': 'Bend Range', 'min': 0, 'max': 3},
            9: {'cc': 78, 'name': 'Bend Curve', 'min': 0, 'max': 1}
        }
        self.pitch_bend = {
            'enabled': True,
            'range': 2,
            'curve': 2
        }
