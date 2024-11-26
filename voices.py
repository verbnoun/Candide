"""
voices.py - Voice and Note Management

Manages voice objects containing synthio notes.
Uses synthesizer.py for all value calculations.
Handles all possible routes based on config path structure.
"""
import time
import sys
import synthio
import audiobusio
from synthesizer import Synthesizer
from constants import VOICES_DEBUG, SAMPLE_RATE, AUDIO_CHANNEL_COUNT, I2S_BIT_CLOCK, I2S_WORD_SELECT, I2S_DATA

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

    if isinstance(message, str) and '/' in message:  # Route format
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

class BootBeep:
    """Simple boot beep that can run independently"""
    def __init__(self, bit_clock=I2S_BIT_CLOCK, word_select=I2S_WORD_SELECT, data=I2S_DATA):
        _log("Initializing BootBeep", "BOOTBEEP")
        self.bit_clock = bit_clock
        self.word_select = word_select
        self.data = data
        self.audio_out = None
        
    def play(self):
        """Play a boot beep"""
        try:
            # Setup I2S
            _log("Setting up I2S output...", "BOOTBEEP")
            self.audio_out = audiobusio.I2SOut(
                bit_clock=self.bit_clock,
                word_select=self.word_select,
                data=self.data
            )
            _log("I2S initialized successfully", "BOOTBEEP")
            
            # Create synth
            _log("Creating synthesizer...", "BOOTBEEP")
            synth = synthio.Synthesizer(sample_rate=SAMPLE_RATE)
            self.audio_out.play(synth)
            _log("Synthesizer playing", "BOOTBEEP")
            
            # Play gentle beep
            _log("Playing boot sound...", "BOOTBEEP")
            synth.press(64)  # A5 note
            time.sleep(0.10)  # Duration
            
            _log("Note released...", "BOOTBEEP")
            synth.release(81)
            time.sleep(0.05)  # Let release finish
            
            _log("Audio playback completed", "BOOTBEEP")
            
            # Cleanup
            _log("Starting cleanup...", "BOOTBEEP")
            synth.deinit()
            _log("Synthesizer deinitialized", "BOOTBEEP")
            self.audio_out.deinit()
            _log("I2S deinitialized", "BOOTBEEP")
            self.audio_out = None
            _log("Cleanup complete", "BOOTBEEP")
            
        except Exception as e:
            _log(f"[ERROR] BootBeep failed: {str(e)}", "BOOTBEEP")
            if self.audio_out:
                _log("Emergency cleanup of I2S...", "BOOTBEEP")
                try:
                    self.audio_out.deinit()
                    _log("Emergency cleanup successful", "BOOTBEEP")
                except:
                    _log("[ERROR] Emergency cleanup failed", "BOOTBEEP")
                self.audio_out = None
            raise e

