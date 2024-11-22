"""
Instrument Configuration System

Source of Routing and configuration structures for defining synthesizer instruments
with robust parameter routing and modulation capabilities.
"""

class InstrumentConfig:
    """Base configuration for instruments"""
    def __init__(self, name):
        self.name = name
        self.config = {}

    def _find_controls(self, config):
        """Extract all control objects with CC numbers"""
        controls = []
        def extract_controls(obj):
            if isinstance(obj, dict):
                if 'type' in obj and obj.get('type') == 'cc':
                    controls.append({
                        'cc': obj.get('number'),
                        'name': obj.get('name', f"CC{obj.get('number')}")
                    })
                for value in obj.values():
                    extract_controls(value)
            elif isinstance(obj, list):
                for item in obj:
                    extract_controls(item)
        extract_controls(config)
        return controls

    def _generate_midi_whitelist(self):
        """Generate a whitelist of allowed MIDI message types"""
        whitelist = {
            'cc': set(),
            'note_on': set(),
            'note_off': set()
        }

        def scan_for_midi_endpoints(obj):
            if isinstance(obj, dict):
                if 'type' in obj:
                    if obj['type'] == 'cc':
                        cc_num = obj.get('number')
                        if cc_num is not None:
                            whitelist['cc'].add(cc_num)
                    elif obj['type'] == 'per_key':
                        event = obj.get('event')
                        if event == 'note_on':
                            whitelist['note_on'].add('note')
                            whitelist['note_on'].add('velocity')
                        elif event == 'note_off':
                            whitelist['note_off'].add('note')
                for value in obj.values():
                    scan_for_midi_endpoints(value)
            elif isinstance(obj, list):
                for item in obj:
                    scan_for_midi_endpoints(item)

        scan_for_midi_endpoints(self.config)
        return whitelist

    def get_config(self):
        """Generate complete configuration"""
        try:
            config = self.config.copy()
            config['midi_whitelist'] = self._generate_midi_whitelist()
            return config
        except Exception as e:
            print(f"[CONFIG] Error generating config: {str(e)}")
            return None


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
                'envelope': {
                    'attack': {
                        'triggers': {
                            'start': {
                                'sources': [
                                    {
                                        'type': 'per_key',
                                        'event': 'note_on'
                                    }
                                ]
                            }
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
                            'start': {
                                'sources': [
                                    {
                                        'type': 'per_key',
                                        'event': 'note_off'
                                    }
                                ]
                            }
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
