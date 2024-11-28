"""
voices.py - Voice and Note Management

Manages voice objects containing synthio notes.
Uses synthesizer.py for all value calculations.
Handles routes based on config path structure.
"""
import time
import sys
import synthio
from synthesizer import Synthesizer
from constants import VOICES_DEBUG, SAMPLE_RATE, AUDIO_CHANNEL_COUNT

def _log(message, module="VOICES"):
    """Strategic logging for voice state changes"""
    if not VOICES_DEBUG:
        return
        
    RED = "\033[31m"
    YELLOW = "\033[33m"  # For rejected messages
    LIGHT_YELLOW = "\033[93m"  # For standard messages
    RESET = "\033[0m"
    
    def format_voice_update(identifier, param_type, value):
        """Format voice parameter update."""
        return f"Voice update: {identifier} {param_type}={value}"

    if isinstance(message, str) and '/' in message:
        print(f"{LIGHT_YELLOW}[{module}] Route: {message}{RESET}", file=sys.stderr)
    elif isinstance(message, dict):
        formatted = format_voice_update(
            message.get('identifier', 'unknown'),
            message.get('type', 'unknown'),
            message.get('value', 'unknown')
        )
        print(f"{LIGHT_YELLOW}[{module}] {formatted}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message) or "[FAIL]" in str(message):
            color = RED
        elif "[REJECTED]" in str(message):
            color = YELLOW
        else:
            color = LIGHT_YELLOW
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class VoiceBeep:
    """Simple audio test that runs as part of VoiceManager initialization"""

    # Static note parameters for the beep
    BEEP_FREQUENCY = 440
    BEEP_AMPLITUDE = 0.5

    def play(self, synth):
        try:
            # Create a simple synthio note with static parameters
            note = synthio.Note(
                frequency=self.BEEP_FREQUENCY,
                amplitude=self.BEEP_AMPLITUDE
            )

            _log("VoiceBeep: pressing NOTE ...")
            synth.press(note)
            time.sleep(0.5)

            _log("VoiceBeep: releasing NOTE ...")
            synth.release(note)
            time.sleep(0.5)

            _log("VoiecBeep: PRESSING 64 ...")
            synth.press(64)
            time.sleep(0.5)
            
            _log("VoiceBeep: Releasing 64 ...")
            synth.release(64)
            time.sleep(0.5)

        except Exception as e:
            _log(f"[VoiceBeep] error: {str(e)}")

class Voice:
    """Represents a single voice containing a synthio note"""
    def __init__(self, channel, note_number, synth_tools):
        self.channel = channel
        self.note_number = note_number
        self.identifier = f"{channel}.{note_number}"
        self.synth_tools = synth_tools
        self.note = None
        self.active = False
        
        # Parameters for note creation/update
        self.params = {
            'frequency': None,
            'amplitude': 1.0,
            'envelope': None,
            'bend': 0.0,
            'ring_frequency': 0.0,
            'filter': None,
            'waveform': None
        }
        _log(f"Created voice: {self.identifier}")

    def is_ready_for_note(self):
        """Check if we have minimum required parameters for note creation"""
        return self.params['frequency'] is not None

    def update_param(self, param, value):
        """Update parameter and note if it exists"""
        _log(f"Updating voice parameter: {self.identifier} {param}={value}")
        self.params[param] = value
        
        if self.note:
            try:
                setattr(self.note, param, value)
                _log(f"Updated note parameter: {self.identifier} {param}={value}")
            except Exception as e:
                _log(f"[ERROR] Failed to update note parameter: {str(e)}")
        
        if not self.note and self.is_ready_for_note():
            self.create_note()

    def assemble_envelope(self):
        """Create envelope from stored parameters"""
        envelope_params = {
            'attack_time': self.params.get('attack_time', 0),
            'decay_time': self.params.get('decay_time', 0),
            'release_time': self.params.get('release_time', 0),
            'attack_level': self.params.get('attack_level', 1.0),
            'sustain_level': self.params.get('sustain_level', 0.8)
        }
        try:
            return synthio.Envelope(**envelope_params)
        except Exception as e:
            _log(f"[ERROR] Failed to create envelope: {str(e)}")
            return None

    def create_note(self):
        try:
            # Prepare note parameters
            note_params = {
                'frequency': self.params['frequency'],
                'amplitude': self.params['amplitude'],
                'bend': self.params['bend'],
                'ring_frequency': self.params['ring_frequency']
            }
            _log({
                'type': 'note_creation',
                'identifier': self.identifier,
                'frequency': note_params['frequency'],
                'amplitude': note_params['amplitude'],
                'bend': note_params['bend'],
                'ring_frequency': note_params['ring_frequency']
            })

            # Create and add envelope if we have envelope parameters
            envelope = self.assemble_envelope()
            if envelope:
                note_params['envelope'] = envelope
                _log({
                    'type': 'envelope_creation',
                    'identifier': self.identifier,
                    'attack_time': envelope.attack_time,
                    'decay_time': envelope.decay_time,
                    'release_time': envelope.release_time,
                    'attack_level': envelope.attack_level,
                    'sustain_level': envelope.sustain_level
                })

            # Create note with clean parameter set
            self.note = synthio.Note(**note_params)
            self.active = True
            _log(f"Created note for voice: {self.identifier}")
        except Exception as e:
            _log(f"[ERROR] Failed to create note: {str(e)}")
            self.active = False

    def release(self):
        """Begin release phase of note"""
        if self.note and hasattr(self.note, 'envelope') and self.note.envelope:
            _log(f"Starting release phase for voice: {self.identifier}")
            self.active = False
        else:
            self.active = False
            self.note = None
            _log(f"Released voice immediately: {self.identifier}")

    def is_active(self):
        """Check if voice is currently active"""
        return self.active

class VoiceManager:
    """Manages collection of voices and their lifecycle"""
    def __init__(self):
        _log("Starting VoiceManager initialization...")
        
        # Parameter mapping from routes to synthio
        self.param_map = {
            'attack_time': 'attack_time',
            'decay_time': 'decay_time',
            'release_time': 'release_time',
            'attack_level': 'attack_level',
            'sustain_level': 'sustain_level',
            'frequency': 'frequency',
            'gain': 'amplitude',
            'pressure': 'amplitude',
            'bend': 'bend',
        }

        # Voice management
        self.voices = {}  # identifier -> Voice
        self.synth_tools = Synthesizer()
        
        # Global state
        self.global_params = {}  # For parameters that apply to all voices
        self.channel_params = {}  # Store params by channel for future voices
        
        # Main synthesizer
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        
        # Create the VoiceBeep instance and play the test tone
        self.voice_beep = VoiceBeep()
        self.voice_beep.play(self.synth)
        
        _log("VoiceManager initialization complete")

    def get_synth(self):
        """Get synthesizer instance for audio system"""
        return self.synth

    def extract_identifier(self, param_path):
        """Extract channel and note from parameter path if present"""
        parts = param_path.split('/')
        for part in parts:
            if '.' in part and len(part.split('.')) == 2:
                channel, note = part.split('.')
                try:
                    return int(channel), int(note)
                except ValueError:
                    return None, None
        return None, None

    def store_channel_param(self, channel, param_path, value):
        """Store parameter for a specific channel"""
        if channel not in self.channel_params:
            self.channel_params[channel] = {}
        param_name = param_path.split('/')[-1]
        if param_name in self.param_map:
            synth_param = self.param_map[param_name]
            self.channel_params[channel][synth_param] = value
            _log(f"Stored channel parameter: ch={channel} {synth_param}={value}")
        else:
            _log(f"[ERROR] Unknown parameter: {param_name}")

    def store_global_param(self, param_path, value):
        """Store global parameter"""
        parts = param_path.split('/')
        # Find the parameter name - it's the part before the value
        param_name = None
        for part in parts:
            try:
                float(part)  # If this succeeds, we've hit the value
                break
            except ValueError:
                param_name = part
                
        if param_name and param_name in self.param_map:
            synth_param = self.param_map[param_name]
            self.global_params[synth_param] = value
            _log(f"Stored global parameter: {synth_param}={value}")
        else:
            _log(f"[ERROR] Unknown parameter: {param_name}")

    def apply_stored_params(self, voice):
        """Apply stored parameters to a new voice"""
        # Apply global params
        for param, value in self.global_params.items():
            voice.update_param(param, value)
        
        # Apply channel-specific params
        if voice.channel in self.channel_params:
            for param, value in self.channel_params[voice.channel].items():
                voice.update_param(param, value)

    def find_scope_in_path(self, parts):
        """Find scope (global or per_key) in path parts"""
        for part in parts:
            if part in ['global', 'per_key']:
                return part
        return None

    def handle_route(self, route):
        """Process incoming routes and update voices"""
        _log(f"Processing route: {route}")
        
        parts = route.split('/')
        if len(parts) < 4:
            _log(f"[ERROR] Invalid route format: {route}")
            return

        signal_chain = parts[0]
        scope = self.find_scope_in_path(parts)
        if not scope:
            _log(f"[ERROR] No scope found in route: {route}")
            return
            
        param_path = '/'.join(parts[1:])  # Include all parts for parameter handling
        value = float(parts[-1])

        # Extract channel and note if present in path
        channel, note = self.extract_identifier(param_path)

        if scope == 'global':
            self.handle_global_route(signal_chain, param_path, value)
        elif scope == 'per_key':
            self.handle_per_key_route(signal_chain, param_path, value, channel, note)

    def handle_global_route(self, signal_chain, param_path, value):
        """Handle global parameter routes"""
        _log(f"Processing global route: {signal_chain}/{param_path}")
        
        # Store global parameter
        self.store_global_param(param_path, value)
        
        # Apply to all active voices
        for voice in self.voices.values():
            if voice.is_active():
                self.apply_parameter(voice, signal_chain, param_path, value)

    def handle_per_key_route(self, signal_chain, param_path, value, channel, note):
        _log(f"Processing per-key route: {signal_chain}/{param_path}")

        # Store channel-specific parameters if we have a channel
        if channel is not None and note is None:
            self.store_channel_param(channel, param_path, value)
            _log(f"Stored channel parameter: ch={channel}, param_path={param_path}, value={value}")

        # If we have both channel and note
        if channel is not None and note is not None:
            identifier = f"{channel}.{note}"

            # Create new voice if needed and all required params are present
            if identifier not in self.voices and signal_chain == 'frequency' and \
            'frequency' in self.channel_params.get(channel, {}):
                _log(f"Creating new voice: identifier={identifier}")
                voice = Voice(channel, note, self.synth_tools)
                self.voices[identifier] = voice
                self.apply_stored_params(voice)
                self.press_note(voice)  # Press the note

            # Update existing voice
            if identifier in self.voices:
                voice = self.voices[identifier]
                self.apply_parameter(voice, signal_chain, param_path, value)
                if voice.is_ready_for_note():
                    _log("Voice ready, pressing ...")
                    self.press_note(voice)  # Press the note

    def press_note(self, voice):
        """Press a note in the synthesizer"""
        try:
            self.synth.press(voice.note)
            _log(f"Pressed note: {voice.identifier}")
        except Exception as e:
            _log(f"[ERROR] Failed to press note: {str(e)}")

    def apply_parameter(self, voice, signal_chain, param_path, value):
        """Apply parameter update to voice based on signal chain"""
        if signal_chain == 'frequency':
            # Use synth_tools to calculate frequency from MIDI note number
            freq = self.synth_tools.note_to_frequency(value)
            _log({
                'type': 'frequency_update',
                'identifier': voice.identifier,
                'new_frequency': freq
            })
            voice.update_param('frequency', freq)
            
        elif signal_chain == 'amplifier':
            if 'envelope' in param_path:
                self.handle_envelope_update(voice, param_path, value)
            elif 'gain' in param_path:
                _log({
                    'type': 'amplitude_update',
                    'identifier': voice.identifier,
                    'new_amplitude': value
                })
                voice.update_param('amplitude', value)
            elif 'pressure' in param_path:
                amplitude = self.synth_tools.calculate_pressure_amplitude(value, voice.params['amplitude'])
                _log({
                    'type': 'amplitude_update',
                    'identifier': voice.identifier,
                    'new_amplitude': amplitude
                })
                voice.update_param('amplitude', amplitude)
                
        elif signal_chain == 'filter':
            filter_parts = param_path.split('/')
            if len(filter_parts) >= 2:
                param = filter_parts[-1]
                if param == 'frequency':
                    new_filter = self.synth_tools.calculate_filter(value, None)
                    _log({
                        'type': 'filter_update',
                        'identifier': voice.identifier,
                        'new_filter_frequency': value,
                        'new_filter_resonance': new_filter.resonance
                    })
                    voice.update_param('filter', new_filter)
                elif param == 'resonance':
                    current_freq = 1000  # Default if not set
                    if voice.params['filter']:
                        current_freq = voice.params['filter'].frequency
                    new_filter = self.synth_tools.calculate_filter(current_freq, value)
                    _log({
                        'type': 'filter_update',
                        'identifier': voice.identifier,
                        'new_filter_frequency': current_freq,
                        'new_filter_resonance': value
                    })
                    voice.update_param('filter', new_filter)

    def handle_envelope_update(self, voice, param_path, value):
        """Update envelope parameters"""
        parts = param_path.split('/')
        if 'release' in parts:
            voice.release()
        else:
            try:
                new_envelope = voice.params.get('envelope', None)
                if new_envelope is None:
                    new_envelope = synthio.Envelope()
                
                # Update envelope parameter
                param_name = parts[-1]
                setattr(new_envelope, param_name, value)
                voice.update_param('envelope', new_envelope)
            except Exception as e:
                _log(f"[ERROR] Failed to update envelope: {str(e)}")

    def cleanup_voices(self):
        """Remove completed voices"""
        for voice_id, voice in list(self.voices.items()):
            if not voice.is_active():
                if voice.note:
                    voice.note = None
                del self.voices[voice_id]
                _log(f"Cleaned up voice: {voice_id}")

    def cleanup(self):
        """Cleanup synthesizer"""
        if self.synth:
            self.synth.deinit()
            _log("Synthesizer cleaned up")