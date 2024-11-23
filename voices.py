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
        lines.append("Parameter stream:")
        if stage:
            lines.append(f"  stage: {stage}")
        lines.append(f"  value: {stream['value']}")
        lines.append("  target:")
        target = stream['target']
        lines.append(f"    type: {target['type']}")
        lines.append(f"    path: {target['path']}")
        lines.append(f"    module: {target['module']}")
        lines.append(f"  channel: {stream['channel']}")
        return "\n".join(lines)
    
    if isinstance(message, dict):
        formatted = format_parameter_stream(message, "received")
        print(f"\n{LIGHT_YELLOW}[{module}]\n{formatted}{RESET}\n", file=sys.stderr)
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
        
        # Create synthio note with required frequency
        self.synth_note = synthio.Note(
            frequency=frequency,
            amplitude=1.0  # Default amplitude, will be updated by velocity
        )
        
    def update_parameter(self, target, value):
        """Apply parameter update from router"""
        try:
            module = target.get('module')
            path = target['path']
            update_type = target.get('type', 'control')
            
            _log(f"[PARAM] Updating {module}.{path} = {value} (type: {update_type})")
            
            # Oscillator handling
            if module == 'oscillator':
                if path == 'frequency':
                    # Convert MIDI note to frequency if it's a raw note number
                    if isinstance(value, int):
                        frequency = midi_to_frequency(value)
                        self.synth_note.frequency = frequency
                        _log(f"[PARAM] Oscillator frequency = {frequency} (from note {value})")
                    else:
                        self.synth_note.frequency = float(value)
                        _log(f"[PARAM] Oscillator frequency = {value}")
                elif path == 'bend':
                    self.synth_note.bend = float(value)
                    _log(f"[PARAM] Oscillator bend = {value}")
                elif update_type == 'trigger':
                    _log(f"[TRIGGER] Oscillator {path}")
            
            # Amplifier handling
            elif module == 'amplifier':
                parts = path.split('.')
                if parts[0] == 'gain':
                    self.synth_note.amplitude = float(value)
                    _log(f"[PARAM] Amplifier gain = {value}")
                elif parts[0] == 'envelope':
                    if update_type == 'trigger' and 'release' in path:
                        # Handle release trigger
                        self.release()
                        _log(f"[TRIGGER] Amplifier release triggered")
                    elif len(parts) >= 3:
                        stage = parts[1]
                        param = parts[2]
                        param_name = f"{stage}_{'level' if param == 'value' else param}"
                        
                        if hasattr(self.synth_note.envelope, param_name):
                            setattr(self.synth_note.envelope, param_name, float(value))
                            _log(f"[PARAM] Envelope {param_name} = {value}")
                        else:
                            _log(f"[FAIL] Cannot set envelope parameter: {param_name}")
                elif update_type == 'trigger':
                    _log(f"[TRIGGER] Amplifier {path}")
            
            # Filter handling
            elif module == 'filter':
                param = path.split('.')[-1]
                if param == 'frequency':
                    current_filter = self.synth_note.filter
                    Q = getattr(current_filter, 'Q', 0.707)
                    self.synth_note.filter = self.synthesis.synthio_synth.low_pass_filter(
                        frequency=float(value),
                        Q=Q
                    )
                    _log(f"[PARAM] Filter frequency = {value}")
                elif param == 'resonance':
                    current_filter = self.synth_note.filter
                    frequency = getattr(current_filter, 'frequency', 20000)
                    self.synth_note.filter = self.synthesis.synthio_synth.low_pass_filter(
                        frequency=frequency,
                        Q=float(value)
                    )
                    _log(f"[PARAM] Filter Q = {value}")
                elif update_type == 'trigger':
                    _log(f"[TRIGGER] Filter {path}")
                
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
        
        try:
            self.synthio_synth = synthio.Synthesizer(
                sample_rate=sample_rate,
                channel_count=2
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
                
                voice = Voice(channel, note_number, self.synthesis, frequency)
                self.active_voices[channel] = voice
                self.synthio_synth.press(voice.synth_note)
                _log(f"[CREATE] Voice created on channel {channel}, note {note_number}")
                
                # Apply any pending parameters
                for path, val in params.items():
                    if path not in ['frequency', 'note_number']:
                        voice.update_parameter({'path': path, 'module': path.split('.')[0]}, val)
                
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
        
        # Log the stream in the desired format
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
                _log(f"[NOTE] Stored frequency {frequency} for note {note_number}")
                
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
