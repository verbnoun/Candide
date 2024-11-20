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
            'name': "Piano",
            
            # Core Modules
            'oscillator': {
                'frequency': {
                    'value': 440.0,
                    'range': {'min': 20.0, 'max': 20000.0},
                    'curve': 'linear'
                },
                'waveform': {
                    'type': 'triangle',
                    'size': 512,
                    'amplitude': 32767  # 16bit max
                }
            },

            'amplifier': {
                'gain': {
                    'value': 0.5,
                    'range': {'min': 0.0, 'max': 1.0},
                    'curve': 'linear'
                }
            },
            
            # Signal Sources
            'sources': {
                'note_on': {
                    'type': 'per_key',
                    'attributes': {
                        'trigger': {
                            'type': 'bool'
                        },
                        'velocity': {
                            'range': {'min': 0, 'max': 127},
                            'curve': 'linear'
                        },
                        'note': {
                            'transform': 'midi_to_frequency',
                            'reference_pitch': 440.0,
                            'reference_pitch_note': 69
                        }
                    }
                },
                'note_off': {
                    'type': 'per_key',
                    'attributes': {
                        'trigger': {
                            'type': 'bool'
                        },
                        'note': {
                            'transform': 'midi_to_frequency',
                            'reference_pitch': 440.0,
                            'reference_pitch_note': 69
                        }
                    }
                }
            },
            
            # Patches
            'patches': [
                {
                    'source': {'id': 'note_on', 'attribute': 'note'},
                    'destination': {'id': 'oscillator', 'attribute': 'frequency'},
                    'processing': {
                        'amount': 1.0,
                        'curve': 'linear'
                    }
                },
                {
                    'source': {'id': 'note_on', 'attribute': 'velocity'},
                    'destination': {'id': 'amplifier', 'attribute': 'gain'},
                    'processing': {
                        'amount': 1.0,
                        'curve': 'linear',
                        'range': {
                            'in_min': 0,
                            'in_max': 127,
                            'out_min': 0.0,
                            'out_max': 1.0
                        }
                    }
                },
                {
                    'source': {'id': 'note_off', 'attribute': 'trigger'},
                    'destination': {'id': 'amplifier', 'attribute': 'gain'},
                    'processing': {
                        'amount': 0.0,  # Sets gain to zero on note off
                        'curve': 'linear'
                    }
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

Basic Instrument Definition [REQUIRED]
------------------------------------
{
   'name': str,        # Instrument name
   'version': str,     # Version for tracking
   
   # [REQUIRED] Core Modules
   'oscillator': {
       'frequency': {
           'value': float,
           'range': {'min': float, 'max': float},
           'curve': str  # linear|exponential
       },
       'waveform': {
           'type': str,       # sine|triangle|saw|square|wavetable
           'size': int,       # Buffer size (typically 512)
           'amplitude': int    # Max amplitude (e.g., 32767 for 16-bit)
       },
       'envelope': {  # Pitch envelope
           'attack': {
               'time': {
                   'value': float,
                   'control': {
                       'cc': int,
                       'name': str,
                       'range': {'min': float, 'max': float}
                   }
               },
               'level': {
                   'value': float,
                   'control': {
                       'cc': int,
                       'name': str,
                       'range': {'min': float, 'max': float}
                   }
               }
           },
           'decay': {...},
           'sustain': {...},
           'release': {...}
       }
   },

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
           'value': float,
           'control': {
               'cc': int,
               'name': str,
               'range': {'min': float, 'max': float}
           }
       },
       'envelope': {  # Filter envelope (FEG)
           'attack': {...},    # Same structure as oscillator envelope
           'decay': {...},
           'sustain': {...},
           'release': {...}
       }
   },

   'amplifier': {
       'gain': {
           'value': float,
           'control': {
               'cc': int,
               'name': str,
               'range': {'min': float, 'max': float}
           }
       },
       'envelope': {  # Amplitude envelope (AEG)
           'attack': {...},    # Same structure as oscillator envelope
           'decay': {...},
           'sustain': {...},
           'release': {...}
       }
   },
   
   # Signal Sources
   'sources': {
       'note_on': {
           'type': 'per_key',
           'attributes': {
               'trigger': {
                   'type': 'bool'  # Simple trigger event
               },
               'velocity': {
                   'range': {'min': 0, 'max': 127},
                   'curve': str
               },
               'note': {
                   'transform': 'midi_to_frequency',
                   'reference_pitch': float,
                   'reference_pitch_note': int
               }
           }
       },
       'note_off': {
           'type': 'per_key',
           'attributes': {
               'trigger': {
                   'type': 'bool'  # Simple trigger event
               },
               'note': {
                   'transform': 'midi_to_frequency',
                   'reference_pitch': float,
                   'reference_pitch_note': int
               }
           }
       },

       # Per-key (polyphonic) sources
       'key_pressure': {  # Poly aftertouch
           'type': 'per_key',
           'range': {'min': float, 'max': float},
           'curve': str
       },
       'key_timbre': {  # Y-axis/CC74 per note
           'type': 'per_key',
           'range': {'min': float, 'max': float},
           'curve': str
       },
       'key_bend': {
           'type': 'per_key',
           'range': {'min': float, 'max': float},  # In semitones
           'curve': str
       },

       # Global sources
       'channel_pressure': {  # Mono aftertouch
           'type': 'global',
           'range': {'min': float, 'max': float},
           'curve': str
       },
       'pitch_bend': {
           'type': 'global',
           'range': {'min': float, 'max': float},  # In semitones
           'curve': str
       },
       
       # Generated sources (LFOs, etc)
       'lfo1': {
           'type': 'global',
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
           'amount': {...},
           'envelope': {  # LFO fade envelope
               'attack': {...},
               'decay': {...},
               'sustain': {...},
               'release': {...}
           }
       }
   },
   
   # Unified Patching System
   'patches': [
       {
           'source': {
               'id': str,          # Reference to a source (e.g., 'note_on', 'lfo1', 'key_pressure')
               'attribute': str    # Optional - specific attribute of source (e.g., 'envelope.attack')
           },
           'destination': {
               'id': str,          # Reference to a module (e.g., 'oscillator', 'filter')
               'attribute': str    # Specific parameter (e.g., 'frequency', 'resonance')
           },
           'processing': {
               'amount': float,    # Modulation amount/depth
               'curve': str,       # Transform curve type
               'range': {          # Optional range mapping
                   'in_min': float,
                   'in_max': float,
                   'out_min': float,
                   'out_max': float
               }
           }
       }
   ]
}
"""
