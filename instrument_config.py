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

    def _find_controls(self, config, prefix=''):
        """Extract all control objects with CC numbers"""
        controls = []

        def extract_controls(obj, parent_path=''):
            if isinstance(obj, dict):
                if 'type' in obj and obj.get('type') == 'cc':
                    controls.append({
                        'cc': obj.get('number'),
                        'name': obj.get('name', f"CC{obj.get('number')}"),
                        'target': obj.get('target', ModTarget.NONE),
                        'path': parent_path
                    })
                else:
                    for key, value in obj.items():
                        new_path = f"{parent_path}.{key}" if parent_path else key
                        extract_controls(value, new_path)
            elif isinstance(obj, list):
                for item in obj:
                    extract_controls(item, parent_path)

        extract_controls(config, prefix)
        return controls

    def get_config(self):
        """Generate complete configuration with CC routing"""
        try:
            # Find all controls with CC numbers
            controls = self._find_controls(self.config)

            # Generate CC routing
            cc_routing = {}
            used_cc_numbers = set()

            for control in controls:
                cc_num = control.get('cc')
                if cc_num is None or cc_num in used_cc_numbers or not (0 <= cc_num <= 127):
                    continue

                cc_routing[str(cc_num)] = control
                used_cc_numbers.add(cc_num)

                if len(cc_routing) >= 14:
                    break

            # Create complete config
            config = self.config.copy()
            config['cc_routing'] = cc_routing

            # Generate MIDI whitelist if not already created
            if not hasattr(self, 'midi_whitelist'):
                self.midi_whitelist = self._generate_midi_whitelist()
            config['midi_whitelist'] = self.midi_whitelist

            return config
        except Exception as e:
            print(f"[CONFIG] Error generating config: {str(e)}")
            return None

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
                        if isinstance(source, dict):
                            if source.get('type') == 'cc':
                                cc_num = source.get('number')
                                if cc_num is not None:
                                    whitelist['cc'].add(cc_num)
                            elif source.get('type') == 'per_key':
                                pass
                for value in obj.values():
                    extract_midi_sources(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_midi_sources(item)

        extract_midi_sources(self.config)
        return whitelist


class Piano(InstrumentConfig):
    """Piano instrument with oscillator -> filter -> amplifier signal path"""
    def __init__(self):
        super().__init__("Piano")
        
        self.config = {
            'name': "Piano",
            
            'oscillator': {
                'triggers': {
                    'start': {
                        'sources': [
                            {
                                'type': 'per_key',
                                'event': 'note_on'
                            }
                        ]
                    },
                    'stop': {
                        'sources': [
                            {
                                'type': 'null',
                                'event': 'note_off'
                            }
                        ]
                    }
                },
                'frequency': {
                    'value': 440.0,
                    'output_range': {'min': 20.0, 'max': 20000.0},
                    'curve': 'linear',
                    'sources': {
                        'controls': [
                            {
                                'type': 'per_key',
                                'event': 'note',
                                'transform': 'midi_to_frequency',
                                'reference_pitch': 440.0,
                                'reference_pitch_note': 69,
                                'amount': 1.0
                            }
                        ]
                    }
                },
                'waveform': {
                    'type': 'triangle',
                    'size': 512,
                    'amplitude': 32767
                }
            },

            'filter': {
                'triggers': {
                    'start': {
                        'sources': [
                            {
                                'type': 'per_key',
                                'event': 'note_on'
                            }
                        ]
                    },
                    'stop': {
                        'sources': [
                            {
                                'type': 'null',
                                'event': 'note_off'
                            }
                        ]
                    }
                },
                'type': {
                    'value': 'lowpass',
                    'options': ['lowpass', 'highpass', 'bandpass']
                },
                'frequency': {
                    'value': 1000,
                    'output_range': {'min': 20.0, 'max': 20000.0},
                    'curve': 'exponential',
                    'sources': {
                        'controls': [
                            {
                                'type': 'cc',
                                'number': 74,
                                'name': 'Cutoff',
                                'amount': 1.0,
                                'midi_range': {'min': 0, 'max': 127}
                            }
                        ]
                    }
                },
                'resonance': {
                    'value': 0.707,
                    'output_range': {'min': 0.1, 'max': 2.0},
                    'curve': 'linear',
                    'sources': {
                        'controls': [
                            {
                                'type': 'cc',
                                'number': 71,
                                'name': 'Resonance',
                                'amount': 1.0,
                                'midi_range': {'min': 0, 'max': 127}
                            }
                        ]
                    }
                }
            },

            'amplifier': {
                'triggers': {
                    'start': {
                        'sources': [
                            {
                                'type': 'per_key',
                                'event': 'note_on'
                            }
                        ]
                    },
                    'stop': {
                        'sources': [
                            {
                                'type': 'null',
                                'event': 'note_off'
                            }
                        ]
                    }
                },
                'gain': {
                    'value': 0.5,
                    'output_range': {'min': 0.0, 'max': 1.0},
                    'curve': 'linear',
                    'sources': {
                        'controls': [
                            {
                                'type': 'per_key',
                                'event': 'velocity',
                                'amount': 1.0,
                                'midi_range': {'min': 0, 'max': 127}
                            }
                        ]
                    }
                },
                'envelope': {
                    'attack': {
                        'triggers': {
                            'sources': [
                                {
                                    'type': 'per_key',
                                    'event': 'note_on'
                                }
                            ]
                        },
                        'time': {
                            'value': 0.1,
                            'output_range': {'min': 0.001, 'max': 2.0},
                            'sources': {
                                'controls': [
                                    {
                                        'type': 'cc',
                                        'number': 73,
                                        'name': 'Attack Time',
                                        'amount': 1.0,
                                        'midi_range': {'min': 0, 'max': 127}
                                    }
                                ]
                            }
                        },
                        'value': {
                            'value': 1.0,
                            'output_range': {'min': 0.0, 'max': 1.0},
                            'sources': {
                                'controls': [
                                    {
                                        'type': 'cc',
                                        'number': 75,
                                        'name': 'Attack Level',
                                        'amount': 1.0,
                                        'midi_range': {'min': 0, 'max': 127}
                                    }
                                ]
                            }
                        }
                    },
                    'decay': {
                        'time': {
                            'value': 0.05,
                            'output_range': {'min': 0.001, 'max': 1.0},
                            'sources': {
                                'controls': [
                                    {
                                        'type': 'cc',
                                        'number': 75,
                                        'name': 'Decay Time',
                                        'amount': 1.0,
                                        'midi_range': {'min': 0, 'max': 127}
                                    }
                                ]
                            }
                        }
                    },
                    'sustain': {
                        'value': {
                            'value': 0.8,
                            'output_range': {'min': 0.0, 'max': 1.0},
                            'sources': {
                                'controls': [
                                    {
                                        'type': 'cc',
                                        'number': 70,
                                        'name': 'Sustain',
                                        'amount': 1.0,
                                        'midi_range': {'min': 0, 'max': 127}
                                    }
                                ]
                            }
                        }
                    },
                    'release': {
                        'triggers': {
                            'sources': [
                                {
                                    'type': 'per_key',
                                    'event': 'note_off'
                                }
                            ]
                        },
                        'time': {
                            'value': 0.2,
                            'output_range': {'min': 0.001, 'max': 2.0},
                            'sources': {
                                'controls': [
                                    {
                                        'type': 'cc',
                                        'number': 72,
                                        'name': 'Release Time',
                                        'amount': 1.0,
                                        'midi_range': {'min': 0, 'max': 127}
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
