"""
Voice Management System

Manages synthesizer voices with channel and note number tracking.
Receives and applies parameter streams from router.
"""

import time
import sys
import math
import synthio
from constants import VOICES_DEBUG, SAMPLE_RATE
from synthesizer import Synthesis

def _log(message, module="VOICES"):
    """Strategic logging for voice state changes"""
    if not VOICES_DEBUG:
        return
        
    RED = "\033[31m"
    YELLOW = "\033[33m"  # For rejected messages
    LIGHT_YELLOW = "\033[93m"  # For standard messages
    RESET = "\033[0m"
    
    def format_parameter_stream(stream, stage=""):
        """Format parameter stream with nice indentation."""
        lines = []
        lines.append(f"[{module}]")
        lines.append("Parameter stream:")
        lines.append(f"  stage: {stage}")
        lines.append(f"  value: {stream['value']}")
        lines.append("  target:")
        target = stream['target']
        lines.append(f"    type: {target.get('type', 'control')}")
        lines.append(f"    path: {target['path']}")
        lines.append(f"    module: {target['module']}")
        lines.append(f"  channel: {stream['channel']}")
        return "\n".join(lines)
    
    if isinstance(message, dict):
        formatted = format_parameter_stream(message, "received")
        print(f"{LIGHT_YELLOW}{formatted}{RESET}\n", file=sys.stderr)
    else:
        if "[ERROR]" in str(message) or "[FAIL]" in str(message):
            color = RED
        elif "[REJECTED]" in str(message):
            color = YELLOW
        else:
            color = LIGHT_YELLOW
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

def midi_to_frequency(note, reference_pitch=440.0, reference_note=69):
    """Convert MIDI note number to frequency"""
    return reference_pitch * (2 ** ((note - reference_note) / 12))

class Voice:
    """Manages a single voice instance for a specific channel and note"""
    def __init__(self, channel, note_number, synthesis, frequency):
        _log(f"[CREATE] Voice ch {channel}, note {note_number}, freq {frequency}")
        
        self.channel = channel
        self.note_number = note_number
        self.active = True
        self.creation_time = time.monotonic()
        self.synthesis = synthesis
        
        # Create basic synthio note with frequency
        self.synth_note = synthio.Note(frequency=frequency)
        
    def update_parameter(self, target, value):
        """Apply parameter update from router"""
        try:
            module = target.get('module')
            path = target['path']
            update_type = target.get('type', 'control')
            
            # Log in new format
            _log({
                'value': value,
                'target': {
                    'type': update_type,
                    'path': path,
                    'module': module
                },
                'channel': self.channel
            })
            
            # Extract parameter name from path
            param_parts = path.split('.')
            param_name = param_parts[-1]
            
            # Oscillator handling
            if module == 'oscillator':
                if param_name == 'frequency':
                    # Convert MIDI note to frequency if it's a raw note number
                    if isinstance(value, int):
                        frequency = midi_to_frequency(value)
                        self.synthesis.update_note(self.synth_note, 'frequency', frequency)
                    else:
                        self.synthesis.update_note(self.synth_note, 'frequency', float(value))
                elif param_name == 'bend':
                    self.synthesis.update_note(self.synth_note, 'bend', float(value))
                elif param_name == 'waveform':
                    # Create waveform using synthesis.waveform_manager
                    waveform = self.synthesis.waveform_manager.get_waveform(
                        value['type'], value)
                    if waveform:
                        self.synthesis.update_note(self.synth_note, 'waveform', waveform)
                elif update_type == 'trigger':
                    # Note on trigger - handled by synthio.Synthesizer.press()
                    pass
            
            # Amplifier handling
            elif module == 'amplifier':
                if param_name == 'gain':
                    self.synthesis.update_note(self.synth_note, 'amplitude', float(value))
                elif param_parts[0] == 'envelope':
                    if update_type == 'trigger' and 'release' in path:
                        # Handle release trigger
                        self.release()
                    elif len(param_parts) >= 3:
                        stage = param_parts[1]
                        param = param_parts[2]
                        
                        # Create envelope if needed
                        if not hasattr(self.synth_note, 'envelope'):
                            self.synth_note.envelope = synthio.Envelope()
                        
                        # Map envelope parameters to synthio names
                        if stage == 'attack':
                            if param == 'time':
                                self.synthesis.update_note(self.synth_note, 'envelope_attack_time', float(value))
                            elif param == 'value':
                                self.synthesis.update_note(self.synth_note, 'envelope_attack_level', float(value))
                        elif stage == 'decay':
                            if param == 'time':
                                self.synthesis.update_note(self.synth_note, 'envelope_decay_time', float(value))
                        elif stage == 'sustain':
                            if param == 'value':
                                self.synthesis.update_note(self.synth_note, 'envelope_sustain_level', float(value))
                        elif stage == 'release':
                            if param == 'time':
                                self.synthesis.update_note(self.synth_note, 'envelope_release_time', float(value))
                elif update_type == 'trigger':
                    pass
            
            # Filter handling
            elif module == 'filter':
                if param_name == 'frequency':
                    self.synthesis.update_note(self.synth_note, 'filter_frequency', float(value))
                elif param_name == 'resonance':
                    self.synthesis.update_note(self.synth_note, 'filter_resonance', float(value))
                elif update_type == 'trigger':
                    pass
                
        except Exception as e:
            _log(f"[FAIL] Parameter update failed: {str(e)}")
            _log(f"[FAIL] Target details: {target}")
            _log(f"[FAIL] Value: {value}")
        
    def release(self):
        """Start voice release phase"""
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            _log(f"[RELEASE] Ch {self.channel}, Note {self.note_number}")

