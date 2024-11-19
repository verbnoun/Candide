"""
Instrument Configuration System

This module defines complete synthesis configuration including:
- Signal flow and routing
- Parameter and CC mappings grouped by feature
- Modulation sources and targets
- Default values
"""

from synth_constants import ModSource, ModTarget

class InstrumentConfig:
    """Minimal base class for instrument configurations"""
    def __init__(self, name):
        self.name = name
        self.config = {
            'name': name
        }
        
    def _find_controls(self, config):
        """Recursively find all control objects with CC numbers"""
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
        """Return complete configuration with CC routing"""
        # Find all controls with CC numbers
        controls = self._find_controls(self.config)
        
        # Generate CC routing for MIDI controller
        cc_routing = {}
        used_cc_numbers = set()
        
        for control in controls:
            cc_num = control['cc']
            
            # Skip if CC number already used or out of range
            if cc_num in used_cc_numbers or not (0 <= cc_num <= 127):
                continue
            
            # Add to routing
            cc_routing[cc_num] = {
                'name': control['name'],
                'target': control.get('target', ModTarget.NONE),
                'path': control.get('path', '')
            }
            used_cc_numbers.add(cc_num)
            
            # Stop if we've reached 14 CC routes (controller limit)
            if len(cc_routing) >= 14:
                break
        
        # Create complete config with CC routing
        config = self.config.copy()
        config['cc_routing'] = cc_routing
        
        return config

    def format_cc_config(self):
        """Format CC config string for controller handshake"""
        cc_routing = self.get_config()['cc_routing']
        if not cc_routing:
            return "cc:"  # Minimal valid config
            
        # Create assignments with names
        assignments = []
        pot_number = 0
        
        for cc_number, routing in cc_routing.items():
            # Validate CC number
            cc_num = int(cc_number)
            if not (0 <= cc_num <= 127):
                continue
                
            # Only use first 14 pots
            if pot_number > 13:
                break
                
            # Get CC name
            cc_name = routing.get('name', f"CC{cc_num}")
            assignments.append(f"{pot_number}={cc_num}:{cc_name}")
            pot_number += 1
            
        # Join with commas
        return "cc:" + ",".join(assignments)

