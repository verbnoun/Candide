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
   → Explicit CC assignments for all controls
   → Uses standard MIDI CC numbers (1-127)
   → Can use undefined CCs (3,9,14,15,20-31) for custom controls
   → Maximum 14 CC assignments per instrument

4. Envelope System
   → Gates triggered by note events
   → Each stage can be controlled by MPE signals
   → Controls amplitude over time

5. LFO System
   → Created and routed based on explicit config
   → Can modulate any parameter
   → Can be synced to note events

6. Filter System
   → Parameters controlled via modulation matrix
   → Can respond to envelopes, LFOs, and MPE controls

Every signal path must be explicitly defined in the instrument config.
No routing occurs unless specified here.
"""

from synth_constants import ModSource, ModTarget

class CCMapping:
    """Standard MIDI CC number definitions"""
    # Standard MIDI CCs
    MODULATION_WHEEL = 1
    BREATH = 2
    FOOT = 4
    PORTAMENTO_TIME = 5
    VOLUME = 7
    BALANCE = 8
    PAN = 10
    EXPRESSION = 11
    EFFECT1 = 12
    EFFECT2 = 13
    
    # Sound Controllers
    SOUND_VARIATION = 70
    RESONANCE = 71
    RELEASE_TIME = 72
    ATTACK_TIME = 73
    BRIGHTNESS = 74
    SOUND_CTRL6 = 75
    SOUND_CTRL7 = 76
    SOUND_CTRL8 = 77
    SOUND_CTRL9 = 78
    SOUND_CTRL10 = 79
    
    # Effect Depths
    REVERB = 91
    TREMOLO = 92
    CHORUS = 93
    DETUNE = 94
    PHASER = 95
    
    # Undefined CCs available for custom use
    UNDEFINED1 = 3
    UNDEFINED2 = 9
    UNDEFINED3 = 14
    UNDEFINED4 = 15
    UNDEFINED5 = 20  # 20-31 range available

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
                'resonance': 0.7,
                'controls': [
                    {
                        'name': 'Brightness',
                        'cc': CCMapping.BRIGHTNESS,
                        'target': ModTarget.FILTER_CUTOFF,
                        'amount': 1.0,
                        'curve': 'exponential'
                    },
                    {
                        'name': 'Resonance',
                        'cc': CCMapping.RESONANCE,
                        'target': ModTarget.FILTER_RESONANCE,
                        'amount': 0.8,
                        'curve': 'linear'
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
                        'name': 'Attack Time',
                        'cc': CCMapping.ATTACK_TIME,
                        'target': ModTarget.ENVELOPE_LEVEL,
                        'amount': 0.7,
                        'curve': 'exponential'
                    }
                },
                'decay': {
                    'gate': 'attack_end',
                    'time': 0.1,
                    'level_scale': 0.8,
                    'curve': 'exponential'
                },
                'sustain': {
                    'gate': 'decay_end',
                    'control': {
                        'source': ModSource.PRESSURE,
                        'min_level': 0.0,
                        'max_level': 0.8,
                        'curve': 'linear'
                    },
                    'level': 0.0,
                    'curve': 'linear'
                },
                'release': {
                    'gate': 'note_off',
                    'time': 0.3,
                    'level': 0.0,
                    'curve': 'exponential'
                }
            },
            'modulation': [
                {
                    'name': 'Custom Timbre',
                    'cc': CCMapping.UNDEFINED1,
                    'target': ModTarget.AMPLITUDE,
                    'amount': 0.5,
                    'curve': 'linear'
                },
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
                    'sync_to_gate': True
                }
            },
            'expression': {
                'pressure': False,
                'pitch_bend': False,
                'velocity': True
            },
            'scaling': {
                'velocity': 1.0,
                'pressure': 1.0,
                'pitch_bend': 48
            }
        }

class Piano(InstrumentConfig):
    """Traditional piano with explicit CC routing"""
    def __init__(self):
        super().__init__("Piano")
        
        # Basic piano configuration
        self.config.update({
            'oscillator': {
                'waveform': 'triangle',
                'detune': 0.001
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
                        'amount': 1.0,
                        'curve': 'exponential'
                    },
                    {
                        'name': 'Resonance',
                        'cc': CCMapping.RESONANCE,
                        'target': ModTarget.FILTER_RESONANCE,
                        'amount': 0.8,
                        'curve': 'linear'
                    }
                ]
            },
            'envelope': {
                'attack': {
                    'gate': 'note_on',
                    'time': 0.001,
                    'level': 1.0,
                    'curve': 'linear',
                    'control': {
                        'name': 'Attack Time',
                        'cc': CCMapping.ATTACK_TIME,
                        'target': ModTarget.ENVELOPE_LEVEL,
                        'amount': 0.7,
                        'curve': 'exponential'
                    }
                },
                'decay': {
                    'gate': 'attack_end',
                    'time': 0.8,
                    'level_scale': 0.8,
                    'curve': 'exponential'
                },
                'sustain': {
                    'gate': 'decay_end',
                    'control': {
                        'source': ModSource.PRESSURE,
                        'min_level': 0.0,
                        'max_level': 0.8,
                        'curve': 'linear'
                    },
                    'level': 0.0,
                    'curve': 'linear'
                },
                'release': {
                    'gate': 'note_off',
                    'time': 0.3,
                    'level': 0.0,
                    'curve': 'exponential'
                }
            },
            'modulation': [
                {
                    'name': 'Custom Timbre',
                    'cc': CCMapping.UNDEFINED1,
                    'target': ModTarget.AMPLITUDE,
                    'amount': 0.5,
                    'curve': 'linear'
                },
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
                    'sync_to_gate': True
                }
            },
            'expression': {
                'pressure': True,
                'pitch_bend': False,
                'velocity': True
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
