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
    LIGHT_MAGENTA = "\033[95m"
    
    if isinstance(message, dict):
        formatted = "\n"
        for k, v in message.items():
            formatted += f"  {k}: {v}\n"
        print(f"{BLUE}[{module}]{formatted}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message):
            color = RED
        elif "[REJECTED]" in str(message):
            color = MAGENTA
        else:
            color = LIGHT_MAGENTA
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class ModuleVoice:
    """Base class for voice modules"""
    def __init__(self, config, synthesis):
        self.synthesis = synthesis
        self.module_name = None
        self.config = config
        
    def handle_trigger(self, note, path, value):
        """Handle a trigger event"""
        _log(f"[TRIGGER] {self.module_name} {path} = {value}")
        return True
        
    def handle_control(self, note, path, value):
        """Handle a control value update"""
        if not note:
            return False
            
        try:
            # Split path into parts for nested parameters
            parts = path.split('.')
            param = parts[-1]  # Last part is the parameter name
            
            result = self.synthesis.update_note(note, param, value)
            if result:
                _log(f"[CONTROL] {self.module_name} {path} = {value}")
            return result
        except Exception as e:
            _log(f"[ERROR] Control update failed: {str(e)}")
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
            
            for stage in ['attack', 'decay', 'sustain', 'release']:
                stage_config = config.get(stage, {})
                
                # Get time value
                if 'time' in stage_config:
                    env_params[f"{stage}_time"] = stage_config['time'].get('value', 0.1)
                    
                # Get level/value
                value_config = stage_config.get('value', {})
                if value_config:
                    env_params[f"{stage}_level"] = value_config.get('value', 1.0)
                    
            if len(env_params) >= 5:  # Need minimum parameters for envelope
                self.envelope = synthio.Envelope(**env_params)
                _log("[CREATE] Envelope created")
                
        except Exception as e:
            _log(f"[ERROR] Envelope failed: {str(e)}")
            
    def handle_trigger(self, note, path, value):
        """Handle envelope triggers like note_on/note_off"""
        if not note or not hasattr(note, 'envelope'):
            return False
            
        try:
            # path format: stage.triggers.event 
            parts = path.split('.')
            if len(parts) >= 2:
                stage = parts[0]  # attack/release/etc
                if value == 1:  # Trigger active
                    _log(f"[TRIGGER] Envelope {stage}")
                    # Logic to handle envelope stage triggering would go here
                    return True
                    
        except Exception as e:
            _log(f"[ERROR] Envelope trigger failed: {str(e)}")
            
        return False
        
    def handle_control(self, note, path, value):
        """Handle envelope parameter updates"""
        if not note or not hasattr(note, 'envelope'):
            return False
            
        try:
            parts = path.split('.')
            if len(parts) >= 2:
                stage = parts[0]  # attack/decay/sustain/release
                param = parts[1]  # time/value
                param_name = f"{stage}_{'level' if param == 'value' else param}"
                setattr(note.envelope, param_name, value)
                _log(f"[CONTROL] Envelope {param_name} = {value}")
                return True
                
        except Exception as e:
            _log(f"[ERROR] Envelope control failed: {str(e)}")
            
        return False

class OscillatorVoice(ModuleVoice):
    """Oscillator parameter handling"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "oscillator"
        self.waveform = None
        if config:
            self._configure_waveform(config)
                
    def _configure_waveform(self, config):
        try:
            if 'waveform' in config:
                self.waveform = self.synthesis.waveform_manager.get_waveform(
                    config['waveform'].get('type', 'triangle'),
                    config['waveform']
                )
                _log("[CREATE] Waveform configured")
        except Exception as e:
            _log(f"[ERROR] Waveform failed: {str(e)}")
            
    def handle_trigger(self, note, path, value):
        """Handle oscillator triggers"""
        _log(f"[TRIGGER] Oscillator {path} = {value}")
        return True

class FilterVoice(ModuleVoice):
    """Filter parameter handling"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "filter"
        self.current_frequency = 20000  # Default to max frequency
        self.current_q = 0.707  # Default Q factor
            
    def handle_control(self, note, path, value):
        """Update filter parameters"""
        try:
            param = path.split('.')[-1]  # Get last part of path
            
            if param == 'frequency':
                self.current_frequency = float(value)
            elif param == 'resonance':
                self.current_q = float(value)
                
            # Create new filter with current parameters
            if hasattr(self.synthesis.synthio_synth, 'low_pass_filter'):
                new_filter = self.synthesis.synthio_synth.low_pass_filter(
                    frequency=self.current_frequency,
                    Q=self.current_q
                )
                note.filter = new_filter
                _log(f"[CONTROL] Filter {param} = {value}")
                return True
                
        except Exception as e:
            _log(f"[ERROR] Filter control failed: {str(e)}")
            
        return False
        
    def handle_trigger(self, note, path, value):
        """Handle filter triggers"""
        _log(f"[TRIGGER] Filter {path} = {value}")
        return True

class AmplifierVoice(ModuleVoice):
    """Amplifier parameter handling"""
    def __init__(self, config, synthesis):
        super().__init__(config, synthesis)
        self.module_name = "amplifier"
        self.envelope = None
        if config and 'envelope' in config:
            self.envelope = EnvelopeVoice(config['envelope'], synthesis)
            
    def handle_trigger(self, note, path, value):
        """Handle amplifier triggers including envelope triggers"""
        parts = path.split('.')
        if len(parts) >= 2 and parts[0] == 'envelope':
            if self.envelope:
                return self.envelope.handle_trigger(note, '.'.join(parts[1:]), value)
        _log(f"[TRIGGER] Amplifier {path} = {value}")
        return True
        
    def handle_control(self, note, path, value):
        """Handle amplifier controls including envelope controls"""
        parts = path.split('.')
        if len(parts) >= 2 and parts[0] == 'envelope':
            if self.envelope:
                return self.envelope.handle_control(note, '.'.join(parts[1:]), value)
        return super().handle_control(note, path, value)

class Voice:
    """Complete voice with all modules"""
    def __init__(self, channel, note_params, config, synthesis):
        _log(f"[CREATE] Voice ch {channel}")
        
        self.channel = channel
        self.active = True
        self.creation_time = time.monotonic()
        self.note_number = note_params.get('note', 0)
        
        self.oscillator = OscillatorVoice(config.get('oscillator'), synthesis)
        self.filter = FilterVoice(config.get('filter'), synthesis)
        self.amplifier = AmplifierVoice(config.get('amplifier'), synthesis)
        
        self.synth_note = self._create_note(note_params)
        
    def _create_note(self, params):
        """Create synthio note with initial parameters"""
        try:
            note_params = {'frequency': params.get('frequency', 440)}
            
            if self.oscillator.waveform:
                note_params['waveform'] = self.oscillator.waveform
                
            if self.amplifier.envelope and self.amplifier.envelope.envelope:
                note_params['envelope'] = self.amplifier.envelope.envelope
                
            # Create note first
            note = synthio.Note(**note_params)
            _log("[CREATE] Note created")
            
            # Create initial filter if synthesizer supports it
            if self.filter and hasattr(self.filter.synthesis.synthio_synth, 'low_pass_filter'):
                note.filter = self.filter.synthesis.synthio_synth.low_pass_filter(
                    frequency=self.filter.current_frequency,
                    Q=self.filter.current_q
                )
                _log("[CREATE] Initial filter attached")
                
            return note
            
        except Exception as e:
            _log(f"[ERROR] Note failed: {str(e)}")
            return None
            
    def update_parameter(self, target, value):
        """Apply parameter update from router"""
        if not self.synth_note:
            return False
        
        try:
            module_name = target['module']
            path = target['path']
            update_type = target['type']
            
            if module_name == 'oscillator':
                module = self.oscillator
            elif module_name == 'filter':
                module = self.filter
            elif module_name == 'amplifier':
                module = self.amplifier
            else:
                return False
                
            if update_type == 'trigger':
                return module.handle_trigger(self.synth_note, path, value)
            else:  # control
                return module.handle_control(self.synth_note, path, value)
                
        except Exception as e:
            _log(f"[ERROR] Update failed: {str(e)}")
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
        self.pending_params = {}
        
        try:
            self.synthio_synth = synthio.Synthesizer(
                sample_rate=sample_rate,
                channel_count=2
            )
            
            if output_manager and hasattr(output_manager, 'attach_synthesizer'):
                output_manager.attach_synthesizer(self.synthio_synth)
                _log("[CREATE] Synth initialized")
                
            # Create synthesis instance with synth reference
            self.synthesis = Synthesis(self.synthio_synth)
                
        except Exception as e:
            _log(f"[ERROR] Synth failed: {str(e)}")
            self.synthio_synth = None
            self.synthesis = None
            
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
        _log(f"Received parameter stream: {target['module']}.{target['path']} = {value}")
        
        # Handle note creation on oscillator frequency control
        if (target['module'] == 'oscillator' and 
            target['type'] == 'control' and 
            target['path'] == 'frequency'):
            
            if channel not in self.active_voices:
                # Create new voice
                note_params = {'frequency': value}
                voice = self.create_voice(channel, note_params)
                
                if voice:  # Only apply pending params if voice creation succeeded
                    # Apply any pending parameters
                    if channel in self.pending_params:
                        for pending_target, pending_value in self.pending_params[channel]:
                            voice.update_parameter(pending_target, pending_value)
                        del self.pending_params[channel]
                    
                return
                
        # Store parameters that arrive before note creation
        if channel is not None and channel not in self.active_voices:
            if channel not in self.pending_params:
                self.pending_params[channel] = []
            self.pending_params[channel].append((target, value))
            _log(f"Stored pending parameter for channel {channel}")
            return
            
        if channel is None:
            # Global parameter - update all voices
            if not self.active_voices:
                _log(f"[REJECTED] No active voices to apply {target['module']}.{target['path']} = {value}")
                return
            for voice in self.active_voices.values():
                voice.update_parameter(target, value)
        else:
            # Per-key parameter - update specific voice
            voice = self.active_voices.get(channel)
            if voice:
                voice.update_parameter(target, value)
            else:
                _log(f"[REJECTED] No voice on channel {channel} for {target['module']}.{target['path']} = {value}")
                
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
            _log(f"[ERROR] Voice failed: {str(e)}")
            
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
