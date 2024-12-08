"""High-level synthesizer coordination module."""

from modules import create_waveform, create_morphed_waveform, WaveformMorph
from pool import VoicePool
from router import PathParser
from patcher import MidiHandler
import synthio
import sys
import time
from constants import (
    SAMPLE_RATE,
    AUDIO_CHANNEL_COUNT,
    LOG_SYNTH,
    LOG_LIGHT_GREEN,
    LOG_RED,
    LOG_RESET,
    SYNTHESIZER_LOG
)

def _log(message, is_error=False):
    if not SYNTHESIZER_LOG:
        return
    color = LOG_RED if is_error else LOG_LIGHT_GREEN
    if is_error:
        print("{}{} [ERROR] {}{}".format(color, LOG_SYNTH, message, LOG_RESET), file=sys.stderr)
    else:
        print("{}{} {}{}".format(color, LOG_SYNTH, message, LOG_RESET), file=sys.stderr)

class SynthState:
    """Manages synthesizer state including waveforms and parameters."""
    def __init__(self):
        self.global_waveform = None
        self.global_ring_waveform = None
        self.base_morph = None
        self.ring_morph = None
        self.current_morph_position = 0.0
        self.current_ring_morph_position = 0.0

class SynthMonitor:
    """Handles health monitoring and error recovery."""
    def __init__(self, interval=5.0):
        self.last_health_check = time.monotonic()
        self.health_check_interval = interval

    def check_health(self, synth, voice_pool):
        current_time = time.monotonic()
        if current_time - self.last_health_check >= self.health_check_interval:
            _log("Performing synthesizer health check")
            voice_pool.check_health(synth)
            if synth is None:
                _log("Synthesizer object is None", is_error=True)
                return False
            self.last_health_check = current_time
            return True
        return True

