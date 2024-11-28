"""
voices.py - Voice and Note Management

Manages voice objects containing synthio notes.
Uses synthesizer.py for all value calculations.
Handles all possible routes based on config path structure.
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

class AmplifierEnvelope:
    """Manages envelope parameters for synthio Note amplifier envelopes"""
    def __init__(self):
        self.envelope = None
        self.params = {}

    def update_param(self, param_name, value):
        """Update parameter and recreate envelope"""
        self.params[param_name] = value
        try:
            self.envelope = synthio.Envelope(
                attack_time=self.params.get('attack_time', 0),
                decay_time=self.params.get('decay_time', 0),
                release_time=self.params.get('release_time', 0),
                attack_level=self.params.get('attack_level', 0),
                sustain_level=self.params.get('sustain_level', 0)
            )
            return self.envelope
        except Exception as e:
            _log(f"[ERROR] Failed to create amplifier envelope: {str(e)}")
            return None

class Voice:
    """Represents a single voice containing a synthio note"""
    def __init__(self, note_number, channel, synth_tools, synth):
        self.note_number = note_number
        self.channel = channel
        self.identifier = f"{note_number}.{channel}"
        self.synth_tools = synth_tools
        self.synth = synth
        self.note = None
        self.active = False
        
        # Parameters for note creation/update
        self.params = {
            'frequency': None,
            'amplitude': None,
            'envelope': None,
            'bend': 0.0,
            'ring_frequency': 0.0
        }

    def is_ready_for_note(self):
        """Check if we have minimum required parameters for note creation"""
        return self.params['frequency'] is not None

    def update_param(self, param, value):
        """Update parameter and note if it exists"""
        self.params[param] = value
        
        if self.note:
            try:
                setattr(self.note, param, value)
                _log(f"Updated note parameter: {self.identifier} {param}={value}")
            except Exception as e:
                _log(f"[ERROR] Failed to update note parameter: {str(e)}")
        
        if not self.note and self.is_ready_for_note():
            self.create_note()

    def create_note(self):
        """Create note with current parameters"""
        try:
            self.note = synthio.Note(
                frequency=self.params['frequency'],
                amplitude=self.params.get('amplitude', 1.0),
                envelope=self.params.get('envelope'),
                bend=self.params.get('bend', 0.0),
                ring_frequency=self.params.get('ring_frequency', 0.0)
            )
            self.active = True
            _log(f"Created note for voice: {self.identifier}")
        except Exception as e:
            _log(f"[ERROR] Failed to create note: {str(e)}")
            self.active = False

    def release(self):
        """Begin release phase of note"""
        self.active = False
        _log(f"Released voice: {self.identifier}")

    def is_active(self):
        """Check if voice is currently active"""
        return self.active

class VoiceManager:
    """Manages collection of voices and their lifecycle"""
    def __init__(self):
        _log("Starting VoiceManager initialization...")
        
        # Voice collection
        self.voices = {}  # identifier -> Voice
        
        # Synthesis tools
        self.synth_tools = Synthesizer()
        
        # Main synthesizer
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        
        # Global amplifier envelope
        self.amplifier_envelope = AmplifierEnvelope()
        
        # MPE state tracking per channel
        self.pending_mpe = {}  # channel -> {param: value}
        for channel in range(16):
            self.pending_mpe[channel] = {
                'bend': 0.0,
                'pressure': 1.0,
                'ring_frequency': 0.0
            }
        
        _log("VoiceManager initialization complete")

    def get_synth(self):
        """Get synthesizer instance for audio system"""
        return self.synth

    def _handle_amplifier_envelope(self, route_parts, param_name, value):
        """Handle amplifier envelope parameter updates"""
        if route_parts[0] != 'amplifier' or 'envelope' not in route_parts:
            _log(f"[ERROR] Invalid envelope route: {'/'.join(route_parts)}")
            return
            
        new_envelope = self.amplifier_envelope.update_param(param_name, value)
        if new_envelope:
            for voice in self.voices.values():
                if voice.is_active():
                    voice.update_param('envelope', new_envelope)

    def _handle_note_on(self, channel, note_number):
        """Handle note on event"""
        voice_id = f"{note_number}.{channel}"
        
        # Create new voice
        voice = Voice(note_number, channel, self.synth_tools, self.synth)
        
        # Set frequency using note number
        voice.params['frequency'] = self.synth_tools.note_to_frequency(note_number)
        
        # Apply current envelope if it exists
        if self.amplifier_envelope.envelope:
            voice.params['envelope'] = self.amplifier_envelope.envelope
        
        # Apply any pending MPE for this channel
        if channel in self.pending_mpe:
            for param, value in self.pending_mpe[channel].items():
                voice.params[param] = value
            # Reset pending MPE
            self.pending_mpe[channel] = {
                'bend': 0.0,
                'pressure': 1.0,
                'ring_frequency': 0.0
            }
        
        self.voices[voice_id] = voice
        voice.create_note()

    def _handle_note_off(self, channel, note_number):
        """Handle note off event"""
        voice_id = f"{note_number}.{channel}"
        if voice_id in self.voices:
            self.voices[voice_id].release()

    def _get_voice_by_channel(self, channel):
        """Find voice using specified channel"""
        for voice in self.voices.values():
            if voice.channel == channel and voice.is_active():
                return voice
        return None

    def _handle_mpe_update(self, channel, param, value):
        """Handle MPE parameter update"""
        voice = self._get_voice_by_channel(channel)
        if voice:
            voice.update_param(param, value)
        else:
            self.pending_mpe[channel][param] = value

    def handle_route(self, route):
        """Process routes in format: signal_chain/signal_chain/scope/channel/params/value"""
        _log(f"Processing route: {route}")
        
        parts = route.split('/')
        if len(parts) < 5:
            _log(f"[ERROR] Invalid route format: {route}")
            return

        signal_chain = parts[0]
        scope = parts[2]
        channel = int(parts[3])
        param_path = '/'.join(parts[4:-1])
        value = float(parts[-1])

        if scope == 'global':
            if 'envelope' in param_path:
                param_name = param_path.split('/')[-1]
                self._handle_amplifier_envelope(parts, param_name, value)

        elif scope == 'per_key':
            if 'frequency' in param_path:
                note_number = int(value)
                self._handle_note_on(channel, note_number)
                
            elif 'release' in param_path:
                note_number = int(value)
                self._handle_note_off(channel, note_number)
                
            else:
                # MPE parameter updates
                if 'pressure' in param_path:
                    self._handle_mpe_update(channel, 'amplitude', value)
                elif 'bend' in param_path:
                    self._handle_mpe_update(channel, 'bend', value)
                elif 'ring_frequency' in param_path:
                    self._handle_mpe_update(channel, 'ring_frequency', value)

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