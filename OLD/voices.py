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
    def __init__(self, channel, note_number, synthesis, frequency, envelope_params=None):
        _log(f"[CREATE] Voice ch {channel}, note {note_number}, freq {frequency}")
        
        self.channel = channel
        self.note_number = note_number
        self.active = True
        self.creation_time = time.monotonic()
        self.synthesis = synthesis
        self.router = None
        self.sustain_timer_elapsed = False
        
        # Create note through synthesis layer with envelope params
        self.synth_note = self.synthesis.create_note(frequency, envelope_params)
        if not self.synth_note:
            raise Exception("Failed to create note")
        
    def update_parameter(self, target, value):
        """Apply parameter update from router"""
        try:
            module = target.get('module')
            path = target['path']
            update_type = target.get('type', 'control')
            source_type = target.get('source_type')
            
            _log({
                'value': value,
                'target': {
                    'type': update_type,
                    'path': path,
                    'module': module,
                    'source_type': source_type
                },
                'channel': self.channel
            })
            
            # Handle timer sources 
            if 'sources' in path and 'timer' in path:
                stage = None
                # Extract envelope stage from path
                path_parts = path.split('.')
                for i, part in enumerate(path_parts):
                    if part == 'envelope' and i + 1 < len(path_parts):
                        stage = path_parts[i + 1]
                        break
                        
                if not stage:
                    _log(f"[FAIL] Could not extract stage from timer path: {path}")
                    return
                    
                param_id = f"timer_{stage}"
                
                # Register callback to send timer.end trigger through route when timer ends
                def timer_end_callback(timer_name):
                    if stage == 'sustain':
                        self.sustain_timer_elapsed = True
                        # Create timer end trigger based on routes 
                        end_trigger = {
                            'type': 'trigger',
                            'source_type': 'timer',
                            'source_event': 'end',
                            'module': 'amplifier', 
                            'path': 'amplifier.envelope.release'
                        }
                        # Send trigger to self through normal parameter handling
                        self.update_parameter(end_trigger, 1)
                
                self.synthesis.register_timer_callback(self.synth_note, param_id, timer_end_callback)
                self.synthesis.update_note(self.synth_note, param_id, value)
                return
            
            # Handle triggers
            if update_type == 'trigger':
                if source_type == 'timer' and 'release' in path:  
                    self.start_release()
                return
                
            # Handle other parameters
            param_name = path.split('.')[-1]
            
            # Oscillator parameters
            if module == 'oscillator':
                if param_name == 'frequency':
                    if isinstance(value, int):
                        frequency = midi_to_frequency(value)
                        self.synthesis.update_note(self.synth_note, 'frequency', frequency)
                    else:
                        self.synthesis.update_note(self.synth_note, 'frequency', value)
                elif param_name == 'waveform':
                    self.synthesis.update_note(self.synth_note, 'waveform', value)
                    
            # Amplifier parameters  
            elif module == 'amplifier':
                if param_name == 'gain':
                    self.synthesis.update_note(self.synth_note, 'amplitude', value)
                elif path.startswith('amplifier.envelope'):
                    parts = path.split('.')
                    if len(parts) >= 3:
                        stage = parts[2]  # attack, decay, sustain, release
                        param = param_name  # time, level
                        param_id = f"envelope_{stage}_{param}"
                        self.synthesis.update_note(self.synth_note, param_id, value)
                        
            # Filter parameters
            elif module == 'filter':  
                if param_name == 'frequency':
                    self.synthesis.update_note(self.synth_note, 'filter_frequency', value)
                elif param_name == 'resonance':
                    self.synthesis.update_note(self.synth_note, 'filter_resonance', value)
                    
        except Exception as e:
            _log(f"[FAIL] Parameter update failed: {str(e)}")
            _log(f"[FAIL] Target details: {target}")
            _log(f"[FAIL] Value: {value}")
        
    def start_release(self):
        """Start release phase by setting tracking variables"""
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            _log(f"[RELEASE] Ch {self.channel}, Note {self.note_number}")

