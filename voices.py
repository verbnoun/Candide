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

class RouteError(Exception):
    """Custom exception for route processing errors"""
    pass

class AmplifierEnvelope:
    """Manages envelope parameters for synthio Note amplifier envelopes"""
    def __init__(self):
        self.envelope = None
        self.params = {}

    def update_param(self, param_name, value):
        """Update parameter and recreate envelope"""
        _log(f"Updating envelope parameter: {param_name}={value}")
        self.params[param_name] = value
        try:
            self.envelope = synthio.Envelope(
                attack_time=self.params.get('attack_time', 0),
                decay_time=self.params.get('decay_time', 0),
                release_time=self.params.get('release_time', 0),
                attack_level=self.params.get('attack_level', 0),
                sustain_level=self.params.get('sustain_level', 0)
            )
            _log(f"Created new envelope with params: {self.params}")
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
        
        self.voices = {}  # identifier -> Voice
        self.synth_tools = Synthesizer()
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        self.amplifier_envelope = AmplifierEnvelope()
        
        # MPE state tracking per channel
        self.pending_mpe = {}  
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

    def handle_route(self, route):
        """Route handler entry point"""
        _log(f"Processing route: {route}")
        
        try:
            # Split and validate basic route structure
            parts = route.split('/')
            if len(parts) < 4:  # need minimum segments
                raise RouteError(f"Invalid route format - insufficient parts: {route}")
            
            # Extract base route components
            signal_chain = parts[0]
            scope = parts[1]
            param_path = '/'.join(parts[2:-1])
            
            try:
                value = float(parts[-1])
            except ValueError:
                raise RouteError(f"Invalid value in route: {parts[-1]}")

            # Delegate to appropriate signal chain handler
            self._route_signal_chain(signal_chain, scope, param_path, value)
            
        except RouteError as e:
            _log(f"[ERROR] {str(e)}")
        except Exception as e:
            _log(f"[ERROR] Unexpected error processing route: {str(e)}")

    def _route_signal_chain(self, signal_chain, scope, param_path, value):
        """Route to appropriate signal chain handler"""
        handlers = {
            'amplifier': self._handle_amplifier,
            'frequency': self._handle_frequency,
            'square': self._handle_square
        }
        
        handler = handlers.get(signal_chain)
        if handler:
            handler(scope, param_path, value)
        else:
            raise RouteError(f"Unimplemented signal chain: {signal_chain}")

    def _handle_amplifier(self, scope, param_path, value):
        """Handle amplifier signal chain"""
        _log(f"Handling amplifier route: scope={scope}, param_path={param_path}")
        
        if scope == 'global':
            self._handle_amplifier_global(param_path, value)
        elif scope == 'per_key':
            self._handle_amplifier_per_key(param_path, value)
        else:
            raise RouteError(f"Unimplemented amplifier scope: {scope}")

    def _handle_amplifier_global(self, param_path, value):
        """Handle global amplifier parameters"""
        parts = param_path.split('/')
        
        if parts[0] == 'envelope':
            if len(parts) < 2:
                raise RouteError("Missing envelope parameter name")
                
            param_name = parts[-1]
            _log(f"Updating global amplifier envelope: {param_name}={value}")
            
            new_envelope = self.amplifier_envelope.update_param(param_name, value)
            if new_envelope:
                # Apply new envelope to all active voices
                for voice in self.voices.values():
                    if voice.is_active():
                        voice.update_param('envelope', new_envelope)
        else:
            raise RouteError(f"Unimplemented amplifier parameter path: {param_path}")

    def _handle_amplifier_per_key(self, param_path, value):
        """Handle per-key amplifier parameters"""
        raise RouteError("Per-key amplifier handling not yet implemented")

    def _handle_frequency(self, scope, param_path, value):
        """Handle frequency signal chain"""
        raise RouteError("Frequency handling not yet implemented")

    def _handle_square(self, scope, param_path, value):
        """Handle square wave signal chain"""
        raise RouteError("Square wave handling not yet implemented")

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