class VoiceManager:
    """Manages voice collection with channel and note tracking"""
    def __init__(self, output_manager, sample_rate=SAMPLE_RATE):
        _log("Initializing voice manager")
        self.active_voices = {}
        self.last_note_number = {}
        self.pending_params = {}  # Store parameters until we can create voice
        self.pending_triggers = set()  # Track channels with pending triggers
        self.routed_params = {}  # Store latest values for routed parameters
        
        try:
            # Initialize basic synthesizer
            self.synthio_synth = synthio.Synthesizer(
                sample_rate=sample_rate,
                channel_count=2  # Stereo output
            )
            
            if output_manager and hasattr(output_manager, 'attach_synthesizer'):
                output_manager.attach_synthesizer(self.synthio_synth)
                _log("[CREATE] Synth initialized")
                
            self.synthesis = Synthesis(self.synthio_synth)
            _log("[CREATE] Synthesis engine initialized")
                
        except Exception as e:
            _log(f"[FAIL] Synth initialization failed: {str(e)}")
            self.synthio_synth = None
            self.synthesis = None

    def try_create_voice(self, channel):
        """Attempt to create a voice if we have all required parameters"""
        if (channel in self.pending_params and
            'frequency' in self.pending_params[channel] and
            channel in self.pending_triggers):
            
            try:
                params = self.pending_params[channel]
                note_number = params['note_number']
                frequency = params['frequency']
                
                # Create voice with basic frequency
                voice = Voice(channel, note_number, self.synthesis, frequency)
                self.active_voices[channel] = voice
                
                # Apply any routed parameters that have values
                for path, value in self.routed_params.items():
                    voice.update_parameter({'path': path, 'module': path.split('.')[0]}, value)
                
                # Press the note after all parameters are set
                self.synthio_synth.press(voice.synth_note)
                _log(f"[CREATE] Voice created on channel {channel}, note {note_number}")
                
                # Clear pending state
                self.pending_triggers.discard(channel)
                return True
                
            except Exception as e:
                _log(f"[FAIL] Voice creation failed: {str(e)}")
                return False
                
        return False
                
    def process_parameter_stream(self, stream):
        """Process parameter stream from router"""
        if not stream:
            _log("[FAIL] Received empty parameter stream")
            return
            
        channel = stream.get('channel')
        target = stream.get('target')
        value = stream.get('value')
        
        # Log the stream in the new format
        _log({
            'value': value,
            'target': target,
            'channel': channel
        })
        
        if not target:
            _log("[FAIL] No target in parameter stream")
            return
        
        if channel is None:
            _log("[FAIL] No channel in parameter stream")
            return

        # Store routed parameter value
        path = target['path']
        if target.get('type') == 'control':
            self.routed_params[path] = value
            
        # Initialize pending parameters for this channel if needed
        if channel not in self.pending_params:
            self.pending_params[channel] = {}
            
        # Handle oscillator trigger
        if (target.get('type') == 'trigger' and 
            target.get('path') == 'oscillator' and
            value == 1):
            self.pending_triggers.add(channel)
            
        # Handle frequency/note number
        elif target.get('path') == 'oscillator.frequency':
            note_number = value if isinstance(value, int) else None
            if note_number:
                frequency = midi_to_frequency(note_number)
                self.pending_params[channel]['frequency'] = frequency
                self.pending_params[channel]['note_number'] = note_number
                self.last_note_number[channel] = note_number
                
        # Store parameter for later if no voice exists yet
        if channel not in self.active_voices:
            self.pending_params[channel][target['path']] = value
            _log({
                'value': value,
                'target': {
                    'type': target.get('type', 'control'),
                    'path': target['path'],
                    'module': target['path'].split('.')[0]
                },
                'channel': channel,
                'stage': 'stored for future voice'
            })
            # Try to create voice if we have necessary parameters
            self.try_create_voice(channel)
            return
                
        # Update existing voice
        voice = self.active_voices[channel]
        try:
            voice.update_parameter(target, value)
        except Exception as e:
            _log(f"[FAIL] Voice parameter update failed: {str(e)}")
            _log(f"[FAIL] Stream details: {stream}")
                
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
                _log(f"[CLEANUP] Ch {voice.channel}, Note {voice.note_number}")
                del self.active_voices[channel]
                # Also clean up pending state
                if channel in self.pending_params:
                    del self.pending_params[channel]
                self.pending_triggers.discard(channel)