class Synthesizer:
    """Main synthesizer class coordinating MIDI handling and sound generation."""
    def __init__(self, midi_interface, audio_system=None):
        self.midi_interface = midi_interface
        self.audio_system = audio_system
        self.synth = None
        self.voice_pool = VoicePool(5)
        self.path_parser = PathParser()
        self.ready_callback = None
        
        # Initialize components
        self.state = SynthState()
        self.midi_handler = MidiHandler(self.state, self.voice_pool, self.path_parser)
        self.monitor = SynthMonitor()
        
        _log("Synthesizer initialized")

    def _handle_midi_message(self, msg):
        """Handle incoming MIDI messages."""
        try:
            if not self.monitor.check_health(self.synth, self.voice_pool):
                self._emergency_cleanup()
                return

            if not self.synth:
                _log("No synthesizer available", is_error=True)
                return

            if msg.type in self.path_parser.enabled_messages:
                self.midi_handler.handle_message(msg, self.synth)

        except Exception as e:
            _log("Error handling MIDI message: {}".format(str(e)), is_error=True)
            self._emergency_cleanup()

    def _setup_synthio(self):
        """Initialize or update synthio synthesizer based on global settings."""
        try:
            self._configure_waveforms()
            initial_envelope = self.path_parser.update_envelope()
            _log("Created initial envelope with params: {}".format(
                self.path_parser.current_envelope_params))
            
            self.synth = synthio.Synthesizer(
                sample_rate=SAMPLE_RATE,
                channel_count=AUDIO_CHANNEL_COUNT,
                waveform=self.state.global_waveform,
                envelope=initial_envelope)
            
            if self.audio_system and self.audio_system.mixer:
                self.audio_system.mixer.voice[0].play(self.synth)
                _log("Connected synthesizer to audio mixer")
                
            _log("Synthio initialization complete")
                
        except Exception as e:
            _log(f"Failed to initialize synthio: {str(e)}", is_error=True)
            raise

    def _configure_waveforms(self):
        """Configure base and ring waveforms based on path configuration."""
        # Configure base waveform
        if 'waveform' in self.path_parser.fixed_values:
            waveform_type = self.path_parser.fixed_values['waveform']
            self.state.global_waveform = create_waveform(waveform_type)
            self.state.base_morph = None
            _log(f"Created fixed base waveform: {waveform_type}")
        elif self.path_parser.waveform_sequence:
            self.state.base_morph = WaveformMorph('base', self.path_parser.waveform_sequence)
            self.state.global_waveform = self.state.base_morph.get_waveform(0)
            _log(f"Created base morph table: {'-'.join(self.path_parser.waveform_sequence)}")
        else:
            _log("No base oscillator waveform path found", is_error=True)
            raise ValueError("No base oscillator waveform path found")
            
        # Configure ring waveform
        if self.path_parser.current_ring_params['waveform']:
            ring_type = self.path_parser.current_ring_params['waveform']
            self.state.global_ring_waveform = create_waveform(ring_type)
            self.state.ring_morph = None
            _log(f"Created fixed ring waveform: {ring_type}")
        elif self.path_parser.ring_waveform_sequence:
            self.state.ring_morph = WaveformMorph('ring', self.path_parser.ring_waveform_sequence)
            self.state.global_ring_waveform = self.state.ring_morph.get_waveform(0)
            _log(f"Created ring morph table: {'-'.join(self.path_parser.ring_waveform_sequence)}")

    def _setup_midi_handlers(self):
        """Set up MIDI message handlers."""
        if self.midi_handler.subscription:
            self.midi_interface.unsubscribe(self.midi_handler.subscription)
            self.midi_handler.subscription = None
            
        _log("Setting up MIDI handlers...")
            
        message_types = [msg_type for msg_type in 
                        ('noteon', 'noteoff', 'cc', 'pitchbend', 'channelpressure')
                        if msg_type in self.path_parser.enabled_messages]
            
        if not message_types:
            raise ValueError("No MIDI message types enabled in paths")
            
        self.midi_handler.subscription = self.midi_interface.subscribe(
            self._handle_midi_message,
            message_types=message_types,
            cc_numbers=self.path_parser.enabled_ccs if 'cc' in self.path_parser.enabled_messages else None
        )
        _log(f"MIDI handlers configured for: {self.path_parser.enabled_messages}")
        
        if self.ready_callback:
            _log("Configuration complete - signaling ready")
            self.ready_callback()

    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready."""
        self.ready_callback = callback
        _log("Ready callback registered")

    def update_instrument(self, paths, config_name=None):
        """Update instrument configuration."""
        _log("Updating instrument configuration...")
        _log("----------------------------------------")
        
        try:
            if self.voice_pool:
                self.voice_pool.release_all(self.synth)
                _log("Released all voices during reconfiguration")
            
            self.path_parser.parse_paths(paths, config_name)
            self._setup_synthio()
            self._setup_midi_handlers()
            
            _log("----------------------------------------")
            _log("Instrument update complete")
            
        except Exception as e:
            _log(f"Failed to update instrument: {str(e)}", is_error=True)
            self._emergency_cleanup()
            raise

    def _emergency_cleanup(self):
        """Perform emergency cleanup in case of critical errors."""
        _log("Performing emergency cleanup", is_error=True)
        try:
            if self.voice_pool and self.synth:
                self.voice_pool.release_all(self.synth)
                _log("Emergency released all voices")
            
            if self.midi_handler.subscription:
                try:
                    self.midi_interface.unsubscribe(self.midi_handler.subscription)
                except Exception as e:
                    _log(f"Error unsubscribing MIDI: {str(e)}", is_error=True)
                self.midi_handler.subscription = None
                
            if self.synth:
                try:
                    self.synth.deinit()
                except Exception as e:
                    _log(f"Error deinitializing synth: {str(e)}", is_error=True)
            self.synth = None
                
            try:
                self._setup_synthio()
                self._setup_midi_handlers()
                _log("Successfully re-initialized synthesizer after emergency")
            except Exception as e:
                _log(f"Failed to re-initialize synth: {str(e)}", is_error=True)
                
            _log("Emergency cleanup complete")
            
        except Exception as e:
            _log(f"Error during emergency cleanup: {str(e)}", is_error=True)

    def cleanup(self):
        """Clean up resources."""
        _log("Cleaning up synthesizer...")
        try:
            if self.voice_pool and self.synth:
                self.voice_pool.release_all(self.synth)
                _log("Released all voices during cleanup")
            
            if self.midi_handler.subscription:
                self.midi_interface.unsubscribe(self.midi_handler.subscription)
                self.midi_handler.subscription = None
                _log("Unsubscribed from MIDI messages")
                
            if self.synth:
                self.synth.deinit()
                self.synth = None
                _log("Deinitialized synthesizer")
                
            _log("Cleanup complete")
            
        except Exception as e:
            _log(f"Error during cleanup: {str(e)}", is_error=True)
            self._emergency_cleanup()
