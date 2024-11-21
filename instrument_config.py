"""
Instrument Configuration System

Source of Routing and configuration structures for defining synthesizer instruments
with robust parameter routing and modulation capabilities.
"""
from constants import ModSource, ModTarget
from fixed_point_math import FixedPoint


class InstrumentConfig:
    """Base configuration for instruments"""
    def __init__(self, name):
        self.name = name
        self.config = {
            'name': name
        }

    def _find_controls(self, config):
        """Extract all control objects with CC numbers"""
        controls = []
        
        def extract_controls(obj):
            if isinstance(obj, dict):
                if all(key in obj for key in ['cc', 'name']):
                    controls.append(obj)
                else:
                    for value in obj.values():
                        extract_controls(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_controls(item)
                    
        extract_controls(config)
        return controls

    def get_config(self):
        """Generate complete configuration with CC routing"""
        # Find all controls with CC numbers
        controls = self._find_controls(self.config)
        
        # Generate CC routing
        cc_routing = {}
        used_cc_numbers = set()
        
        for control in controls:
            cc_num = control['cc']
            if cc_num in used_cc_numbers or not (0 <= cc_num <= 127):
                continue
                
            cc_routing[cc_num] = {
                'name': control['name'],
                'target': control.get('target', ModTarget.NONE),
                'path': control.get('path', '')
            }
            used_cc_numbers.add(cc_num)
            
            if len(cc_routing) >= 14:
                break
                
        config = self.config.copy()
        config['cc_routing'] = cc_routing
        
        # Generate MIDI whitelist if not already created
        if not hasattr(self, 'midi_whitelist'):
            self.midi_whitelist = self._generate_midi_whitelist()
        config['midi_whitelist'] = self.midi_whitelist
        
        return config

    def _generate_midi_whitelist(self):
        """Generate a whitelist of MIDI message types and numbers allowed by this instrument"""
        whitelist = {
            'cc': set(),
            'note_on': {'velocity', 'note'},
            'note_off': {'trigger'}
        }
        
        def extract_midi_sources(obj):
            if isinstance(obj, dict):
                if 'sources' in obj:
                    for source in obj['sources']:
                        if source.get('type') == 'cc':
                            whitelist['cc'].add(source.get('number'))
                        elif source.get('type') == 'per_key':
                            # Already added note_on/note_off attributes above
                            pass
                for value in obj.values():
                    extract_midi_sources(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_midi_sources(item)
        
        extract_midi_sources(self.config)
        return whitelist

    def format_cc_config(self):
        """Format CC config string"""
        cc_routing = self.get_config()['cc_routing']
        if not cc_routing:
            return "cc:"
            
        assignments = []
        pot_number = 0
        
        for cc_number, routing in cc_routing.items():
            cc_num = int(cc_number)
            if not (0 <= cc_num <= 127):
                continue
                
            if pot_number > 13:
                break
                
            cc_name = routing.get('name', f"CC{cc_num}")
            assignments.append(f"{pot_number}={cc_num}:{cc_name}")
            pot_number += 1
            
        return "cc:" + ",".join(assignments)


class Piano(InstrumentConfig):
    """Piano instrument with oscillator -> filter -> amplifier signal path"""
    def __init__(self):
        super().__init__("Piano")
        
        self.config = {
            'name': "Piano",
            
            'oscillator': {
                'parameters': {
                    'frequency': {
                        'value': 440.0,
                        'range': {'min': 20.0, 'max': 20000.0},
                        'curve': 'linear',
                        'sources': [
                            {
                                'type': 'per_key',
                                'attribute': 'note',
                                'transform': 'midi_to_frequency',
                                'reference_pitch': 440.0,
                                'reference_pitch_note': 69,
                                'amount': 1.0
                            }
                        ]
                    },
                    'waveform': {
                        'type': 'triangle',
                        'size': 512,
                        'amplitude': 32767
                    }
                }
            },

            'filter': {
                'parameters': {
                    'type': {
                        'value': 'lowpass',
                        'options': ['lowpass', 'highpass', 'bandpass']
                    },
                    'frequency': {
                        'value': 1000,
                        'range': {'min': 20.0, 'max': 20000.0},
                        'curve': 'exponential',
                        'sources': [
                            {
                                'type': 'cc',
                                'number': 74,  # MIDI CC standard for filter cutoff
                                'name': 'Cutoff',
                                'amount': 1.0,
                                'range': {'in_min': 0, 'in_max': 127}
                            }
                        ]
                    },
                    'resonance': {
                        'value': 0.707,  # Default Q factor
                        'range': {'min': 0.1, 'max': 2.0},
                        'curve': 'linear',
                        'sources': [
                            {
                                'type': 'cc',
                                'number': 71,  # MIDI CC standard for resonance
                                'name': 'Resonance',
                                'amount': 1.0,
                                'range': {'in_min': 0, 'in_max': 127}
                            }
                        ]
                    }
                }
            },

            'amplifier': {
                'parameters': {
                    'gain': {
                        'value': 0.5,
                        'range': {'min': 0.0, 'max': 1.0},
                        'curve': 'linear',
                        'sources': [
                            {
                                'type': 'per_key',
                                'attribute': 'velocity',
                                'amount': 1.0,
                                'range': {
                                    'in_min': 0,
                                    'in_max': 127,
                                    'out_min': 0.0,
                                    'out_max': 1.0
                                }
                            },
                            {
                                'type': 'per_key',
                                'attribute': 'note_off',
                                'amount': 0.0
                            }
                        ]
                    },
                    'envelope': {
                        'attack': {
                            'time': {
                                'value': 0.1,
                                'range': {'min': 0.001, 'max': 2.0},
                                'sources': [
                                    {
                                        'type': 'cc',
                                        'number': 73,
                                        'name': 'Attack Time',
                                        'amount': 1.0,
                                        'range': {'in_min': 0, 'in_max': 127}
                                    }
                                ]
                            },
                            'level': {
                                'value': 1.0,
                                'range': {'min': 0.0, 'max': 1.0},
                                'sources': [
                                    {
                                        'type': 'cc',
                                        'number': 75,
                                        'name': 'Attack Level',
                                        'amount': 1.0,
                                        'range': {'in_min': 0, 'in_max': 127}
                                    }
                                ]
                            }
                        },
                        'decay': {
                            'time': {
                                'value': 0.05,
                                'range': {'min': 0.001, 'max': 1.0},
                                'sources': [
                                    {
                                        'type': 'cc',
                                        'number': 75,
                                        'name': 'Decay Time',
                                        'amount': 1.0,
                                        'range': {'in_min': 0, 'in_max': 127}
                                    }
                                ]
                            }
                        },
                        'sustain': {
                            'level': {
                                'value': 0.8,
                                'range': {'min': 0.0, 'max': 1.0},
                                'sources': [
                                    {
                                        'type': 'cc',
                                        'number': 70,
                                        'name': 'Sustain',
                                        'amount': 1.0,
                                        'range': {'in_min': 0, 'in_max': 127}
                                    }
                                ]
                            }
                        },
                        'release': {
                            'time': {
                                'value': 0.2,
                                'range': {'min': 0.001, 'max': 2.0},
                                'sources': [
                                    {
                                        'type': 'cc',
                                        'number': 72,
                                        'name': 'Release Time',
                                        'amount': 1.0,
                                        'range': {'in_min': 0, 'in_max': 127}
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }


def create_instrument(name):
    """Factory function for instrument creation"""
    instruments = {
        'piano': Piano
    }
    
    if name.lower() in instruments:
        return instruments[name.lower()]()
    return None

def list_instruments():
    """List available instruments"""
    return ['Piano']