class EvErYtHiNg(InstrumentConfig):
    """Comprehensive instrument configuration with all details"""
    def __init__(self):
        super().__init__("EvErYtHiNg")
        
        self.config = {
            'name': "EvErYtHiNg",
            
            # Parameters section for synthesizer
            'parameters': {
                'frequency': {
                    'synthio_param': 'frequency',
                    'default': 440.0,
                    'range': {'min': 20.0, 'max': 20000.0},
                    'curve': 'linear'
                },
                'amplitude': {
                    'synthio_param': 'amplitude',
                    'default': 0.5,
                    'range': {'min': 0.0, 'max': 1.0},
                    'curve': 'linear'
                },
                'waveform': {
                    'synthio_param': 'waveform',
                    'default': 'triangle',
                    'options': ['sine', 'triangle', 'sawtooth', 'square']
                }
            },
            
            # Message routing for MPE with more detailed configuration
            'message_routes': {
                'note_on': {
                    'source_id': 'note',
                    'value_func': lambda data: data.get('note', 0),
                    'target': 'frequency',
                    'description': 'Convert MIDI note number to frequency',
                    'transform': {
                        'type': 'midi_to_freq',
                        'reference_pitch': 440.0,
                        'reference_note': 69
                    }
                },
                'note_off': {
                    'source_id': 'gate',
                    'value_func': lambda data: 0,
                    'target': 'amplitude',
                    'description': 'Set amplitude to zero on note off'
                },
                'pressure': {
                    'source_id': 'pressure',
                    'value_func': lambda data: data.get('value', 0),
                    'target': 'amplitude',
                    'description': 'Modulate amplitude with channel pressure',
                    'transform': {
                        'type': 'normalize',
                        'input_range': {'min': 0, 'max': 127},
                        'output_range': {'min': 0.0, 'max': 1.0}
                    }
                },
                'pitch_bend': {
                    'source_id': 'pitch_bend',
                    'value_func': lambda data: data.get('value', 8192),
                    'target': 'frequency',
                    'description': 'Modulate frequency with pitch bend',
                    'transform': {
                        'type': 'pitch_bend',
                        'center': 8192,
                        'range': {'semitones': 48}
                    }
                }
            },
            
            # Oscillator configuration
            'oscillator': {
                'waveform': {
                    'type': 'sine',  # Default waveform
                    'config': {
                        'size': 512,
                        'amplitude': 32767
                    }
                },
                'tuning': {
                    'transpose': 0,
                    'fine': 0.0
                }
            },
            
            # Envelope section
            'envelope': {
                'stages': {
                    'attack': {
                        'time': {
                            'value': 0.01,
                            'control': {
                                'cc': 72,
                                'name': 'Attack Time',
                                'range': {'min': 0.001, 'max': 2.0},
                                'curve': 'exponential'
                            }
                        },
                        'level': {
                            'value': 1.0,
                            'source': ModSource.VELOCITY,  # Velocity modulates attack level
                            'control': {
                                'cc': 73,
                                'name': 'Attack Level',
                                'range': {'min': 0.0, 'max': 1.0},
                                'curve': 'linear'
                            }
                        }
                    },
                    'decay': {
                        'time': {
                            'value': 0.1,
                            'control': {
                                'cc': 74,
                                'name': 'Decay Time',
                                'range': {'min': 0.01, 'max': 3.0},
                                'curve': 'exponential'
                            }
                        }
                    },
                    'sustain': {
                        'level': {
                            'value': 0.7,
                            'control': {
                                'cc': 75,
                                'name': 'Sustain Level',
                                'range': {'min': 0.0, 'max': 1.0},
                                'curve': 'linear'
                            }
                        }
                    },
                    'release': {
                        'time': {
                            'value': 0.2,
                            'control': {
                                'cc': 76,
                                'name': 'Release Time',
                                'range': {'min': 0.01, 'max': 4.0},
                                'curve': 'exponential'
                            }
                        }
                    }
                }
            },
            
            # Filter section
            'filter': {
                'type': 'lowpass',
                'frequency': {
                    'value': 2000,
                    'control': {
                        'cc': 77,
                        'name': 'Filter Cutoff',
                        'range': {'min': 20, 'max': 20000},
                        'curve': 'exponential'
                    }
                },
                'resonance': {
                    'value': 0.7,
                    'control': {
                        'cc': 71,
                        'name': 'Filter Resonance',
                        'range': {'min': 0.1, 'max': 1.9},
                        'curve': 'exponential'
                    }
                }
            },
            
            # LFO definitions
            'lfos': {
                'lfo1': {
                    'type': 'lfo',
                    'waveform': {
                        'type': 'triangle',
                        'size': 32
                    },
                    'rate': {
                        'value': 1.0,
                        'control': {
                            'cc': 102,
                            'name': 'LFO 1 Rate',
                            'range': {'min': 0.1, 'max': 20.0},
                            'curve': 'exponential'
                        }
                    },
                    'amount': {
                        'value': 0.5,
                        'control': {
                            'cc': 103,
                            'name': 'LFO 1 Amount',
                            'range': {'min': 0.0, 'max': 1.0},
                            'curve': 'linear'
                        }
                    }
                }
            },
            
            # Signal flow and routing
            'routes': [
                # Envelope -> Amplitude
                {
                    'source': 'envelope',
                    'target': ModTarget.AMPLITUDE,
                    'amount': 1.0
                },
                
                # LFO -> Filter cutoff 
                {
                    'source': 'lfo1',
                    'target': ModTarget.FILTER_CUTOFF,
                    'amount': 0.5,
                    'bipolar': True
                },
                
                # Velocity -> Initial envelope level
                {
                    'source': ModSource.VELOCITY,
                    'target': 'envelope.attack.level',
                    'amount': 1.0,
                    'curve': 'exponential'
                }
            ],
            
            # MPE settings
            'mpe': {
                'enabled': True,
                'pitch_bend_range': 48,
                'pressure': {
                    'enabled': True,
                    'target': ModTarget.FILTER_CUTOFF,
                    'amount': 0.3
                },
                'timbre': {
                    'enabled': True,
                    'cc': 74,
                    'target': ModTarget.FILTER_RESONANCE,
                    'amount': 0.5
                }
            }
        }

