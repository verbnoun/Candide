"""
Voice Management System

Manages synthio note lifecycle and parameter application.
Receives parameter streams from router and maintains voice state.
"""

import time
import sys
import synthio
from constants import VOICES_DEBUG, SAMPLE_RATE
from synthesizer import Synthesis

def _log(message, module="VOICES"):
    """Strategic logging for voice state changes"""
    if not VOICES_DEBUG:
        return
        
    RED = "\033[31m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    GRAY = "\033[90m"
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        formatted = "\n"
        for k, v in message.items():
            formatted += f"  {k}: {v}\n"
        print(f"{BLUE}[{module}]{formatted}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message):
            color = RED
        elif "[CREATE]" in str(message):
            color = GREEN
        elif "[UPDATE]" in str(message):
            color = BLUE
        elif "[RELEASE]" in str(message):
            color = YELLOW
        elif "[CLEANUP]" in str(message):
            color = MAGENTA
        elif "[REJECTED]" in str(message):
            color = GRAY
        else:
            color = BLUE
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class ModuleVoice:
    """Base class for voice modules"""
    def __init__(self, config, synthesis):
        self.synthesis = synthesis
        self.module_name = None
        
    def update_parameter(self, note, parameter, value):
        """Update parameter on note"""
        try:
            result = self.synthesis.update_note(note, parameter, value)
            if result:
                _log(f"[UPDATE] {self.module_name} {parameter}")
            return result
        except Exception as e:
            _log(f"[ERROR] Update failed")
            return False

class EnvelopeVoice(ModuleVoice):
    """Envelope handling for any module"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "envelope"
        self.envelope = None
        if config:
            self._create_envelope(config)
            
    def _create_envelope(self, config):
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
                                
            if len(env_params) >= 5:
                self.envelope = synthio.Envelope(**env_params)
                _log("[CREATE] Envelope created")
                
        except Exception as e:
            _log("[ERROR] Envelope failed")
            
    def update_parameter(self, note, stage, param, value):
        if not note or not hasattr(note, 'envelope'):
            return False
            
        try:
            param_name = f"{stage}_{param}"
            setattr(note.envelope, param_name, value)
            _log(f"[UPDATE] Envelope {param_name}")
            return True
        except Exception as e:
            _log("[ERROR] Envelope update failed")
            return False

class OscillatorVoice(ModuleVoice):
    """Oscillator parameter handling"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "oscillator"
        self.waveform = None
        self.envelope = None
        if config:
            self._configure_waveform(config)
            if 'envelope' in config:
                self.envelope = EnvelopeVoice(config['envelope'], synthesis)
                
    def _configure_waveform(self, config):
        try:
            osc_config = config.get('parameters', {})
            if 'waveform' in osc_config:
                self.waveform = self.synthesis.waveform_manager.get_waveform(
                    osc_config['waveform'].get('type', 'triangle'),
                    osc_config['waveform']
                )
                _log("[CREATE] Waveform configured")
        except Exception as e:
            _log("[ERROR] Waveform failed")

class FilterVoice(ModuleVoice):
    """Filter parameter handling"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "filter"
        self.envelope = None
        if config and 'envelope' in config:
            self.envelope = EnvelopeVoice(config['envelope'], synthesis)
            
    def update_parameter(self, note, param, value):
        if not note or not hasattr(note, 'filter'):
            return False
            
        try:
            setattr(note.filter, param, value)
            _log(f"[UPDATE] Filter {param}")
            return True
        except Exception as e:
            _log("[ERROR] Filter update failed")
            return False

class AmplifierVoice(ModuleVoice):
    """Amplifier parameter handling"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "amplifier"
        self.envelope = None
        if config and 'envelope' in config:
            self.envelope = EnvelopeVoice(config['envelope'], synthesis)

class Voice:
    """Complete voice with all modules"""
    def __init__(self, channel, params, config, synthesis):
        _log(f"[CREATE] Voice ch {channel}")
        
        self.channel = channel
        self.active = True
        self.creation_time = time.monotonic()
        
        self.oscillator = OscillatorVoice(config.get('oscillator'), synthesis)
        self.filter = FilterVoice(config.get('filter'), synthesis)
        self.amplifier = AmplifierVoice(config.get('amplifier'), synthesis)
        
        self.synth_note = self._create_note(params)
        
    def _create_note(self, params):
        """Create synthio note with initial parameters"""
        try:
            note_params = params.copy()
            
            if self.oscillator.waveform:
                note_params['waveform'] = self.oscillator.waveform
                
            if self.amplifier.envelope:
                note_params['envelope'] = self.amplifier.envelope.envelope
                
            note = synthio.Note(**note_params)
            _log("[CREATE] Note created")
            return note
            
        except Exception as e:
            _log("[ERROR] Note failed")
            return None
            
    def update_parameter(self, target, value):
        """Apply parameter update from router"""
        if not self.synth_note:
            return False
        
        try:
            module_name = target['module']
            parameter = target['parameter']
            
            if module_name == 'oscillator':
                module = self.oscillator
            elif module_name == 'filter':
                module = self.filter
            elif module_name == 'amplifier':
                module = self.amplifier
            else:
                return False
                
            if 'envelope' in parameter:
                if module.envelope:
                    _, stage, param = parameter.split('.')
                    return module.envelope.update_parameter(
                        self.synth_note, stage, param, value
                    )
            else:
                return module.update_parameter(self.synth_note, parameter, value)
                
        except Exception as e:
            _log("[ERROR] Update failed")
            return False
            
    def release(self):
        """Start voice release phase"""
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            _log(f"[RELEASE] Ch {self.channel}")

class VoiceManager:
    """Manages voice collection and parameter routing"""
    def __init__(self, output_manager, sample_rate=SAMPLE_RATE):
        _log("Initializing voice manager")
        self.active_voices = {}
        self.current_config = None
        self.synthesis = Synthesis()
        
        try:
            self.synthio_synth = synthio.Synthesizer(
                sample_rate=sample_rate,
                channel_count=2
            )
            
            if output_manager and hasattr(output_manager, 'attach_synthesizer'):
                output_manager.attach_synthesizer(self.synthio_synth)
                _log("[CREATE] Synth initialized")
                
        except Exception as e:
            _log("[ERROR] Synth failed")
            self.synthio_synth = None
            
    def set_config(self, config):
        """Set current instrument configuration"""
        if not isinstance(config, dict):
            _log("[ERROR] Invalid config")
            raise ValueError("Config must be dictionary")
            
        self.current_config = config
        _log("[UPDATE] Config set")
        
    def process_parameter_stream(self, stream):
        """Process parameter stream from router"""
        if not stream or not self.current_config:
            return
            
        channel = stream.get('channel')
        target = stream.get('target')
        value = stream.get('value')
        
        if not target:
            return
            
        # Log received parameter stream
        _log(f"Received parameter stream: {target['module']}.{target['parameter']} = {value}")
        
        if channel is None:
            # Global parameter - update all voices
            if not self.active_voices:
                _log(f"[REJECTED] No active voices to apply {target['module']}.{target['parameter']} = {value}")
                return
            for voice in self.active_voices.values():
                voice.update_parameter(target, value)
        else:
            # Per-key parameter - update specific voice
            voice = self.active_voices.get(channel)
            if voice:
                voice.update_parameter(target, value)
            else:
                _log(f"[REJECTED] No voice on channel {channel} for {target['module']}.{target['parameter']} = {value}")
                
    def create_voice(self, channel, params):
        """Create new voice"""
        if not self.current_config:
            return None
            
        try:
            voice = Voice(channel, params, self.current_config, self.synthesis)
            
            if voice and voice.synth_note:
                self.active_voices[channel] = voice
                self.synthio_synth.press(voice.synth_note)
                return voice
                
        except Exception as e:
            _log("[ERROR] Voice failed")
            
        return None
        
    def release_voice(self, channel):
        """Release voice"""
        voice = self.active_voices.get(channel)
        if voice:
            voice.release()
            if voice.synth_note:
                self.synthio_synth.release(voice.synth_note)
            return True
        return False
        
    def cleanup_voices(self):
        """Remove completed voices"""
        current_time = time.monotonic()
        for channel in list(self.active_voices.keys()):
            voice = self.active_voices[channel]
            if not voice.active and (current_time - voice.release_time) > 0.5:
                _log(f"[CLEANUP] Ch {channel}")
                del self.active_voices[channel]
