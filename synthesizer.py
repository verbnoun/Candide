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

class ValueStore:
    """Centralized store for all synthesizer values."""
    def __init__(self):
        self.values = {}
        self.previous = {}
        
    def store(self, name, value):
        """Store a value and keep track of previous."""
        if name in self.values:
            self.previous[name] = self.values[name]
        self.values[name] = value
        log(TAG_SYNTH, f"Stored value {name}={value}")
        
    def get(self, name, default=None):
        """Get a stored value."""
        return self.values.get(name, default)
        
    def get_previous(self, name, default=None):
        """Get previous value if it exists."""
        return self.previous.get(name, default)
        
    def clear(self):
        """Clear all stored values."""
        self.values.clear()
        self.previous.clear()

class SynthState:
    """Manages synthesizer state including waveforms and parameters."""
    def __init__(self):
        # Waveform objects (not values - these are the actual waveform buffers)
        self.global_waveform = None
        self.global_ring_waveform = None
        self.base_morph = None
        self.ring_morph = None

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
        self.store = ValueStore()
        self.midi_handler = MidiHandler(self.state, self.path_parser)
        self.midi_handler.synthesizer = self
        self.monitor = SynthMonitor()
        
        log(TAG_SYNTH, "Synthesizer initialized")

    def _initialize_set_values(self):
        """Handle all set values from path parser during initialization."""
        try:
            success = True
            for name, value in self.path_parser.set_values.items():
                try:
                    self.store_value(name, value, use_now=False)
                    log(TAG_SYNTH, f"Successfully stored initial value {name}={value}")
                except Exception as e:
                    log(TAG_SYNTH, f"Failed to store initial value {name}: {str(e)}", is_error=True)
                    success = False
            return success
        except Exception as e:
            log(TAG_SYNTH, f"Error in _initialize_set_values: {str(e)}", is_error=True)
            return False

    # === Value Store Management ===
    
    def store_value(self, name, value, use_now=True):
        """Store a value and optionally use it immediately."""
        self.store.store(name, value)
        if use_now:
            self._handle_value_update(name, value)
    
    def _handle_value_update(self, name, value):
        """Handle a value update based on parameter type."""
        try:
            if name.startswith('filter_'):
                self.update_global_filter(name, value)
            elif name.startswith('math_'):
                self._update_math(name, value)
            elif name.startswith('lfo_'):
                self._update_lfo(name, value)
            elif name in ('attack_time', 'decay_time', 'release_time', 
                         'attack_level', 'sustain_level'):
                self.update_global_envelope(name, value)
            elif name.startswith('ring_'):
                self.update_ring_modulation(name, value)
            elif name == 'morph':
                self.update_morph_position(value, self.store.get('morph_position', 0))
            elif name == 'waveform':
                self.update_global_waveform(value)
            else:
                log(TAG_SYNTH, f"No immediate handler for {name}={value}")
        except Exception as e:
            log(TAG_SYNTH, f"Error handling value update for {name}: {str(e)}", is_error=True)

    # === Math Operations ===
    
    def _update_math(self, name, value):
        """Handle math operation updates."""
        log(TAG_SYNTH, f"Math update: {name}={value}")
        # TODO: Implement math operations

    # === LFO Operations ===
    
    def _update_lfo(self, name, value):
        """Handle LFO parameter updates."""
        log(TAG_SYNTH, f"LFO update: {name}={value}")
        # TODO: Implement LFO operations

    # === Existing Action Methods ===

    def update_global_envelope(self, param_name, value):
        """Update global envelope with new parameter."""
        self.store.store(param_name, value)
        envelope = self._create_envelope()
        if envelope:
            self.synth.envelope = envelope
            log(TAG_SYNTH, f"Updated global envelope {param_name}={value}")

    def update_global_filter(self, param_name, value):
        """Update global filter with new parameter."""
        # Store the incoming parameter
        self.store.store(param_name, value)
        
        # Check store for all required filter parameters
        filter_freq = self.store.get('filter_frequency')
        filter_res = self.store.get('filter_resonance')
        filter_type = self.path_parser.filter_type
        
        # All three parameters are required for a filter
        if filter_freq is not None and filter_res is not None and filter_type:
            def update_voice(voice):
                if voice.active_note:
                    try:
                        filter = SynthioInterfaces.create_filter(
                            self.synth,
                            filter_type,
                            filter_freq,
                            filter_res
                        )
                        if filter:
                            voice.active_note.filter = filter
                    except Exception as e:
                        log(TAG_SYNTH, f"Failed to update voice filter: {str(e)}", is_error=True)
                        
            self.voice_pool.for_each_active_voice(update_voice)
            log(TAG_SYNTH, f"Updated global filter freq={filter_freq} res={filter_res} type={filter_type}")
        else:
            log(TAG_SYNTH, "Missing required filter parameters", is_error=True)

    def update_global_waveform(self, waveform_type):
        """Update global waveform."""
        # Store the incoming parameter
        self.store.store('waveform', waveform_type)
        
        try:
            # Create new waveform
            new_waveform = SynthioInterfaces.create_waveform(waveform_type)
            if new_waveform:
                self.state.global_waveform = new_waveform
                self.state.base_morph = None
                
                # Check store for morph position
                morph_pos = self.store.get('morph_position')
                if morph_pos is not None:
                    self.voice_pool.for_each_active_voice(
                        lambda v: self._update_voice_morph(v, morph_pos))
                
                log(TAG_SYNTH, f"Updated global waveform: {waveform_type}")
        except Exception as e:
            log(TAG_SYNTH, f"Failed to update global waveform: {str(e)}", is_error=True)

    def update_morph_position(self, position, midi_value):
        """Update waveform morph position."""
        # Store both position and MIDI value
        self.store.store('morph_position', midi_value)
        self.store.store('morph', position)
        
        # Check if we have a base morph to work with
        if self.state.base_morph:
            # Check store for ring morph if available
            ring_morph = self.store.get('ring_morph')
            
            def update_voice(voice):
                if voice.active_note:
                    try:
                        # Update base waveform morph
                        voice.active_note.waveform = self.state.base_morph.get_waveform(midi_value)
                        
                        # If ring morph exists and we have a value, update it too
                        if ring_morph is not None and self.state.ring_morph:
                            voice.active_note.ring_waveform = self.state.ring_morph.get_waveform(ring_morph)
                    except Exception as e:
                        log(TAG_SYNTH, f"Failed to update voice morph: {str(e)}", is_error=True)
            
            self.voice_pool.for_each_active_voice(update_voice)
            log(TAG_SYNTH, f"Updated morph position: {position} (MIDI: {midi_value})")

    def update_ring_modulation(self, param_name, value):
        """Update ring modulation parameters."""
        # Store the incoming parameter
        self.store.store(param_name, value)
        
        # Check store for all ring mod parameters
        ring_freq = self.store.get('ring_frequency')
        ring_bend = self.store.get('ring_bend')
        ring_morph = self.store.get('ring_morph')
        
        def update_voice(voice):
            if voice.active_note:
                try:
                    # Apply any available parameters
                    if ring_freq is not None:
                        voice.active_note.ring_frequency = ring_freq
                    if ring_bend is not None:
                        voice.active_note.ring_bend = ring_bend
                    if ring_morph is not None and self.state.ring_morph:
                        voice.active_note.ring_waveform = self.state.ring_morph.get_waveform(ring_morph)
                except Exception as e:
                    log(TAG_SYNTH, f"Failed to update voice ring mod: {str(e)}", is_error=True)
        
        if self.path_parser.has_ring_mod:
            self.voice_pool.for_each_active_voice(update_voice)
            log(TAG_SYNTH, f"Updated ring modulation {param_name}={value}")

    def update_voice_parameter(self, param_name, value, channel):
        """Update parameter on voice by channel."""
        voice = self.voice_pool.get_voice_by_channel(channel)
        if voice and voice.is_active():
            self._update_voice_param(param_name, value, voice)
            log(TAG_SYNTH, f"Updated voice {voice.get_address()} {param_name}={value}")

    # === Voice Management Methods ===

    def press(self, note_number, channel, value):
        """Press note with router-provided value."""
        voice = self.voice_pool.press_note(note_number, channel)
        if not voice:
            return
            
        params = self._build_note_params(value)
        
        try:
            note = SynthioInterfaces.create_note(**params)
            self.synth.press(note)
            voice.active_note = note
            log(TAG_SYNTH, f"Created note {note_number} on channel {channel}")
        except Exception as e:
            log(TAG_SYNTH, f"Failed to create note: {str(e)}", is_error=True)
            self.voice_pool.release_note(note_number)

    def release(self, note_number, channel):
        """Release note."""
        voice = self.voice_pool.get_voice_by_channel(channel)
        if voice and voice.note_number == note_number:
            self.synth.release(voice.active_note)
            self.voice_pool.release_note(note_number)
            return
            
        voice = self.voice_pool.release_note(note_number)
        if voice and voice.active_note:
            self.synth.release(voice.active_note)
            voice.active_note = None

    # === Internal Helper Methods ===

    def _update_voice_param(self, param_name, value, voice):
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
                    self.store.get('filter_frequency'),
                    self.store.get('filter_resonance')
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

    def _build_note_params(self, value):
        """Build note parameters from stored values and value."""
        params = {}
        params['frequency'] = synthio.midi_to_hz(value)
        
        if self.path_parser.filter_type:
            filter_freq = self.store.get('filter_frequency', 0)
            filter_res = self.store.get('filter_resonance', 0)
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
        
        waveform = self.store.get('waveform')
        if waveform:
            params['waveform'] = self.state.global_waveform
        elif self.state.base_morph:
            morph_pos = self.store.get('morph_position', 0)
            params['waveform'] = self.state.base_morph.get_waveform(morph_pos)
                
        if self.path_parser.has_ring_mod:
            ring_freq = self.store.get('ring_frequency')
            ring_bend = self.store.get('ring_bend')
            if ring_freq is not None:
                params['ring_frequency'] = ring_freq
            if ring_bend is not None:
                params['ring_bend'] = ring_bend
                
            ring_waveform = self.store.get('ring_waveform')
            if ring_waveform:
                params['ring_waveform'] = self.state.global_ring_waveform
            elif self.state.ring_morph:
                morph_pos = self.store.get('ring_morph_position', 0)
                params['ring_waveform'] = self.state.ring_morph.get_waveform(morph_pos)
                
        return params

    def _create_envelope(self):
        """Create a new envelope with stored parameters."""
        if not self.path_parser.has_envelope_paths:
            return None
            
        try:
            envelope_params = {}
            for param in ['attack_time', 'decay_time', 'release_time', 
                         'attack_level', 'sustain_level']:
                value = self.store.get(param)
                if value is not None:
                    try:
                        envelope_params[param] = float(value)
                    except (TypeError, ValueError) as e:
                        log(TAG_SYNTH, f"Invalid envelope parameter {param}: {value}", is_error=True)
                        continue
            
            envelope = synthio.Envelope(**envelope_params)
            return envelope
        except Exception as e:
            log(TAG_SYNTH, f"Error creating envelope: {str(e)}", is_error=True)
            return None

    # === Setup and Configuration Methods ===

    def _setup_synthio(self):
        """Initialize or update synthio synthesizer based on global settings."""
        try:
            self._configure_waveforms()
            initial_envelope = self._create_envelope()
            
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

    def _configure_waveforms(self):
        """Configure base and ring waveforms based on path configuration."""
        # Configure base waveform
        waveform = self.store.get('waveform')
        if waveform:
            self.state.global_waveform = SynthioInterfaces.create_waveform(waveform)
            self.state.base_morph = None
            log(TAG_SYNTH, f"Created base waveform: {waveform}")
        elif self.path_parser.waveform_sequence:
            self.state.base_morph = WaveformMorph('base', self.path_parser.waveform_sequence)
            self.state.global_waveform = self.state.base_morph.get_waveform(0)
            log(TAG_SYNTH, f"Created base morph table: {'-'.join(self.path_parser.waveform_sequence)}")
        else:
            log(TAG_SYNTH, "No base oscillator waveform path found", is_error=True)
            raise ValueError("No base oscillator waveform path found")
            
        # Configure ring waveform if ring mod is enabled
        if self.path_parser.has_ring_mod:
            ring_waveform = self.store.get('ring_waveform')
            if ring_waveform:
                self.state.global_ring_waveform = SynthioInterfaces.create_waveform(ring_waveform)
                self.state.ring_morph = None
                log(TAG_SYNTH, f"Created ring waveform: {ring_waveform}")
            elif self.path_parser.ring_waveform_sequence:
                self.state.ring_morph = WaveformMorph('ring', self.path_parser.ring_waveform_sequence)
                self.state.global_ring_waveform = self.state.ring_morph.get_waveform(0)
                log(TAG_SYNTH, f"Created ring morph table: {'-'.join(self.path_parser.ring_waveform_sequence)}")

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
                self.midi_handler.handle_message(msg)

        except Exception as e:
            log(TAG_SYNTH, f"Error handling MIDI message: {str(e)}", is_error=True)
            self._emergency_cleanup()

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
            
            self.store.clear()  # Clear stored values for new configuration
            self.path_parser.parse_paths(paths, config_name)
            
            if not self._initialize_set_values():
                log(TAG_SYNTH, "Failed to initialize set values", is_error=True)
                raise ValueError("Failed to initialize set values")
                
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
            
            self.store.clear()  # Clear stored values during cleanup
                
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
                
            self.store.clear()  # Clear stored values during cleanup
            log(TAG_SYNTH, "Cleanup complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Error during cleanup: {str(e)}", is_error=True)
            self._emergency_cleanup()
