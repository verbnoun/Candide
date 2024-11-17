from synth_constants import ModSource, ModTarget

class InstrumentConfig:
    """Base class for instrument configurations"""
    def __init__(self, name):
        self.name = name
        self.config = {
            'name': name,
            'oscillator': {
                'waveform': 'sine',
                'detune': 0.0
            },
            'filter': {
                'type': 'low_pass',
                'cutoff': 2000,
                'resonance': 0.7
            },
            'envelope': {
                'attack': 0.01,
                'decay': 0.1,
                'sustain': 0.8,
                'release': 0.2
            },
            'modulation': [],  # List of modulation routings
            'performance': {
                'pressure_enabled': True,
                'pressure_sensitivity': 1.0,
                'pitch_bend_enabled': True,
                'pitch_bend_range': 48,
            },
            'lfo': {},  # LFO configurations
            'ring': None  # Ring modulation settings if needed
        }

    def add_modulation_route(self, source, target, amount=1.0, curve='linear'):
        """Add a modulation routing"""
        self.config['modulation'].append({
            'source': source,
            'target': target,
            'amount': amount,
            'curve': curve
        })

    def add_lfo(self, name, rate, shape='triangle', min_value=0.0, max_value=1.0):
        """Add an LFO configuration"""
        self.config['lfo'][name] = {
            'rate': rate,
            'shape': shape,
            'min_value': min_value,
            'max_value': max_value
        }

    def set_ring_modulation(self, frequency, waveform='sine', bend_range=0):
        """Configure ring modulation"""
        self.config['ring'] = {
            'frequency': frequency,
            'waveform': waveform,
            'bend_range': bend_range
        }

    def get_config(self):
        """Get complete configuration"""
        return self.config

class Piano(InstrumentConfig):
    """Traditional piano without MPE"""
    def __init__(self):
        super().__init__("Piano")
        
        # Basic piano configuration
        self.config.update({
            'oscillator': {
                'waveform': 'triangle',
                'detune': 0.001  # Slight detuning for richness
            },
            'filter': {
                'type': 'low_pass',
                'cutoff': 5000,
                'resonance': 0.2
            },
            'envelope': {
                'attack': 0.001,
                'decay': 0.8,
                'sustain': 0.0,  # Piano-like decay
                'release': 0.3
            },
            'performance': {
                'pressure_enabled': False,
                'pitch_bend_enabled': False,
                'velocity_sensitivity': 1.0
            }
        })
        
        # Simple velocity to amplitude mapping
        self.add_modulation_route(
            ModSource.VELOCITY,
            ModTarget.AMPLITUDE,
            amount=1.0
        )

class Organ(InstrumentConfig):
    """Organ with pressure-controlled volume"""
    def __init__(self):
        super().__init__("Organ")
        
        self.config.update({
            'oscillator': {
                'waveform': 'sine',
                'detune': 0.0
            },
            'filter': {
                'type': 'low_pass',
                'cutoff': 2000,
                'resonance': 0.3
            },
            'envelope': {
                'attack': 0.05,
                'decay': 0.0,
                'sustain': 1.0,
                'release': 0.08
            },
            'performance': {
                'pressure_enabled': True,
                'pressure_sensitivity': 1.0,
                'pitch_bend_enabled': False,
                'velocity_sensitivity': 0.0  # Organ doesn't use velocity
            }
        })
        
        # Pressure controls amplitude
        self.add_modulation_route(
            ModSource.PRESSURE,
            ModTarget.AMPLITUDE,
            amount=0.8,
            curve='exponential'
        )

class Womp(InstrumentConfig):
    """Full MPE expression instrument"""
    def __init__(self):
        super().__init__("Womp")
        
        self.config.update({
            'oscillator': {
                'waveform': 'saw',
                'detune': 0.2
            },
            'filter': {
                'type': 'low_pass',
                'cutoff': 800,
                'resonance': 1.8
            },
            'envelope': {
                'attack': 0.005,
                'decay': 0.1,
                'sustain': 0.7,
                'release': 0.2
            },
            'performance': {
                'pressure_enabled': True,
                'pressure_sensitivity': 1.0,
                'pitch_bend_enabled': True,
                'pitch_bend_range': 48
            }
        })
        
        # Add wobble LFO
        self.add_lfo('wobble', rate=5.0, shape='triangle', min_value=0.3, max_value=1.0)
        
        # Add ring modulation
        self.set_ring_modulation(
            frequency=2.0,
            waveform='triangle',
            bend_range=12
        )
        
        # Rich modulation routing
        self.add_modulation_route(
            ModSource.PRESSURE,
            ModTarget.FILTER_CUTOFF,
            amount=0.7,
            curve='exponential'
        )
        
        self.add_modulation_route(
            ModSource.TIMBRE,
            ModTarget.FILTER_RESONANCE,
            amount=0.6
        )
        
        self.add_modulation_route(
            ModSource.PRESSURE,
            ModTarget.RING_FREQUENCY,
            amount=0.5
        )
        
        self.add_modulation_route(
            'wobble',  # LFO name
            ModTarget.FILTER_CUTOFF,
            amount=0.3
        )

class WindChime(InstrumentConfig):
    """Ethereal wind chime with inter-note modulation"""
    def __init__(self):
        super().__init__("Wind Chime")
        
        self.config.update({
            'oscillator': {
                'waveform': 'sine',
                'detune': 0.01
            },
            'filter': {
                'type': 'band_pass',
                'cutoff': 3000,
                'resonance': 1.5
            },
            'envelope': {
                'attack': 0.001,
                'decay': 0.2,
                'sustain': 0.1,
                'release': 2.0
            },
            'performance': {
                'pressure_enabled': True,
                'pressure_sensitivity': 0.8,
                'pitch_bend_enabled': True,
                'pitch_bend_range': 4
            }
        })
        
        # Shimmer LFO
        self.add_lfo('shimmer', 
            rate=0.5,
            shape='sine',
            min_value=0.0,
            max_value=1.0
        )
        
        # Wind LFO
        self.add_lfo('wind',
            rate=0.2,
            shape='triangle',
            min_value=0.2,
            max_value=0.8
        )
        
        # Ring modulation for harmonics
        self.set_ring_modulation(
            frequency=1.5,
            waveform='sine',
            bend_range=2
        )
        
        # Modulation routing
        self.add_modulation_route(
            ModSource.PRESSURE,
            ModTarget.RING_FREQUENCY,
            amount=0.3,
            curve='exponential'
        )
        
        self.add_modulation_route(
            'shimmer',
            ModTarget.FILTER_CUTOFF,
            amount=0.2
        )
        
        self.add_modulation_route(
            'wind',
            ModTarget.AMPLITUDE,
            amount=0.3
        )
        
        self.add_modulation_route(
            ModSource.PRESSURE,
            ModTarget.FILTER_RESONANCE,
            amount=0.4
        )

def create_instrument(name):
    """Factory function to create instrument configurations"""
    instruments = {
        'piano': Piano,
        'organ': Organ,
        'womp': Womp,
        'wind_chime': WindChime
    }
    
    if name.lower() in instruments:
        return instruments[name.lower()]()
    return None

def list_instruments():
    """Get list of available instruments"""
    return ['Piano', 'Organ', 'Womp', 'Wind Chime']
