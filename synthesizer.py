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
from setup import SynthesizerSetup

class SynthState:
    """Centralized store for synthesizer state including values and waveforms."""
    def __init__(self):
        # Value storage
        self.values = {}
        self.previous = {}
        
        # Waveform objects (not values - these are the actual waveform buffers)
        self.global_waveform = None
        self.global_ring_waveform = None
        self.base_morph = None
        self.ring_morph = None
        
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

class MidiSetup:
    """Handles MIDI setup and subscription management."""
    def __init__(self, midi_interface, synthesizer):
        self.midi_interface = midi_interface
        self.synthesizer = synthesizer
        self.subscription = None
        self.ready_callback = None
        
    def handle_message(self, msg):
        """Handle incoming MIDI messages."""
        try:
            if not self.synthesizer.monitor.check_health(self.synthesizer.synth, self.synthesizer.voice_pool):
                self.synthesizer._emergency_cleanup()
                return

            if not self.synthesizer.synth:
                log(TAG_SYNTH, "No synthesizer available", is_error=True)
                return

            if msg.type in self.synthesizer.path_parser.enabled_messages:
                self.synthesizer.midi_handler.handle_message(msg)

        except Exception as e:
            log(TAG_SYNTH, f"Error handling MIDI message: {str(e)}", is_error=True)
            self.synthesizer._emergency_cleanup()
            
    def setup_handlers(self):
        """Set up MIDI message handlers."""
        if self.subscription:
            self.midi_interface.unsubscribe(self.subscription)
            self.subscription = None
            
        log(TAG_SYNTH, "Setting up MIDI handlers...")
            
        message_types = [msg_type for msg_type in 
                        ('noteon', 'noteoff', 'cc', 'pitchbend', 'channelpressure')
                        if msg_type in self.synthesizer.path_parser.enabled_messages]
            
        if not message_types:
            raise ValueError("No MIDI message types enabled in paths")
            
        self.subscription = self.midi_interface.subscribe(
            self.handle_message,
            message_types=message_types,
            cc_numbers=self.synthesizer.path_parser.enabled_ccs if 'cc' in self.synthesizer.path_parser.enabled_messages else None
        )
        log(TAG_SYNTH, f"MIDI handlers configured for: {self.synthesizer.path_parser.enabled_messages}")
        
        if self.ready_callback:
            log(TAG_SYNTH, "Configuration complete - signaling ready")
            self.ready_callback()
            
    def cleanup(self):
        """Clean up MIDI subscription."""
        if self.subscription:
            self.midi_interface.unsubscribe(self.subscription)
            self.subscription = None
            log(TAG_SYNTH, "Unsubscribed from MIDI messages")
            
    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready."""
        self.ready_callback = callback
        log(TAG_SYNTH, "Ready callback registered")

class Synthesizer:
    """Main synthesizer class coordinating sound generation."""
    def __init__(self, midi_interface, audio_system=None):
        # Initialize setup
        self.setup = SynthesizerSetup(midi_interface, audio_system)
        
        # Initialize components through setup
        components = self.setup.initialize()
        self.synth = components['synth']
        self.voice_pool = components['voice_pool']
        self.path_parser = components['path_parser']
        self.state = components['state']  # Now using combined SynthState
        self.monitor = components['monitor']
        self.midi_handler = components['midi_handler']
        
        # Set synthesizer reference in midi_handler
        self.midi_handler.synthesizer = self
        
        # Initialize MIDI setup
        self.midi_setup = MidiSetup(midi_interface, self)
        
        log(TAG_SYNTH, "Synthesizer initialized")

    def _create_envelope(self, store, path_parser):
        """Create a new envelope with stored parameters."""
        if not path_parser.has_envelope_paths:
            return None
            
        try:
            envelope_params = {}
            for param in ['attack_time', 'decay_time', 'release_time', 
                         'attack_level', 'sustain_level']:
                value = store.get(param)
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

    def _emergency_cleanup(self):
        """Perform emergency cleanup in case of critical errors."""
        log(TAG_SYNTH, "Performing emergency cleanup", is_error=True)
        try:
            if self.voice_pool:
                self.voice_pool.release_all()
                log(TAG_SYNTH, "Emergency released all voices")
            
            self.midi_setup.cleanup()
                
            if self.synth:
                try:
                    self.synth.deinit()
                except Exception as e:
                    log(TAG_SYNTH, f"Error deinitializing synth: {str(e)}", is_error=True)
            self.synth = None
            
            self.state.clear()  # Clear stored values during cleanup
                
            try:
                self.synth = self.setup.setup_synthio(self.state, self.state, self.path_parser)  # Using state for both parameters
                self.midi_setup.setup_handlers()
                log(TAG_SYNTH, "Successfully re-initialized synthesizer after emergency")
            except Exception as e:
                log(TAG_SYNTH, f"Failed to re-initialize synth: {str(e)}", is_error=True)
                
            log(TAG_SYNTH, "Emergency cleanup complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Error during emergency cleanup: {str(e)}", is_error=True)

    def store_value(self, name, value, use_now=True):
        """Store a value and optionally use it immediately."""
        self.state.store(name, value)  # Using combined state
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
                self.update_morph_position(value, self.state.get('morph_position', 0))
            elif name == 'waveform':
                self.update_global_waveform(value)
            else:
                log(TAG_SYNTH, f"No immediate handler for {name}={value}")
        except Exception as e:
            log(TAG_SYNTH, f"Error handling value update for {name}: {str(e)}", is_error=True)

    def _update_math(self, name, value):
        """Handle math operation updates."""
        log(TAG_SYNTH, f"Math update: {name}={value}")
        # TODO: Implement math operations

    def _update_lfo(self, name, value):
        """Handle LFO parameter updates."""
        log(TAG_SYNTH, f"LFO update: {name}={value}")
        # TODO: Implement LFO operations

    def update_global_envelope(self, param_name, value):
        """Update global envelope with new parameter."""
        self.state.store(param_name, value)
        envelope = self._create_envelope(self.state, self.path_parser)
        if envelope:
            self.synth.envelope = envelope
            log(TAG_SYNTH, f"Updated global envelope {param_name}={value}")

    def update_global_filter(self, param_name, value):
        """Update global filter with new parameter."""
        # Store the incoming parameter
        self.state.store(param_name, value)
        
        # Check state for all required filter parameters
        filter_freq = self.state.get('filter_frequency')
        filter_res = self.state.get('filter_resonance')
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
        self.state.store('waveform', waveform_type)
        
        try:
            # Create new waveform
            new_waveform = SynthioInterfaces.create_waveform(waveform_type)
            if new_waveform:
                self.state.global_waveform = new_waveform
                self.state.base_morph = None
                
                # Check state for morph position
                morph_pos = self.state.get('morph_position')
                if morph_pos is not None:
                    self.voice_pool.for_each_active_voice(
                        lambda v: self._update_voice_morph(v, morph_pos))
                
                log(TAG_SYNTH, f"Updated global waveform: {waveform_type}")
        except Exception as e:
            log(TAG_SYNTH, f"Failed to update global waveform: {str(e)}", is_error=True)

    def update_morph_position(self, position, midi_value):
        """Update waveform morph position."""
        # Store both position and MIDI value
        self.state.store('morph_position', midi_value)
        self.state.store('morph', position)
        
        # Check if we have a base morph to work with
        if self.state.base_morph:
            # Check state for ring morph if available
            ring_morph = self.state.get('ring_morph')
            
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
        self.state.store(param_name, value)
        
        # Check state for all ring mod parameters
        ring_freq = self.state.get('ring_frequency')
        ring_bend = self.state.get('ring_bend')
        ring_morph = self.state.get('ring_morph')
        
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
                    self.state.get('filter_frequency'),
                    self.state.get('filter_resonance')
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
            filter_freq = self.state.get('filter_frequency', 0)
            filter_res = self.state.get('filter_resonance', 0)
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
        
        waveform = self.state.get('waveform')
        if waveform:
            params['waveform'] = self.state.global_waveform
        elif self.state.base_morph:
            morph_pos = self.state.get('morph_position', 0)
            params['waveform'] = self.state.base_morph.get_waveform(morph_pos)
                
        if self.path_parser.has_ring_mod:
            ring_freq = self.state.get('ring_frequency')
            ring_bend = self.state.get('ring_bend')
            if ring_freq is not None:
                params['ring_frequency'] = ring_freq
            if ring_bend is not None:
                params['ring_bend'] = ring_bend
                
            ring_waveform = self.state.get('ring_waveform')
            if ring_waveform:
                params['ring_waveform'] = self.state.global_ring_waveform
            elif self.state.ring_morph:
                morph_pos = self.state.get('ring_morph_position', 0)
                params['ring_waveform'] = self.state.ring_morph.get_waveform(morph_pos)
                
        return params

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

    def update_instrument(self, paths, config_name=None):
        """Update instrument configuration."""
        log(TAG_SYNTH, "Updating instrument configuration...")
        log(TAG_SYNTH, "----------------------------------------")
        
        try:
            if self.voice_pool:
                self.voice_pool.release_all()
                log(TAG_SYNTH, "Released all voices during reconfiguration")
            
            self.state.clear()  # Clear stored values for new configuration
            self.path_parser.parse_paths(paths, config_name)
            
            if not self.setup.initialize_set_values(self.state, self.path_parser):
                log(TAG_SYNTH, "Failed to initialize set values", is_error=True)
                raise ValueError("Failed to initialize set values")
                
            self.synth = self.setup.setup_synthio(self.state, self.state, self.path_parser)  # Using state for both parameters
            self.midi_setup.setup_handlers()
            
            log(TAG_SYNTH, "----------------------------------------")
            log(TAG_SYNTH, "Instrument update complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Failed to update instrument: {str(e)}", is_error=True)
            self._emergency_cleanup()
            raise

    def cleanup(self):
        """Clean up resources."""
        self.setup.cleanup(self)
    
    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready."""
        self.midi_setup.register_ready_callback(callback)
