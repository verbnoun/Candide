"""
Instrument Configuration System

This module defines how MIDI/MPE signals flow through the synthesis engine.
Each instrument configuration acts as a routing map that controls:

Signal Flow:
1. Note Events (note on/off, velocity)
   → Triggers envelope gates
   → Sets initial amplitude via velocity routing

2. MPE Control Signals (pressure, timbre, pitch bend)
   → Routed to parameters via explicit CC assignments
   → Uses standard MIDI CC numbers where appropriate

3. CC Routing
   → Flexible CC controls for any parameter
   → Supports multiple curve types
   → Configurable value ranges
   → Maximum 14 CC assignments per instrument

4. Envelope System
   → Gates triggered by note events
   → Each stage can be controlled by CC
   → Controls amplitude over time

5. LFO System
   → Created and routed based on explicit config
   → Can modulate any parameter
   → Can be synced to note events

Every signal path must be explicitly defined in the instrument config.
No routing occurs unless specified here.
"""

from synth_constants import ModSource, ModTarget, CCMapping

class InstrumentConfig:
    """Base class for instrument configurations"""
    def __init__(self, name):
        self.name = name
        self.config = {
            'name': name,
            'oscillator': {
                'waveform': 'sine',
                'detune': 0.0,
                'control': {
                    'cc': 74,
                    'name': 'Oscillator Detune',
                    'range': {'min': -1.0, 'max': 1.0},
                    'curve': 'linear',
                    'default': 0.0
                }
            },
            'filter': {
                'type': 'low_pass',
                'cutoff': 2000,
                'resonance': 0.7,
                'controls': [
                    {
                        'name': 'Brightness',
                        'cc': CCMapping.BRIGHTNESS,
                        'target': ModTarget.FILTER_CUTOFF,
                        'range': {'min': 500, 'max': 8000},
                        'curve': 'exponential',
                        'default': 2000
                    },
                    {
                        'name': 'Resonance',
                        'cc': CCMapping.RESONANCE,
                        'target': ModTarget.FILTER_RESONANCE,
                        'range': {'min': 0.1, 'max': 2.0},
                        'curve': 's_curve',
                        'default': 0.7
                    }
                ]
            },
            'envelope': {
                'attack': {
                    'gate': 'note_on',
                    'time': 0.01,
                    'level': 1.0,
                    'curve': 'linear',
                    'control': {
                        'cc': CCMapping.ATTACK_TIME,
                        'name': 'Attack Time',
                        'range': {'min': 0.001, 'max': 2.0},
                        'curve': 'logarithmic',
                        'default': 0.01
                    }
                },
                'decay': {
                    'gate': 'attack_end',
                    'time': 0.1,
                    'level_scale': 0.8,
                    'curve': 'exponential',
                    'control': {
                        'cc': 75,
                        'name': 'Decay Time',
                        'range': {'min': 0.01, 'max': 1.0},
                        'curve': 'linear',
                        'default': 0.1
                    }
                },
                'sustain': {
                    'gate': 'decay_end',
                    'level': 0.5,
                    'control': {
                        'source': ModSource.PRESSURE,
                        'min_level': 0.0,
                        'max_level': 0.8,
                        'curve': 'linear'
                    }
                },
                'release': {
                    'gate': 'note_off',
                    'time': 0.3,
                    'level': 0.0,
                    'control': {
                        'cc': CCMapping.RELEASE_TIME,
                        'name': 'Release Time',
                        'range': {'min': 0.01, 'max': 3.0},
                        'curve': 's_curve',
                        'default': 0.3
                    }
                }
            },
            'modulation': [
                {
                    'source': ModSource.VELOCITY,
                    'target': ModTarget.AMPLITUDE,
                    'amount': 1.0,
                    'curve': 'exponential'
                }
            ],
            'lfo': {
                'tremolo': {
                    'rate': 5.0,
                    'shape': 'sine',
                    'min_value': 0.7,
                    'max_value': 1.0,
                    'sync_to_gate': True,
                    'control': {
                        'cc': 1,
                        'name': 'LFO Rate',
                        'range': {'min': 0.1, 'max': 20.0},
                        'curve': 'logarithmic',
                        'default': 5.0
                    }
                }
            },
            'expression': {
                'pressure': True,
                'pitch_bend': False,
                'velocity': True
            },
            'scaling': {
                'velocity': 1.0,
                'pressure': 1.0,
                'pitch_bend': 48
            }
        }

    def _find_controls(self, config):
        """Recursively find all control objects with CC numbers"""
        controls = []
        
        def extract_controls(obj):
            if isinstance(obj, dict):
                # Check if this is a control object
                if all(key in obj for key in ['cc', 'name']):
                    controls.append(obj)
                
                # Recursively search nested dictionaries
                for value in obj.values():
                    extract_controls(value)
            
            # Recursively search lists
            elif isinstance(obj, list):
                for item in obj:
                    extract_controls(item)
        
        extract_controls(config)
        return controls

    def get_config(self):
        """Return the instrument configuration with CC routing"""
        # Find all controls with CC numbers
        controls = self._find_controls(self.config)
        
        # Generate CC routing
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
                'target': control.get('target', ModTarget.NONE)
            }
            used_cc_numbers.add(cc_num)
            
            # Stop if we've reached 14 CC routes
            if len(cc_routing) >= 14:
                break
        
        # Create a copy of the config with CC routing
        config_copy = self.config.copy()
        config_copy['cc_routing'] = cc_routing
        
        return config_copy

class Piano(InstrumentConfig):
    """Traditional piano with explicit CC routing"""
    def __init__(self):
        super().__init__("Piano")
        
        # Piano-specific configuration
        self.config.update({
            'oscillator': {
                'waveform': 'triangle',
                'detune': 0.001,
                'control': {
                    'cc': 75,
                    'name': 'Piano Detune',
                    'range': {'min': -0.01, 'max': 0.01},
                    'curve': 'linear',
                    'default': 0.001
                }
            },
            'filter': {
                'type': 'low_pass',
                'cutoff': 5000,
                'resonance': 0.2,
                'controls': [
                    {
                        'name': 'Brightness',
                        'cc': CCMapping.BRIGHTNESS,
                        'target': ModTarget.FILTER_CUTOFF,
                        'range': {'min': 1000, 'max': 10000},
                        'curve': 'exponential',
                        'default': 5000
                    }
                ]
            },
            'envelope': {
                'attack': {
                    'time': 0.001,
                    'control': {
                        'cc': 73,
                        'name': 'Piano Attack',
                        'range': {'min': 0.0001, 'max': 0.1},
                        'curve': 'logarithmic',
                        'default': 0.001
                    }
                },
                'decay': {
                    'time': 0.8,
                    'control': {
                        'cc': 72,
                        'name': 'Piano Decay',
                        'range': {'min': 0.1, 'max': 2.0},
                        'curve': 's_curve',
                        'default': 0.8
                    }
                }
            }
        })

def create_instrument(name):
    """Factory function to create instrument configurations"""
    instruments = {
        'piano': Piano,
        # Additional instruments would be registered here
    }
    
    if name.lower() in instruments:
        return instruments[name.lower()]()
    return None

def list_instruments():
    """Get list of available instruments"""
    return ['Piano']  # Add others as implemented
