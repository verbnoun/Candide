"""
Voice Management System for Candide Synthesizer
Mirrors router.py's structure for voice parameter control
"""

import time
import sys
import synthio
from fixed_point_math import FixedPoint
from constants import VOICES_DEBUG, SAMPLE_RATE
from synthesizer import Synthesis
from router import OscillatorRouter, FilterRouter, AmplifierRouter

def _log(message):
    if not VOICES_DEBUG:
        return
    RED = "\033[31m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        print(f"{CYAN}{message}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message):
            color = RED
        elif "[SYNTHIO]" in str(message):
            color = GREEN
        else:
            color = CYAN
        print(f"{color}[VOICES] {message}{RESET}", file=sys.stderr)

class VoiceModule:
    """Base class for voice modules"""
    def __init__(self, config, synthesis):
        self.config = config
        self.synthesis = synthesis
        self.module_name = "BASE"
        
    def get_config(self):
        """Get module-specific configuration"""
        return self.config.get(self.module_name) if self.config else None
        
    def update_parameter(self, note, param, value):
        """Update parameter on synthio note"""
        if not note:
            return False
        try:
            if isinstance(value, FixedPoint):
                value = FixedPoint.to_float(value)
            return self.synthesis.update_note(note, param, value)
        except Exception as e:
            _log(f"[ERROR] Failed to update {param}: {str(e)}")
            return False

class EnvelopeVoice(VoiceModule):
    """Envelope module that can be used by other modules"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "envelope"
        self.envelope = None
        self.create_envelope(config)
        
    def create_envelope(self, config):
        """Create synthio envelope from config"""
        try:
            env_params = {}
            env_config = config.get('parameters', {}).get('envelope', {})
            
            for stage in ['attack', 'decay', 'sustain', 'release']:
                if stage in env_config:
                    stage_config = env_config[stage]
                    for param in ['time', 'level']:
                        if param in stage_config:
                            param_config = stage_config[param]
                            if 'value' in param_config:
                                env_params[f"{stage}_{param}"] = param_config['value']
                                
            if len(env_params) >= 5:  # Minimum required params
                self.envelope = synthio.Envelope(**env_params)
                
        except Exception as e:
            _log(f"[ERROR] Failed to create envelope: {str(e)}")
            
    def update_parameter(self, note, stage, param, value):
        """Update envelope parameter"""
        if not note or not hasattr(note, 'envelope'):
            return False
        try:
            if isinstance(value, FixedPoint):
                value = FixedPoint.to_float(value)
            setattr(note.envelope, f"{stage}_{param}", value)
            return True
        except Exception as e:
            _log(f"[ERROR] Failed to update envelope {stage}.{param}: {str(e)}")
            return False

class OscillatorVoice(VoiceModule):
    """Oscillator-specific voice implementation"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "oscillator"
        self.waveform = None
        self.configure_waveform(config)
        
    def configure_waveform(self, config):
        """Set up waveform from config"""
        try:
            osc_config = config.get('parameters', {})
            if 'waveform' in osc_config:
                self.waveform = self.synthesis.waveform_manager.get_waveform(
                    osc_config['waveform'].get('type', 'triangle'),
                    osc_config['waveform']
                )
        except Exception as e:
            _log(f"[ERROR] Failed to configure waveform: {str(e)}")
            
    def update_frequency(self, note, value):
        """Update oscillator frequency"""
        return self.update_parameter(note, 'frequency', value)

class FilterVoice(VoiceModule):
    """Filter-specific voice implementation"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "filter"
        
    def update_parameter(self, note, param, value):
        """Update filter parameter"""
        if not note or not hasattr(note, 'filter'):
            return False
        try:
            if isinstance(value, FixedPoint):
                value = FixedPoint.to_float(value)
            setattr(note.filter, param, value)
            return True
        except Exception as e:
            _log(f"[ERROR] Failed to update filter {param}: {str(e)}")
            return False

class AmplifierVoice(VoiceModule):
    """Amplifier-specific voice implementation"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "amplifier"
        self.envelope = None
        
        # Create envelope if configured
        if 'parameters' in config and 'envelope' in config['parameters']:
            self.envelope = EnvelopeVoice(
                {'parameters': {'envelope': config['parameters']['envelope']}},
                synthesis
            )
            
    def update_gain(self, note, value):
        """Update amplifier gain"""
        return self.update_parameter(note, 'amplitude', value)

