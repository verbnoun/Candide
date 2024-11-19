"""
Instrument Configuration System

Source of Routing and configuration structures for defining synthesizer instruments
with robust parameter routing and modulation capabilities.

Key Configuration Areas:
- Basic instrument definition
- Sound generation (oscillator, envelope, filter)
- Modulation routing
- Control mapping
"""

from synth_constants import ModSource, ModTarget

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
        return config

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
    """Minimal piano instrument with basic sound generation"""
    def __init__(self):
        super().__init__("Piano")
        
        self.config = {
            # Basic Definition
            'name': "Piano",
            
            # Sound Generation 
            'waveforms': {
                'triangle': {
                    'type': 'triangle',
                    'size': 512,
                    'amplitude': 32767 #16bit max
                }
            },
            
            # Required Parameters
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
                    'options': ['triangle']
                }
            },
            
            # Envelope Configuration
            'envelope': {
                'stages': {
                    'attack': {
                        'time': {
                            'value': 0.01,
                            'control': {
                                'cc': 72,
                                'name': 'Attack Time',
                                'range': {'min': 0.001, 'max': 2.0}
                            }
                        }
                    },
                    'decay': {
                        'time': {
                            'value': 0.1,
                            'control': {
                                'cc': 74,
                                'name': 'Decay Time',
                                'range': {'min': 0.01, 'max': 3.0}
                            }
                        }
                    },
                    'sustain': {
                        'level': {
                            'value': 0.5,
                            'control': {
                                'cc': 75,
                                'name': 'Sustain Level',
                                'range': {'min': 0.0, 'max': 1.0}
                            }
                        }
                    },
                    'release': {
                        'time': {
                            'value': 0.2,
                            'control': {
                                'cc': 76,
                                'name': 'Release Time',
                                'range': {'min': 0.01, 'max': 4.0}
                            }
                        }
                    }
                }
            },
            
            # Message Routing
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
            },

            # Parameter Routing
            'routes': [
                {
                    'source': 'velocity',
                    'target': 'amplitude',
                    'amount': 1.0,
                    'curve': 'linear'
                },
                {
                    'source': 'gate',
                    'target': 'amplitude',
                    'amount': 1.0,
                    'curve': 'linear'
                }
            ]
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

"""
SYNTHESIZER CONFIGURATION TEMPLATE
================================

Complete template showing all possible configuration options.
Copy relevant sections when creating new instruments.

Required sections marked with [REQUIRED]

Basic Instrument Definition [REQUIRED]
------------------------------------
{
    'name': str,        # Instrument name
    'version': str,     # Version for tracking
    
    # Sound Generation
    # ---------------
    
    # [REQUIRED] Waveform Definition
    'waveforms': {
        'waveform_name': {
            'type': str,     # sine|triangle|saw|square|custom
            'size': int,     # Buffer size (typically 512)
            'amplitude': int  # Max 32767
        }
    },
    
    # [REQUIRED] Core Parameters
    'parameters': {
        'frequency': {
            'synthio_param': 'frequency',
            'default': float,
            'range': {'min': float, 'max': float},
            'curve': str  # linear|exponential
        },
        'amplitude': {
            'synthio_param': 'amplitude',
            'default': float,
            'range': {'min': float, 'max': float},
            'curve': str
        }
    },
    
    # Envelope Configuration
    'envelope': {
        'stages': {
            'attack': {
                'time': {
                    'value': float,
                    'control': {
                        'cc': int,
                        'name': str,
                        'range': {'min': float, 'max': float}
                    }
                },
                'level': {  # Optional
                    'value': float,
                    'control': {
                        'cc': int,
                        'name': str,
                        'range': {'min': float, 'max': float}
                    }
                }
            },
            'decay': {
                'time': {
                    # Same structure as attack
                }
            },
            'sustain': {
                'level': {
                    # Level control only
                }
            },
            'release': {
                'time': {
                    # Time control only
                }
            }
        }
    },
    
    # Filter Configuration
    'filter': {
        'type': str,    # lowpass|highpass|bandpass
        'frequency': {
            'value': float,
            'control': {
                'cc': int,
                'name': str,
                'range': {'min': float, 'max': float}
            }
        },
        'resonance': {
            # Same structure as frequency
        }
    },
    
    # Modulation Sources
    'lfos': {
        'lfo_name': {
            'type': 'lfo',
            'waveform': {
                'type': str,
                'size': int
            },
            'rate': {
                'value': float,
                'control': {
                    'cc': int,
                    'name': str,
                    'range': {'min': float, 'max': float}
                }
            },
            'amount': {
                # Same structure as rate
            }
        }
    },
    
    # [REQUIRED] Message Routing
    'message_routes': {
        'note_on': {
            'source_id': str,
            'value_func': callable,
            'target': str,
            'transform': {
                'type': str,
                'reference_pitch': float,
                'reference_note': int
            }
        },
        'note_off': {
            'source_id': str,
            'value_func': callable,
            'target': str
        },
        'cc': {
            'source_id': str,
            'value_func': callable,
            'target': str,
            'transform': {
                'type': str,
                'input_range': dict,
                'output_range': dict
            }
        }
    },
    
    # [REQUIRED] Parameter Routing
    'routes': [
        {
            'source': str,      # Source parameter
            'target': str,      # Target parameter
            'amount': float,    # Modulation amount
            'curve': str        # Transform curve
        }
    ],
    
    # MPE Configuration
    'mpe': {
        'enabled': bool,
        'pitch_bend_range': int,
        'pressure': {
            'enabled': bool,
            'target': str,
            'amount': float
        },
        'timbre': {
            'enabled': bool,
            'cc': int,
            'target': str,
            'amount': float
        }
    }
}
"""