class Piano(InstrumentConfig):
    """Minimal piano instrument with absolute minimum configuration"""
    def __init__(self):
        super().__init__("Piano")
        
        self.config = {
            'name': "Piano",
            
            # Minimal parameters
            'parameters': {
                'frequency': {
                    'synthio_param': 'frequency',
                    'default': 440.0,
                    'range': {'min': 20.0, 'max': 20000.0},
                    'curve': 'linear'
                },
                'amplitude': {
                    'synthio_param': 'amplitude',
                    'default': 0.5,
                    'range': {'min': 0.0, 'max': 1.0},
                    'curve': 'linear'
                },
                'waveform': {
                    'synthio_param': 'waveform',
                    'default': 'triangle',
                    'options': ['sine', 'triangle', 'sawtooth', 'square']
                },
                'attack_time': {
                    'synthio_param': 'attack_time',
                    'default': 0.01,
                    'range': {'min': 0.001, 'max': 2.0},
                    'curve': 'exponential'
                },
                'decay_time': {
                    'synthio_param': 'decay_time',
                    'default': 0.1,
                    'range': {'min': 0.01, 'max': 3.0},
                    'curve': 'exponential'
                },
                'sustain_level': {
                    'synthio_param': 'sustain_level',
                    'default': 0.5,
                    'range': {'min': 0.0, 'max': 1.0},
                    'curve': 'linear'
                },
                'release_time': {
                    'synthio_param': 'release_time',
                    'default': 0.2,
                    'range': {'min': 0.01, 'max': 4.0},
                    'curve': 'exponential'
                }
            },
            
            # Minimal envelope with CC controls
            'envelope': {
                'stages': {
                    'attack': {
                        'time': {
                            'value': 0.01,
                            'control': {
                                'cc': 72,
                                'name': 'Attack Time',
                                'range': {'min': 0.001, 'max': 2.0},
                                'target': 'attack_time'
                            }
                        }
                    },
                    'decay': {
                        'time': {
                            'value': 0.1,
                            'control': {
                                'cc': 74,
                                'name': 'Decay Time',
                                'range': {'min': 0.01, 'max': 3.0},
                                'target': 'decay_time'
                            }
                        }
                    },
                    'sustain': {
                        'level': {
                            'value': 0.5,
                            'control': {
                                'cc': 75,
                                'name': 'Sustain Level',
                                'range': {'min': 0.0, 'max': 1.0},
                                'target': 'sustain_level'
                            }
                        }
                    },
                    'release': {
                        'time': {
                            'value': 0.2,
                            'control': {
                                'cc': 76,
                                'name': 'Release Time',
                                'range': {'min': 0.01, 'max': 4.0},
                                'target': 'release_time'
                            }
                        }
                    }
                }
            },
            
            # Minimal routing
            'routes': [
                {
                    'source': 'velocity',
                    'target': 'amplitude',
                    'amount': 1.0
                },
                {
                    'source': 'gate',
                    'target': 'amplitude',
                    'amount': 1.0
                },
                {
                    'source': 'cc',
                    'target': 'attack_time',
                    'amount': 1.0,
                    'curve': 'exponential'
                },
                {
                    'source': 'cc',
                    'target': 'decay_time',
                    'amount': 1.0,
                    'curve': 'exponential'
                },
                {
                    'source': 'cc',
                    'target': 'sustain_level',
                    'amount': 1.0,
                    'curve': 'linear'
                },
                {
                    'source': 'cc',
                    'target': 'release_time',
                    'amount': 1.0,
                    'curve': 'exponential'
                }
            ],
            
            # Minimal message routing
            'message_routes': {
                'note_on': {
                    'source_id': 'note',
                    'value_func': lambda data: data.get('note', 0),
                    'target': 'frequency',
                    'transform': {
                        'type': 'midi_to_freq',
                        'reference_pitch': 440.0,
                        'reference_note': 69
                    }
                },
                'note_off': {
                    'source_id': 'gate',
                    'value_func': lambda data: 0,
                    'target': 'amplitude'
                },
                'cc': {
                    'source_id': 'cc',
                    'value_func': lambda data: data.get('value', 0),
                    'target': 'parameter',
                    'transform': {
                        'type': 'normalize',
                        'input_range': {'min': 0, 'max': 127},
                        'output_range': {'min': 0.0, 'max': 1.0}
                    }
                }
            }
        }

def create_instrument(name):
    """Factory function to create instrument configurations"""
    instruments = {
        'piano': Piano,
        'everything': EvErYtHiNg
    }
    
    if name.lower() in instruments:
        return instruments[name.lower()]()
    return None

def list_instruments():
    """Get list of available instruments"""
    return ['Piano', 'Everything']
