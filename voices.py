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
        elif "[PARAM]" in str(message):
            color = GREEN
        else:
            color = LIGHT_MAGENTA
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class Voice:
    """Manages a single voice instance and its parameters"""
    def __init__(self, channel, note_params, synthesis):
        _log(f"[CREATE] Voice ch {channel}")
        
        self.channel = channel
        self.active = True
        self.creation_time = time.monotonic()
        self.note_number = note_params.get('note', 0)
        self.synthesis = synthesis
        
        # Create note with basic parameters
        self.synth_note = self._create_note(note_params)
        
    def _create_note(self, params):
        """Create synthio note with initial configuration"""
        try:
            note_params = {
                'frequency': params.get('frequency', 440),
                'amplitude': 1.0,
                'bend': 0.0,
                'panning': 0.0
            }
            
            # Create note
            note = synthio.Note(**note_params)
            _log("[CREATE] Note created")
            
            return note
            
        except Exception as e:
            _log(f"[ERROR] Note creation failed: {str(e)}")
            return None

    def _handle_oscillator(self, path, value, update_type):
        """Handle oscillator module parameters"""
        if not self.synth_note:
            return False
            
        if path == 'frequency':
            self.synth_note.frequency = float(value)
            return True
        elif path == 'bend':
            self.synth_note.bend = float(value)
            return True
        elif update_type == 'trigger':
            _log(f"[TRIGGER] Oscillator {path}")
            return True
        return False

    def _handle_amplifier(self, path, value, update_type):
        """Handle amplifier module parameters"""
        if not self.synth_note:
            return False

        parts = path.split('.')
        if parts[0] == 'gain':
            self.synth_note.amplitude = float(value)
            return True
        elif parts[0] == 'envelope':
            if not hasattr(self.synth_note, 'envelope'):
                return False
                
            if len(parts) < 3:  # need at least envelope.stage.param
                return False

            stage = parts[1]  # attack/decay/sustain/release
            param = parts[2]  # time/value/level/start
                
            # Handle trigger paths (e.g. envelope.release.start)
            if param == 'start':
                _log(f"[TRIGGER] Envelope {stage} start")
                return True
                
            # Handle parameter updates
            param_name = f"{stage}_{'level' if param == 'value' else param}"
            if hasattr(self.synth_note.envelope, param_name):
                setattr(self.synth_note.envelope, param_name, value)
                _log(f"[PARAM] Envelope {param_name} = {value}")
                return True
        elif update_type == 'trigger':
            _log(f"[TRIGGER] Amplifier {path}")
            return True
        return False

    def _handle_filter(self, path, value, update_type):
        """Handle filter module parameters"""
        if not self.synth_note or not hasattr(self.synth_note, 'filter'):
            return False
            
        parts = path.split('.')
        param = parts[-1]
        current_filter = self.synth_note.filter
            
        if param == 'frequency':
            frequency = float(value)
            Q = getattr(current_filter, 'Q', 0.707)
            self.synth_note.filter = self.synthesis.synthio_synth.low_pass_filter(
                frequency=frequency,
                Q=Q
            )
            _log(f"[PARAM] Filter frequency = {frequency}")
            return True
                
        elif param == 'resonance':
            Q = float(value)
            frequency = getattr(current_filter, 'frequency', 20000)
            self.synth_note.filter = self.synthesis.synthio_synth.low_pass_filter(
                frequency=frequency,
                Q=Q
            )
            _log(f"[PARAM] Filter Q = {Q}")
            return True
        elif update_type == 'trigger':
            _log(f"[TRIGGER] Filter {path}")
            return True
        return False
        
    def update_parameter(self, target, value):
        """Apply parameter update from router"""
        try:
            module = target['module']
            path = target['path']
            update_type = target['type']
            
            _log(f"[PARAM] Updating {module}.{path} = {value}")
            
            # Handle each module's parameters
            if module == 'oscillator':
                return self._handle_oscillator(path, value, update_type)
            elif module == 'amplifier':
                return self._handle_amplifier(path, value, update_type)
            elif module == 'filter':
                return self._handle_filter(path, value, update_type)
                
        except Exception as e:
            _log(f"[ERROR] Parameter update failed: {str(e)}")
            
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
        self.pending_params = {}
        
        try:
            # Initialize synthio synthesizer
            self.synthio_synth = synthio.Synthesizer(
                sample_rate=sample_rate,
                channel_count=2
            )
            
            if output_manager and hasattr(output_manager, 'attach_synthesizer'):
                output_manager.attach_synthesizer(self.synthio_synth)
                _log("[CREATE] Synth initialized")
                
            # Create synthesis instance with synth reference
            self.synthesis = Synthesis(self.synthio_synth)
            _log("[CREATE] Synthesis engine initialized")
                
        except Exception as e:
            _log(f"[ERROR] Synth initialization failed: {str(e)}")
            self.synthio_synth = None
            self.synthesis = None
                
    def process_parameter_stream(self, stream):
        """Process parameter stream from router"""
        if not stream:
            return
            
        channel = stream.get('channel')
        target = stream.get('target')
        value = stream.get('value')
        
        if not target:
            return
            
        # Log received parameter stream
        _log(f"[PARAM] Stream: {target['module']}.{target['path']} = {value}")
        
        # Handle note creation on oscillator frequency control
        if (target['module'] == 'oscillator' and 
            target['type'] == 'control' and 
            target['path'] == 'frequency'):
            
            if channel not in self.active_voices:
                # Create new voice
                note_params = {'frequency': value}
                voice = self.create_voice(channel, note_params)
                
                if voice:  # Apply any pending parameters
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
            _log(f"[PARAM] Stored pending for ch {channel}")
            return
            
        # Apply parameter updates
        if channel is None:
            # Global parameter - update all voices
            if not self.active_voices:
                _log(f"[REJECTED] No voices for {target['module']}.{target['path']} = {value}")
                return
            for voice in self.active_voices.values():
                voice.update_parameter(target, value)
        else:
            # Per-voice parameter - update specific voice
            voice = self.active_voices.get(channel)
            if voice:
                voice.update_parameter(target, value)
            else:
                _log(f"[REJECTED] No voice on ch {channel}")
                
    def create_voice(self, channel, params):
        """Create new voice"""
        try:
            voice = Voice(channel, params, self.synthesis)
            
            if voice and voice.synth_note:
                self.active_voices[channel] = voice
                self.synthio_synth.press(voice.synth_note)
                return voice
               
        except Exception as e:
            _log(f"[ERROR] Voice creation failed: {str(e)}")
            
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
