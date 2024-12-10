"""High-level synthesizer coordination module."""

import synthio
import sys
import time
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from logging import log, TAG_SYNTH
from voices import VoicePool
from router import PathParser
from patcher import MidiHandler
from interfaces import SynthioInterfaces, WaveformMorph

class SynthState:
    """Manages synthesizer state including waveforms and parameters."""
    def __init__(self):
        # Waveform objects (not values - these are the actual waveform buffers)
        self.global_waveform = None
        self.global_ring_waveform = None
        self.base_morph = None
        self.ring_morph = None
        
        # All mutable values in one place
        self.set_values = {}

    def update_value(self, name, value):
        """Update any value in state. Creates new value if it doesn't exist."""
        self.set_values[name] = value

    def get_value(self, name):
        """Get any value from state. Returns None if value doesn't exist."""
        return self.set_values.get(name)

class SynthMonitor:
    """Handles health monitoring and error recovery."""
    def __init__(self, interval=5.0):
        self.last_health_check = time.monotonic()
        self.health_check_interval = interval

    def check_health(self, synth, voice_pool):
        current_time = time.monotonic()
        if current_time - self.last_health_check >= self.health_check_interval:
            log(TAG_SYNTH, "Performing synthesizer health check")
            voice_pool.check_health()
            if synth is None:
                log(TAG_SYNTH, "Synthesizer object is None", is_error=True)
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
        self.midi_handler.synthesizer = self  # Add this line to set the reference
        self.monitor = SynthMonitor()
        
        log(TAG_SYNTH, "Synthesizer initialized")

    def _handle_midi_message(self, msg):
        """Handle incoming MIDI messages."""
        try:
            if not self.monitor.check_health(self.synth, self.voice_pool):
                self._emergency_cleanup()
                return

            if not self.synth:
                log(TAG_SYNTH, "No synthesizer available", is_error=True)
                return

            if msg.type in self.path_parser.enabled_messages:
                self.midi_handler.handle_message(msg, self.synth)

        except Exception as e:
            log(TAG_SYNTH, f"Error handling MIDI message: {str(e)}", is_error=True)
            self._emergency_cleanup()

    def update_global_envelope(self, param_name, value):
        """Update global envelope with new parameter."""
        self.state.update_value(param_name, value)
        envelope = self._create_envelope()  # Already handles getting all params
        if envelope:
            self.synth.envelope = envelope
            log(TAG_SYNTH, f"Updated global envelope {param_name}={value}")

    def update_global_filter(self, param_name, value):
        """Update global filter with new parameter."""
        filter_param = f'filter_{param_name}'
        self.state.update_value(filter_param, value)
        # Update filter on all voices
        for voice in self.voice_pool.voices:
            if voice.is_active():
                self._update_voice_filter(voice)
        log(TAG_SYNTH, f"Updated global filter {param_name}={value}")

    def update_global_waveform(self, waveform_type):
        """Update global waveform."""
        self.state.update_value('waveform', waveform_type)
        self.state.global_waveform = SynthioInterfaces.create_waveform(waveform_type)
        self.state.base_morph = None
        log(TAG_SYNTH, f"Updated global waveform: {waveform_type}")

    def update_morph_position(self, position, midi_value):
        """Update waveform morph position."""
        # Store both MIDI value for lookup and normalized position
        self.state.update_value('morph_position', midi_value)
        self.state.update_value('morph', position)
        
        # Update all active voices
        if self.state.base_morph:
            for voice in self.voice_pool.voices:
                if voice.is_active():
                    self._update_voice_morph(voice, midi_value)
        log(TAG_SYNTH, f"Updated morph position: {position} (MIDI: {midi_value})")

    def update_ring_modulation(self, param_name, value):
        """Update ring modulation parameters."""
        self.state.update_value(param_name, value)
        
        # Update all active voices
        for voice in self.voice_pool.voices:
            if voice.is_active():
                self._update_voice_ring_mod(voice, param_name, value)
        log(TAG_SYNTH, f"Updated ring modulation {param_name}={value}")

    def update_voice_parameter(self, param_name, value, channel):
        """Update parameter on voice by channel."""
        voice = self.voice_pool.get_voice_by_channel(channel)
        if voice and voice.is_active():
            self._update_voice_param(voice, param_name, value)
            log(TAG_SYNTH, f"Updated voice {voice.get_address()} {param_name}={value}")

    def _update_voice_param(self, voice, param_name, value):
        """Internal method to update voice parameter."""
        if voice.active_note and hasattr(voice.active_note, param_name):
            try:
                setattr(voice.active_note, param_name, value)
                log(TAG_SYNTH, f"Updated voice parameter {param_name} = {value}")
            except Exception as e:
                log(TAG_SYNTH, f"Failed to update voice parameter {param_name}: {str(e)}", is_error=True)

    def _update_voice_filter(self, voice):
        """Internal method to update voice filter."""
        if voice.active_note:
            try:
                filter = SynthioInterfaces.create_filter(
                    self.synth,
                    self.path_parser.filter_type,
                    self.state.get_value('filter_frequency'),
                    self.state.get_value('filter_resonance')
                )
                if filter:
                    voice.active_note.filter = filter
            except Exception as e:
                log(TAG_SYNTH, f"Failed to update voice filter: {str(e)}", is_error=True)

    def _update_voice_morph(self, voice, midi_value):
        """Internal method to update voice waveform morph."""
        if voice.active_note and self.state.base_morph:
            try:
                voice.active_note.waveform = self.state.base_morph.get_waveform(midi_value)
            except Exception as e:
                log(TAG_SYNTH, f"Failed to update voice morph: {str(e)}", is_error=True)

    def _update_voice_ring_mod(self, voice, param_name, value):
        """Internal method to update voice ring modulation."""
        if voice.active_note:
            try:
                if param_name == 'ring_frequency':
                    voice.active_note.ring_frequency = value
                elif param_name == 'ring_bend':
                    voice.active_note.ring_bend = value
                elif param_name == 'ring_morph':
                    if self.state.ring_morph:
                        voice.active_note.ring_waveform = self.state.ring_morph.get_waveform(value)
            except Exception as e:
                log(TAG_SYNTH, f"Failed to update voice ring mod: {str(e)}", is_error=True)

    def _setup_synthio(self):
        """Initialize or update synthio synthesizer based on global settings."""
        try:
            self._configure_waveforms()
            initial_envelope = self._create_envelope()
            
            # Get envelope params for logging
            envelope_params = {
                'attack_time': self.state.get_value('attack_time'),
                'decay_time': self.state.get_value('decay_time'),
                'release_time': self.state.get_value('release_time'),
                'attack_level': self.state.get_value('attack_level'),
                'sustain_level': self.state.get_value('sustain_level')
            }
            # Only log non-None parameters
            actual_params = {k: v for k, v in envelope_params.items() if v is not None}
            if actual_params:
                log(TAG_SYNTH, f"Creating initial envelope with params: {actual_params}")
            else:
                log(TAG_SYNTH, "Creating initial envelope with default parameters")
            
            # Use interface to create synthesizer
            self.synth = SynthioInterfaces.create_synthesizer(
                sample_rate=SAMPLE_RATE,
                channel_count=AUDIO_CHANNEL_COUNT,
                waveform=self.state.global_waveform,
                envelope=initial_envelope
            )
            
            if self.audio_system and self.audio_system.mixer:
                self.audio_system.mixer.voice[0].play(self.synth)
                log(TAG_SYNTH, "Connected synthesizer to audio mixer")
                
            log(TAG_SYNTH, "Synthio initialization complete")
                
        except Exception as e:
            log(TAG_SYNTH, f"Failed to initialize synthio: {str(e)}", is_error=True)
            raise

    def _create_envelope(self):
        """Create a new envelope with current parameters."""
        if not self.path_parser.has_envelope_paths:
            log(TAG_SYNTH, "No envelope paths found - using instant on/off envelope")
            return None
            
        try:
            # Only include parameters that exist in state
            envelope_params = {}
            for param in ['attack_time', 'decay_time', 'release_time', 'attack_level', 'sustain_level']:
                value = self.state.get_value(param)
                if value is not None:
                    # Ensure parameter is float
                    try:
                        envelope_params[param] = float(value)
                    except (TypeError, ValueError) as e:
                        log(TAG_SYNTH, f"Invalid envelope parameter {param}: {value} - {str(e)}", is_error=True)
                        continue
            
            envelope = synthio.Envelope(**envelope_params)
            return envelope
        except Exception as e:
            log(TAG_SYNTH, f"Error creating envelope: {str(e)}", is_error=True)
            return None

    def _configure_waveforms(self):
        """Configure base and ring waveforms based on path configuration."""
        # Store values from paths in state
        for name, value in self.path_parser.set_values.items():
            self.state.update_value(name, value)
            
        # Configure base waveform
        if 'waveform' in self.path_parser.set_values:
            waveform_type = self.state.get_value('waveform')
            self.state.global_waveform = SynthioInterfaces.create_waveform(waveform_type)
            self.state.base_morph = None
            log(TAG_SYNTH, f"Created base waveform: {waveform_type}")
        elif self.path_parser.waveform_sequence:
            self.state.base_morph = WaveformMorph('base', self.path_parser.waveform_sequence)
            self.state.global_waveform = self.state.base_morph.get_waveform(0)
            log(TAG_SYNTH, f"Created base morph table: {'-'.join(self.path_parser.waveform_sequence)}")
        else:
            log(TAG_SYNTH, "No base oscillator waveform path found", is_error=True)
            raise ValueError("No base oscillator waveform path found")
            
        # Configure ring waveform if ring mod is enabled
        if self.path_parser.has_ring_mod:
            if 'ring_waveform' in self.path_parser.set_values:
                ring_type = self.state.get_value('ring_waveform')
                self.state.global_ring_waveform = SynthioInterfaces.create_waveform(ring_type)
                self.state.ring_morph = None
                log(TAG_SYNTH, f"Created ring waveform: {ring_type}")
            elif self.path_parser.ring_waveform_sequence:
                self.state.ring_morph = WaveformMorph('ring', self.path_parser.ring_waveform_sequence)
                self.state.global_ring_waveform = self.state.ring_morph.get_waveform(0)
                log(TAG_SYNTH, f"Created ring morph table: {'-'.join(self.path_parser.ring_waveform_sequence)}")

    def _setup_midi_handlers(self):
        """Set up MIDI message handlers."""
        if self.midi_handler.subscription:
            self.midi_interface.unsubscribe(self.midi_handler.subscription)
            self.midi_handler.subscription = None
            
        log(TAG_SYNTH, "Setting up MIDI handlers...")
            
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
        log(TAG_SYNTH, f"MIDI handlers configured for: {self.path_parser.enabled_messages}")
        
        if self.ready_callback:
            log(TAG_SYNTH, "Configuration complete - signaling ready")
            self.ready_callback()

    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready."""
        self.ready_callback = callback
        log(TAG_SYNTH, "Ready callback registered")

    def update_instrument(self, paths, config_name=None):
        """Update instrument configuration."""
        log(TAG_SYNTH, "Updating instrument configuration...")
        log(TAG_SYNTH, "----------------------------------------")
        
        try:
            if self.voice_pool:
                self.voice_pool.release_all()
                log(TAG_SYNTH, "Released all voices during reconfiguration")
            
            self.path_parser.parse_paths(paths, config_name)
            self._setup_synthio()
            self._setup_midi_handlers()
            
            log(TAG_SYNTH, "----------------------------------------")
            log(TAG_SYNTH, "Instrument update complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Failed to update instrument: {str(e)}", is_error=True)
            self._emergency_cleanup()
            raise

    def _emergency_cleanup(self):
        """Perform emergency cleanup in case of critical errors."""
        log(TAG_SYNTH, "Performing emergency cleanup", is_error=True)
        try:
            if self.voice_pool:
                self.voice_pool.release_all()
                log(TAG_SYNTH, "Emergency released all voices")
            
            if self.midi_handler.subscription:
                try:
                    self.midi_interface.unsubscribe(self.midi_handler.subscription)
                except Exception as e:
                    log(TAG_SYNTH, f"Error unsubscribing MIDI: {str(e)}", is_error=True)
                self.midi_handler.subscription = None
                
            if self.synth:
                try:
                    self.synth.deinit()
                except Exception as e:
                    log(TAG_SYNTH, f"Error deinitializing synth: {str(e)}", is_error=True)
            self.synth = None
                
            try:
                self._setup_synthio()
                self._setup_midi_handlers()
                log(TAG_SYNTH, "Successfully re-initialized synthesizer after emergency")
            except Exception as e:
                log(TAG_SYNTH, f"Failed to re-initialize synth: {str(e)}", is_error=True)
                
            log(TAG_SYNTH, "Emergency cleanup complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Error during emergency cleanup: {str(e)}", is_error=True)

    def cleanup(self):
        """Clean up resources."""
        log(TAG_SYNTH, "Cleaning up synthesizer...")
        try:
            if self.voice_pool:
                self.voice_pool.release_all()
                log(TAG_SYNTH, "Released all voices during cleanup")
            
            if self.midi_handler.subscription:
                self.midi_interface.unsubscribe(self.midi_handler.subscription)
                self.midi_handler.subscription = None
                log(TAG_SYNTH, "Unsubscribed from MIDI messages")
                
            if self.synth:
                self.synth.deinit()
                self.synth = None
                log(TAG_SYNTH, "Deinitialized synthesizer")
                
            log(TAG_SYNTH, "Cleanup complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Error during cleanup: {str(e)}", is_error=True)
            self._emergency_cleanup()

    def handle_note_on(self, note_number, channel):
        """Handle note-on by coordinating between voice pool and synthio."""
        # Get voice from voice pool
        voice = self.voice_pool.press_note(note_number, channel)
        if not voice:
            return
            
        # Build note parameters
        params = {}
        
        # Convert note number to frequency
        params['frequency'] = synthio.midi_to_hz(note_number)
        
        # Get filter parameters if filter type is specified
        if self.path_parser.filter_type:
            filter_freq = self.state.get_value('filter_frequency') or 0
            filter_res = self.state.get_value('filter_resonance') or 0
            
            try:
                filter = SynthioInterfaces.create_filter(
                    self.synth,
                    self.path_parser.filter_type,
                    filter_freq,
                    filter_res
                )
                if filter:
                    params['filter'] = filter
            except Exception as e:
                log(TAG_SYNTH, f"Failed to create filter: {str(e)}", is_error=True)
        
        # Get appropriate waveform
        if 'waveform' in self.path_parser.set_values:
            params['waveform'] = self.state.global_waveform
        elif self.state.base_morph:
            morph_pos = self.state.get_value('morph_position') or 0
            params['waveform'] = self.state.base_morph.get_waveform(morph_pos)
                
        # Get ring waveform if needed
        if self.path_parser.has_ring_mod:
            # Add ring mod parameters
            ring_freq = self.state.get_value('ring_frequency')
            ring_bend = self.state.get_value('ring_bend')
            if ring_freq is not None:
                params['ring_frequency'] = ring_freq
            if ring_bend is not None:
                params['ring_bend'] = ring_bend
                
            # Get ring waveform
            if 'ring_waveform' in self.path_parser.set_values:
                params['ring_waveform'] = self.state.global_ring_waveform
            elif self.state.ring_morph:
                morph_pos = self.state.get_value('ring_morph_position') or 0
                params['ring_waveform'] = self.state.ring_morph.get_waveform(morph_pos)
            
        # Create synthio note
        try:
            note = SynthioInterfaces.create_note(**params)
            self.synth.press(note)
            voice.active_note = note
            log(TAG_SYNTH, f"Created note {note_number} on channel {channel} with params: {params}")
        except Exception as e:
            log(TAG_SYNTH, f"Failed to create note: {str(e)}", is_error=True)
            self.voice_pool.release_note(note_number)

    def handle_note_off(self, note_number, channel):
        """Handle note-off by coordinating between voice pool and synthio."""
        # First try to find voice by exact note and channel
        voice = self.voice_pool.get_voice_by_channel(channel)
        if voice and voice.note_number == note_number:
            self.synth.release(voice.active_note)
            self.voice_pool.release_note(note_number)
            return
            
        # Fallback to just note number if channel match fails
        voice = self.voice_pool.release_note(note_number)
        if voice and voice.active_note:
            self.synth.release(voice.active_note)
            voice.active_note = None