class Voice:
    """Represents a voice with its modules and synthio note"""
    def __init__(self, channel, note, velocity, config, synthesis):
        self.channel = channel
        self.note = note
        self.velocity = velocity
        self.active = True
        self.creation_time = time.monotonic()
        
        # Initialize modules
        self.oscillator = OscillatorVoice(config.get('oscillator', {}), synthesis)
        self.filter = FilterVoice(config.get('filter', {}), synthesis)
        self.amplifier = AmplifierVoice(config.get('amplifier', {}), synthesis)
        
        # Create synthio note
        self.synth_note = self._create_note()
        
    def _create_note(self):
        """Create synthio note with initial parameters"""
        try:
            freq = FixedPoint.midi_note_to_fixed(self.note)
            amp = FixedPoint.normalize_midi_value(self.velocity)
            
            params = {
                'frequency': FixedPoint.to_float(freq),
                'amplitude': FixedPoint.to_float(amp),
                'waveform': self.oscillator.waveform
            }
            
            if self.amplifier.envelope and self.amplifier.envelope.envelope:
                params['envelope'] = self.amplifier.envelope.envelope
                
            note = synthio.Note(**params)
            _log(f"[SYNTHIO] Created Note: freq={params['frequency']:.1f}Hz, amp={params['amplitude']:.3f}")
            return note
            
        except Exception as e:
            _log(f"[ERROR] Failed to create note: {str(e)}")
            return None
            
    def route_to_destination(self, destination, value, message):
        """Route value to appropriate module parameter"""
        if not self.synth_note:
            return
            
        try:
            module_name = destination['id']
            param = destination['attribute']
            
            if module_name == 'oscillator':
                if param == 'frequency':
                    self.oscillator.update_frequency(self.synth_note, value)
                    
            elif module_name == 'filter':
                self.filter.update_parameter(self.synth_note, param, value)
                
            elif module_name == 'amplifier':
                if 'envelope' in param:
                    if self.amplifier.envelope:
                        _, stage, param_type = param.split('.')
                        self.amplifier.envelope.update_parameter(
                            self.synth_note, stage, param_type, value
                        )
                else:
                    self.amplifier.update_gain(self.synth_note, value)
                    
        except Exception as e:
            _log(f"[ERROR] Failed to route value: {str(e)}")
            
    def release(self):
        """Handle note release"""
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            _log(f"Note released: channel={self.channel}, note={self.note}")

class VoiceManager:
    """Manages voice lifecycle and routing"""
    def __init__(self, output_manager, sample_rate=SAMPLE_RATE):
        _log("Initializing VoiceManager")
        self.active_voices = {}
        self.current_config = None
        self.synthesis = Synthesis()
        self.routers = None
        
        try:
            self.synthio_synth = synthio.Synthesizer(
                sample_rate=sample_rate,
                channel_count=2
            )
            
            if output_manager and hasattr(output_manager, 'attach_synthesizer'):
                output_manager.attach_synthesizer(self.synthio_synth)
                _log("[SYNTHIO] Synthesizer initialized and attached")
                
        except Exception as e:
            _log(f"[ERROR] Synthesizer initialization failed: {str(e)}")
            self.synthio_synth = None
            
    def set_config(self, config):
        """Update current instrument configuration"""
        _log(f"Setting instrument configuration")
        
        if not isinstance(config, dict):
            _log("[ERROR] VoiceManager config must be a dictionary")
            raise ValueError("VoiceManager config must be a dictionary")
        
        self.current_config = config
        
        # Initialize routers
        self.routers = {
            'oscillator': OscillatorRouter(config),
            'filter': FilterRouter(config),
            'amplifier': AmplifierRouter(config)
        }
    
    def allocate_voice(self, channel, note, velocity):
        """Create a new voice for a note"""
        _log(f"Attempting to allocate voice:")
        _log(f"  channel={channel}")
        _log(f"  note={note}")
        _log(f"  velocity={velocity}")
        
        if not self.current_config or not self.routers:
            _log("[ERROR] No current configuration available")
            return None
        
        try:
            # Create voice
            voice = Voice(channel, note, velocity, self.current_config, self.synthesis)
            
            # Create note on message for initial routing
            note_on = {
                'type': 'note_on',
                'channel': channel,
                'data': {
                    'note': note,
                    'velocity': velocity
                }
            }
            
            # Route through module routers
            for router in self.routers.values():
                router.process_message(note_on, voice)
            
            self.active_voices[(channel, note)] = voice
            
            if self.synthio_synth and voice.synth_note:
                self.synthio_synth.press(voice.synth_note)
                _log(f"[SYNTHIO] Pressed note {note}")
            
            _log(f"Voice allocated successfully")
            return voice
            
        except Exception as e:
            _log(f"[ERROR] Voice allocation failed: {str(e)}")
            return None
    
    def get_voice(self, channel, note):
        """Retrieve an active voice"""
        return self.active_voices.get((channel, note))
    
    def release_voice(self, channel, note):
        """Handle voice release"""
        voice = self.get_voice(channel, note)
        if voice:
            voice.release()
            if self.synthio_synth and voice.synth_note:
                self.synthio_synth.release(voice.synth_note)
            return voice
        return None
    
    def cleanup_voices(self):
        """Remove completed voices after grace period"""
        current_time = time.monotonic()
        for key in list(self.active_voices.keys()):
            voice = self.active_voices[key]
            if not voice.active and (current_time - voice.release_time) > 0.5:
                del self.active_voices[key]
                _log(f"Removed inactive voice: channel={key[0]}, note={key[1]}")
