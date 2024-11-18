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
                'resonance': 0.7
            },
            'expression': {
                'pressure': False,    # Must be explicitly enabled
                'pitch_bend': False,  # Must be explicitly enabled
                'velocity': True      # Always enabled for basic dynamics
            },
            'cc_routing': {
                # Maps CC numbers to parameter targets with explicit routing
                # Example: 74: {'target': ModTarget.FILTER_CUTOFF, 'amount': 1.0, 'curve': 'linear'}
            },
            'envelope': {
                'attack': {
                    'gate': 'note_on',
                    'time': 0.01,
                    'level': None,
                    'curve': 'linear'
                },
                'decay': {
                    'gate': 'attack_end',
                    'time': 0.1,
                    'level_scale': 1.0,
                    'curve': 'exponential'
                },
                'sustain': {
                    'gate': 'decay_end',
                    'control': None,
                    'level': 0.8,
                    'curve': 'linear'
                },
                'release': {
                    'gate': 'note_off',
                    'time': 0.2,
                    'level': 0.0,
                    'curve': 'exponential'
                }
            },
            'lfo': {},
            'modulation': [],
            'scaling': {
                'velocity': 1.0,
                'pressure': 1.0,
                'pitch_bend': 48,
            }
        }

    def add_cc_route(self, cc_number, target, amount=1.0, curve='linear', description=None):
        """Add CC routing configuration"""
        if len(self.config['cc_routing']) >= 14:
            raise ValueError("Maximum of 14 CC routes exceeded")
            
        self.config['cc_routing'][cc_number] = {
            'target': target,
            'amount': amount,
            'curve': curve,
            'description': description
        }

    def add_lfo(self, name, rate, shape='triangle', min_value=0.0, max_value=1.0, sync_to_gate=False):
        """Add LFO configuration"""
        self.config['lfo'][name] = {
            'rate': rate,
            'shape': shape,
            'min_value': min_value,
            'max_value': max_value,
            'sync_to_gate': sync_to_gate
        }

    def add_modulation_route(self, source, target, amount=1.0, curve='linear'):
        """Add a modulation routing"""
        self.config['modulation'].append({
            'source': source,
            'target': target,
            'amount': amount,
            'curve': curve
        })

    def get_config(self):
        """Get complete configuration"""
        return self.config

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
                'resonance': 0.2
            },
            'expression': {
                'pressure': True,
                'pitch_bend': False,
                'velocity': True
            },
            'envelope': {
                'attack': {
                    'gate': 'note_on',
                    'time': 0.001,
                    'level': None,
                    'curve': 'linear'
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
            }
        })
        
        # Add explicit CC routing using standard MIDI CCs
        self.add_cc_route(
            CCMapping.BRIGHTNESS,
            ModTarget.FILTER_CUTOFF,
            amount=1.0,
            curve='exponential',
            description="Filter Brightness"
        )
        
        self.add_cc_route(
            CCMapping.RESONANCE,
            ModTarget.FILTER_RESONANCE,
            amount=0.8,
            curve='linear',
            description="Filter Resonance"
        )
        
        self.add_cc_route(
            CCMapping.ATTACK_TIME,
            ModTarget.ENVELOPE_LEVEL,
            amount=0.7,
            curve='exponential',
            description="Attack Time"
        )
        
        # Using an undefined CC for custom timbre control
        self.add_cc_route(
            CCMapping.UNDEFINED1,
            ModTarget.AMPLITUDE,
            amount=0.5,
            curve='linear',
            description="Custom Timbre Control"
        )
        
        # Optional tremolo effect
        self.add_lfo(
            name='tremolo',
            rate=5.0,
            min_value=0.7,
            max_value=1.0,
            sync_to_gate=True
        )
        
        # Basic velocity to amplitude routing
        self.add_modulation_route(
            ModSource.VELOCITY,
            ModTarget.AMPLITUDE,
            amount=1.0,
            curve='exponential'
        )

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
