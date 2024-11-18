"""
Instrument Configuration System

This module defines how MIDI/MPE signals flow through the synthesis engine.
Each instrument configuration acts as a routing map that controls:

Signal Flow:
1. Note Events (note on/off, velocity)
   → Triggers envelope gates
   → Sets initial amplitude via velocity routing

2. MPE Control Signals (pressure, timbre, pitch bend)
   → Only processed if explicitly enabled in config
   → Routed to specified parameters via modulation matrix

3. Envelope System
   → Gates triggered by note events
   → Each stage can be controlled by MPE signals
   → Controls amplitude over time

4. LFO System
   → Created and routed based on explicit config
   → Can modulate any parameter
   → Can be synced to note events

5. Filter System
   → Parameters controlled via modulation matrix
   → Can respond to envelopes, LFOs, and MPE controls

Every signal path must be explicitly defined in the instrument config.
No routing occurs unless specified here.
"""

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
            'expression': {
                'pressure': False,    # Must be explicitly enabled
                'pitch_bend': False,  # Must be explicitly enabled
                'timbre': False,      # Must be explicitly enabled
                'velocity': True      # Always enabled for basic dynamics
            },
            'envelope': {
                'attack': {
                    'gate': 'note_on',       # Gate trigger source
                    'time': 0.01,            # Stage duration
                    'level': None,           # Uses velocity if None
                    'curve': 'linear'        # Level curve type
                },
                'decay': {
                    'gate': 'attack_end',    
                    'time': 0.1,             
                    'level_scale': 1.0,      # Relative to attack peak
                    'curve': 'exponential'   
                },
                'sustain': {
                    'gate': 'decay_end',     
                    'control': None,         # Optional MPE control source
                    'level': 0.8,            # Fixed level if no control
                    'curve': 'linear'        
                },
                'release': {
                    'gate': 'note_off',      
                    'time': 0.2,             
                    'level': 0.0,            
                    'curve': 'exponential'   
                }
            },
            'lfo': {},              # LFO definitions
            'modulation': [],       # Modulation route definitions
            'scaling': {
                'velocity': 1.0,    # 0-1 scaling of velocity response
                'pressure': 1.0,    # 0-1 scaling of pressure response
                'timbre': 1.0,      # 0-1 scaling of timbre response
                'pitch_bend': 48,   # Semitones of pitch bend range
            }
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
    """Traditional piano with gate-based envelope control and MPE expression"""
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
                'pressure': True,     # Used for sustain control
                'pitch_bend': False,
                'timbre': False,
                'velocity': True
            },
            'envelope': {
                'attack': {
                    'gate': 'note_on',
                    'time': 0.001,
                    'level': None,     # Use velocity
                    'curve': 'linear'
                },
                'decay': {
                    'gate': 'attack_end',
                    'time': 0.8,
                    'level_scale': 0.8,  # 80% of attack
                    'curve': 'exponential'
                },
                'sustain': {
                    'gate': 'decay_end',
                    'control': {
                        'source': ModSource.PRESSURE,
                        'min_level': 0.0,
                        'max_level': 0.8,  # 80% of decay level
                        'curve': 'linear'
                    },
                    'level': 0.0,     # Initial level without pressure
                    'curve': 'linear'
                },
                'release': {
                    'gate': 'note_off',
                    'time': 0.3,
                    'level': 0.0,
                    'curve': 'exponential'
                }
            },
            'scaling': {
                'velocity': 1.0,
                'pressure': 1.0,
                'timbre': 0.0,     # Not used
                'pitch_bend': 0,    # Not used
            }
        })
        
        # Optional soft pedal modulation
        self.add_lfo(
            name='tremolo',
            rate=5.0,
            min_value=0.7,
            max_value=1.0,
            sync_to_gate=True
        )
        
        # Only add modulation for enabled expression
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