class VoiceManager:
    """Manages voice collection with channel and note tracking"""
    def __init__(self, output_manager, sample_rate=SAMPLE_RATE):
        _log("Initializing voice manager")
        self.active_voices = {}  # Key is (channel, note_number)
        self.pending_params = {}  # Store parameters until we can create voice
        self.pending_triggers = set()  # Track channels with pending triggers
        self.global_params = {}  # Store global CC values that apply to all voices
        self.per_key_params = {}  # Store per-key CC values
        
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

    def try_create_voice(self, channel, note_number):
        """Attempt to create a voice if we have all required parameters"""
        if (channel in self.pending_params and
            'frequency' in self.pending_params[channel] and
            channel in self.pending_triggers):
            
            try:
                params = self.pending_params[channel]
                frequency = params['frequency']
                
                # Extract envelope parameters from global params
                envelope_params = {}
                for path, value in self.global_params.items():
                    if 'envelope' in path:
                        parts = path.split('.')
                        if len(parts) >= 4:
                            if 'sources' in path and 'timer' in path:
                                continue
                            stage = parts[2]
                            param = parts[3]
                            param_name = f"{stage}_{param}"
                            envelope_params[param_name] = value
                
                # Create voice with frequency and envelope params
                voice = Voice(channel, note_number, self.synthesis, frequency, envelope_params)
                self.active_voices[(channel, note_number)] = voice
                
                # Apply any stored global parameters
                for path, value in self.global_params.items():
                    voice.update_parameter({'path': path, 'module': path.split('.')[0]}, value)
                
                # Apply any stored per-key parameters
                key = (channel, note_number) 
                if key in self.per_key_params:
                    for path, value in self.per_key_params[key].items():
                        voice.update_parameter({'path': path, 'module': path.split('.')[0]}, value)
                
                self.synthio_synth.press(voice.synth_note)
                _log(f"[CREATE] Voice created on channel {channel}, note {note_number}")
                
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
        
        _log({
            'value': value,
            'target': target,
            'channel': channel
        })
        
        if not target or channel is None:
            _log("[FAIL] Missing target or channel in stream")
            return
            
        path = target['path']
        source_type = target.get('source_type')
        
        # Store and apply global CC parameters
        if source_type == 'cc':
            self.global_params[path] = value
            for key, voice in list(self.active_voices.items()):
                if key[0] == channel:
                    try:
                        voice.update_parameter(target, value)
                    except Exception as e:
                        _log(f"[FAIL] Voice parameter update failed: {str(e)}")
            return
        
        # Initialize pending parameters
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
                self.try_create_voice(channel, note_number)
                return
                
        # Store parameters for pending voices
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
            return
            
        # Handle per-key parameters
        if source_type == 'per_key':
            if 'note_number' in self.pending_params.get(channel, {}):
                note_number = self.pending_params[channel]['note_number']
                key = (channel, note_number)
                if key in self.active_voices:
                    voice = self.active_voices[key]
                    voice.update_parameter(target, value)
                    
    def cleanup_voices(self):
        """Remove completed voices and check for sustain timeouts"""
        current_time = time.monotonic()
        
        # Check for timed releases
        elapsed_timers = self.synthesis.check_timers()
        for timer_name in elapsed_timers:
            try:
                note_id = int(timer_name.split('_')[0])
                for key, voice in list(self.active_voices.items()):
                    if id(voice.synth_note) == note_id:
                        _log(f"[AUTO-RELEASE] Ch {voice.channel}, Note {voice.note_number} (timer elapsed)")
                        # Timer callback will create and send release trigger
                        break
            except Exception as e:
                _log(f"[ERROR] Failed to process timer: {str(e)}")
                
        # Clean up released voices after release phase completes
        for key in list(self.active_voices.keys()):
            voice = self.active_voices[key]
            if not voice.active:
                release_time = voice.synth_note.envelope.release_time
                if (current_time - voice.release_time) > release_time:
                    _log(f"[CLEANUP] Ch {voice.channel}, Note {voice.note_number}")
                    if key in self.per_key_params:
                        del self.per_key_params[key]
                    del self.active_voices[key]
                    if voice.channel in self.pending_params:
                        del self.pending_params[voice.channel]
                    self.pending_triggers.discard(voice.channel)