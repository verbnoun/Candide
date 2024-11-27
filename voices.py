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

class EnvelopeHandler:
    def __init__(self, synth_tools, default_params=None):
        self.synth_tools = synth_tools
        self.envelope = None
        self.default_params = default_params or {
            'attack_time': 0.1,
            'decay_time': 0.05,
            'sustain_level': 0.8,
            'release_time': 0.2,
            'attack_level': 1.0
        }

    def update_envelope(self, params):
        self.envelope = self.synth_tools.calculate_envelope(params, 'amplitude')

    def handle_route(self, route_parts):
        envelope_params = self.default_params.copy()
        for part in route_parts:
            if part.startswith('attack_time'):
                envelope_params['attack_time'] = float(part.split('/')[-1])
            elif part.startswith('decay_time'):
                envelope_params['decay_time'] = float(part.split('/')[-1])
            elif part.startswith('attack_level'):
                envelope_params['attack_level'] = float(part.split('/')[-1])
            elif part.startswith('sustain_level'):
                envelope_params['sustain_level'] = float(part.split('/')[-1])
            elif part.startswith('release_time'):
                envelope_params['release_time'] = float(part.split('/')[-1])

        self.update_envelope(envelope_params)

class Voice:
    """Represents a single voice containing a synthio note"""
    def __init__(self, synth_tools, synth, required_params):
        self.note = None
        self.identifier = None
        self.start_time = time.monotonic()
        self.synth_tools = synth_tools
        self.synth = synth
        self.active = False
        
        # Required parameters for note creation
        self.params = {
            'frequency': None,
            'waveform': None,
            'amplitude': None,
            'envelope': None,
            'bend': None,
            'pressure': None,
            'timbre': None
        }
        
        # Apply any pre-configured parameters
        if required_params:
            self.params.update(required_params)
            self.envelope_handler = EnvelopeHandler(synth_tools, required_params['envelope'])
            self.params['envelope'] = self.envelope_handler.envelope

    def is_ready_for_note(self):
        """Check if we have all required parameters to create note"""
        return all(self.params[p] is not None for p in ['frequency', 'waveform', 'amplitude'])

    def update_param(self, param, value):
        if param == 'envelope':
            self.envelope_handler.handle_route(value.split('/'))
            self.params['envelope'] = self.envelope_handler.envelope
        else:
            self.params[param] = value
        _log({
            'identifier': self.identifier,
            'type': f'param_update_{param}',
            'value': value
        })
        
        if self.is_ready_for_note() and not self.note:
            self.create_note()

    def create_note(self):
        """Create note with all parameters"""
        try:
            self.note = synthio.Note(
                frequency=self.params['frequency'],
                waveform=self.params['waveform'],
                amplitude=self.params['amplitude'],
                envelope=self.params['envelope'],
                bend=self.params['bend'],
                ring_frequency=self.params.get('timbre', 0.0)
            )
            self.active = True
            _log(f"Created note for voice: {self.identifier}")
        except Exception as e:
            _log(f"[ERROR] Failed to create note: {str(e)}")
            self.active = False

    def release(self):
        """Begin release phase of note"""
        self.active = False
        _log(f"Released voice: identifier={self.identifier}")

    def is_active(self):
        """Check if voice is currently active"""
        return self.active

class VoiceManager:
    """Manages collection of voices and their lifecycle"""
    def __init__(self):
        _log("Starting VoiceManager initialization...")
        
        # Voice collection
        _log("Creating voice collection...")
        self.voices = {}
        
        # Synthesis tools
        _log("Creating synthesis tools instance...")
        self.synth_tools = Synthesizer()
        
        # Main synthesizer
        _log("Creating main synthio.Synthesizer instance...")
        _log(f"Parameters: SAMPLE_RATE={SAMPLE_RATE}, AUDIO_CHANNEL_COUNT={AUDIO_CHANNEL_COUNT}")
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        
        # Track global envelope parameters
        self.global_params = {
            'attack_time': None,
            'decay_time': None,
            'attack_level': None,
            'sustain_level': None
        }
        
        # Track per-channel MPE state
        _log("Initializing channel state tracking...")
        self.channel_state = {}
        for channel in range(16):
            self.channel_state[channel] = {
                'pitch_bend': None,
                'pressure': None,
                'timbre': None
            }
        
        self.global_envelope_handler = EnvelopeHandler(self.synth_tools, self.global_params)
        _log("VoiceManager initialization complete")

    def get_synth(self):
        """Get synthesizer instance for audio system"""
        return self.synth

    def update_global_param(self, param, value):
        """Update global envelope parameter"""
        self.global_params[param] = value
        self.global_envelope_handler.handle_route([param, value])
        _log(f"Updated global param {param}: {value}")

    def update_channel_state(self, channel, param, value):
        """Update channel MPE state"""
        if channel in self.channel_state:
            self.channel_state[channel][param] = value
            _log(f"Updated channel {channel} {param}: {value}")

    def handle_route(self, route):
        """Process an incoming route and update appropriate voice"""
        _log(f"[Voice Manager] {route}")
        
        parts = route.split('/')
        target = parts[1]
        
        if target == 'global':
            if 'envelope' in parts:
                param_type = parts[3]
                value = float(parts[-1])
                self.update_global_param(param_type, value)
        else:
            note_str, channel = target.split('.')
            required_params = {
                'bend': self.channel_state[channel]['pitch_bend'],
                'pressure': self.channel_state[channel]['pressure'],
                'timbre': self.channel_state[channel]['timbre'],
                'envelope': self.global_envelope_handler.envelope
            }
            if target not in self.voices:
                self.voices[target] = Voice(self.synth_tools, self.synth, required_params)
                self.voices[target].identifier = target
                _log(f"Created new voice for target: {target}")

            voice = self.voices[target]
            # ... (existing voice update logic)

    def cleanup_voices(self):
        """Remove completed voices"""
        for identifier, voice in list(self.voices.items()):
            if not voice.is_active():
                envelope_info = self.synth.note_info(voice.note)
                if envelope_info[0] is None:
                    _log(f"Cleaned up voice: {identifier}")
                    del self.voices[identifier]

    def cleanup(self):
        """Cleanup synthesizer"""
        if self.synth:
            self.synth.deinit()
            _log("Synthesizer cleaned up")