class Voice:
    """
    Represents a single voice containing a synthio note.
    Handles all possible route parameter updates.
    """
    def __init__(self, synth_tools):
        self.note = None  
        self.identifier = None  # note.channel format
        self.start_time = time.monotonic()
        self.synth_tools = synth_tools
        self.active = False
        
        # Track current parameter values for filter reconstruction
        self.filter_freq = None
        self.filter_res = None
        
        # Track envelope parameters
        self.envelope_params = {}
        
        # Track LFO states
        self.oscillator_lfo = None
        self.filter_lfo = None
        
        _log("Voice instance created")

    def start(self, identifier, frequency):
        """Initialize and configure a new synthio note"""
        self.identifier = identifier
        self.start_time = time.monotonic()
        self.active = True
        
        # Create basic note - other parameters will be set by routes
        self.note = synthio.Note(
            frequency=frequency,
            amplitude=0.0  # Start silent until routes configure
        )
        _log(f"Started voice: identifier={identifier}, frequency={frequency}")

    def update(self, route):
        """Update note parameters based on route"""
        _log(route)  # Log incoming route
        
        parts = route.split('/')
        stage = parts[0]     # oscillator/filter/amplifier
        params = parts[2:]   # All parameter parts
        value = float(parts[-1])

        if stage == 'oscillator':
            if 'ring' in parts[1:]:
                self._handle_ring_mod_route(params, value)
            else:
                self._handle_oscillator_route(params, value)
                
        elif stage == 'filter':
            self._handle_filter_route(params, value)
                
        elif stage == 'amplifier':
            self._handle_amplifier_route(params, value)

    def _handle_oscillator_route(self, params, value):
        """Handle main oscillator parameters"""
        param = params[0]
        
        _log({
            'identifier': self.identifier,
            'type': f'oscillator_{param}',
            'value': value
        })
        
        if param == 'frequency':
            self.note.frequency = value
            
        elif param == 'bend':
            self.note.bend = value
            
        elif param == 'waveform':
            self.note.waveform = self.synth_tools.create_wave(value)
            
        elif param == 'envelope':
            if 'frequency' in params:
                # Handle frequency envelope parameters
                env_param = params[2]  # attack_time, attack_level etc
                self.envelope_params[f'freq_{env_param}'] = value
                self.note.envelope = self.synth_tools.calculate_envelope(
                    self.envelope_params, 'frequency')
                    
        elif param == 'lfo':
            if params[1] == 'rate':
                lfo = self.synth_tools.create_lfo(value, self.oscillator_lfo.scale if self.oscillator_lfo else 0.5)
                self.oscillator_lfo = lfo
                self.note.bend = lfo
            elif params[1] == 'depth':
                lfo = self.synth_tools.create_lfo(
                    self.oscillator_lfo.rate if self.oscillator_lfo else 5, value)
                self.oscillator_lfo = lfo
                self.note.bend = lfo
                
        elif param == 'timbre':
            # Use CC74 for timbre control
            self.note.ring_frequency = self.synth_tools.calculate_timbre(value)

    def _handle_ring_mod_route(self, params, value):
        """Handle ring modulation parameters"""
        param = params[0]
        
        _log({
            'identifier': self.identifier,
            'type': f'ring_mod_{param}',
            'value': value
        })
        
        if param == 'frequency':
            self.note.ring_frequency = value
            
        elif param == 'waveform':
            self.note.ring_waveform = self.synth_tools.create_wave(value)
            
        elif param == 'bend':
            self.note.ring_bend = value
            
        elif param == 'envelope':
            if 'frequency' in params:
                env_param = params[2]
                self.envelope_params[f'ring_{env_param}'] = value
                # Let synthesizer calculate appropriate envelope
                env = self.synth_tools.calculate_envelope(
                    self.envelope_params, 'ring')
                self.note.envelope = env

    def _handle_filter_route(self, params, value):
        """Handle all filter parameters"""
        param = params[0]
        
        _log({
            'identifier': self.identifier,
            'type': f'filter_{param}',
            'value': value
        })
        
        if param == 'frequency':
            self.filter_freq = value
            if self.filter_res is None:
                self.filter_res = 0.7  # Default Q if not set
            self.note.filter = self.synth_tools.calculate_filter(
                self.filter_freq, self.filter_res)
                
        elif param == 'resonance':
            self.filter_res = value
            if self.filter_freq is None:
                self.filter_freq = 1000  # Default freq if not set
            self.note.filter = self.synth_tools.calculate_filter(
                self.filter_freq, self.filter_res)
                
        elif param == 'envelope':
            env_param = params[2]  # attack_time, decay_time, etc
            self.envelope_params[f'filter_{env_param}'] = value
            # Create modulated filter based on envelope
            self.note.filter = self.synth_tools.calculate_filter_envelope(
                self.envelope_params)
                
        elif param == 'lfo':
            if params[1] == 'rate':
                lfo = self.synth_tools.create_lfo(value, 
                    self.filter_lfo.scale if self.filter_lfo else 0.3)
                self.filter_lfo = lfo
                # Apply LFO to filter frequency
                self.note.filter = self.synth_tools.calculate_filter_lfo(
                    self.filter_freq, self.filter_res, lfo)
            elif params[1] == 'depth':
                lfo = self.synth_tools.create_lfo(
                    self.filter_lfo.rate if self.filter_lfo else 2, value)
                self.filter_lfo = lfo
                self.note.filter = self.synth_tools.calculate_filter_lfo(
                    self.filter_freq, self.filter_res, lfo)

    def _handle_amplifier_route(self, params, value):
        """Handle all amplifier parameters"""
        param = params[0]
        
        _log({
            'identifier': self.identifier,
            'type': f'amplifier_{param}',
            'value': value
        })
        
        if param == 'gain':
            self.note.amplitude = value
            
        elif param == 'pressure':
            # Update amplitude based on pressure
            self.note.amplitude = self.synth_tools.calculate_pressure_amplitude(
                value, self.note.amplitude)
                
        elif param == 'envelope':
            subtype = params[1]  # amplitude, filter, etc
            env_param = params[2]  # attack_time, decay_level, etc
            self.envelope_params[f'{subtype}_{env_param}'] = value
            self.note.envelope = self.synth_tools.calculate_envelope(
                self.envelope_params, subtype)
                
        elif param == 'expression':
            # Global/channel expression control
            self.note.amplitude = self.synth_tools.calculate_expression(
                value, self.note.amplitude)

    def release(self):
        """Begin release phase of note"""
        self.active = False
        _log(f"Released voice: identifier={self.identifier}")
        
    def is_active(self):
        """Check if voice is currently active"""
        return self.active

class VoiceManager:
    """
    Manages collection of voices and their lifecycle.
    Routes parameter updates to appropriate voices.
    """
    def __init__(self):
        self.voices = {}  # identifier -> Voice mapping
        self.synth_tools = Synthesizer()  # Calculation tools
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        self.max_voices = self.synth.max_polyphony
        _log("Voice manager initialized")

    def get_synth(self):
        """Get the synthesizer instance for audio system"""
        return self.synth

    def handle_route(self, route):
        """Process an incoming route and update appropriate voice"""
        _log(route)  # Log incoming route
        
        parts = route.split('/')
        target = parts[1]  # global or note.channel
        
        # Handle global routes
        if target == 'global':
            _log(f"Processing global route: {route}")
            for voice in self.voices.values():
                if voice.is_active():
                    voice.update(route)
            return
            
        # Handle per-note routes
        if target not in self.voices and parts[0] == 'oscillator' and parts[2] == 'frequency':
            # Start new note
            voice = Voice(self.synth_tools)
            voice.start(target, float(parts[-1]))
            self.voices[target] = voice
            self.synth.press(voice.note)
            _log(f"Created new voice for target: {target}")
            
        elif target in self.voices:
            voice = self.voices[target]
            if voice.is_active():
                voice.update(route)
                
        # Handle release
        if len(parts) >= 2 and parts[-2] == 'release':
            if target in self.voices:
                voice = self.voices[target]
                voice.release()
                self.synth.release(voice.note)
                _log(f"Released voice: {target}")

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
