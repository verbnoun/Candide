"""High-level synthesizer coordination module."""

import synthio
import sys
import time
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from logging import log, TAG_SYNTH
from voices import VoicePool
from router import PathParser
from patcher import MidiHandler
from interfaces import SynthioInterfaces
from setup import SynthesizerSetup

class SynthState:
    """Centralized store for synthesizer state including values and waveforms."""
    def __init__(self):
        # Value storage
        self.values = {}
        self.previous = {}
        
        # Global waveform storage
        self.global_waveform = None
        self.global_ring_waveform = None
        
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
        self.global_waveform = None
        self.global_ring_waveform = None

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
    """Main synthesizer class coordinating sound generation."""
    
    # Core Methods
    def __init__(self, midi_interface, audio_system=None):
        # Initialize setup
        self.setup = SynthesizerSetup(midi_interface, audio_system)
        
        # Initialize components through setup
        components = self.setup.initialize()
        self.synth = components['synth']
        self.voice_pool = components['voice_pool']
        self.path_parser = components['path_parser']
        self.state = components['state']
        self.monitor = components['monitor']
        self.midi_handler = components['midi_handler']
        
        # Set synthesizer reference in midi_handler
        self.midi_handler.synthesizer = self
        
        # Set synthesizer reference in setup for updates
        self.setup.set_synthesizer(self)
        
        log(TAG_SYNTH, "Synthesizer initialized")

    def cleanup(self):
        """Clean up resources."""
        self.setup.cleanup(self)
    
    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready."""
        self.midi_handler.register_ready_callback(callback)

    def update_parameter(self, param_name, value, channel=None):
        """Update parameter on notes based on channel specification.
        
        Args:
            param_name: Parameter to update
            value: New value to set
            channel: None for all notes, or specific channel number
        """
        # Always store non-channel-specific values
        if channel is None:
            self.state.store(param_name, value)
            
            # Special handling for waveforms
            if param_name == 'waveform':
                self.state.global_waveform = value
            elif param_name == 'ring_waveform':
                self.state.global_ring_waveform = value
                
        # Handling for filter parameters
        if param_name.startswith('filter_'):
            self.state.store(param_name, value)
            filter_freq = self.state.get('filter_frequency')
            filter_res = self.state.get('filter_resonance')
            filter_type = self.path_parser.filter_type
            
            # Only proceed if we have all filter parameters
            if filter_freq is not None and filter_res is not None and filter_type:
                def update_voice(voice):
                    if voice.active_note:
                        try:
                            # Create new filter for each voice
                            filter = SynthioInterfaces.create_filter(
                                self.synth,
                                filter_type,
                                filter_freq,
                                filter_res
                            )
                            if filter:
                                voice.active_note.filter = filter
                                log(TAG_SYNTH, f"Updated filter for voice {voice.get_address()}")
                        except Exception as e:
                            log(TAG_SYNTH, f"Failed to update voice filter: {str(e)}", is_error=True)
                
                # Update filters based on channel
                if channel is None:
                    self.voice_pool.for_each_active_voice(update_voice)
                else:
                    voice = self.voice_pool.get_voice_by_channel(channel)
                    if voice:
                        update_voice(voice)
                return
        
        # Define which parameters can be updated during play
        updatable_params = {
            'bend': lambda note: setattr(note, 'bend', value),
            'amplitude': lambda note: setattr(note, 'amplitude', value),
            'panning': lambda note: setattr(note, 'panning', value),
            'waveform': lambda note: self._update_waveform(note, value),
            'waveform_loop_start': lambda note: setattr(note, 'waveform_loop_start', value),
            'waveform_loop_end': lambda note: setattr(note, 'waveform_loop_end', value),
            'ring_frequency': lambda note: setattr(note, 'ring_frequency', value),
            'ring_bend': lambda note: setattr(note, 'ring_bend', value),
            'ring_waveform': lambda note: self._update_ring_waveform(note, value),
            'ring_waveform_loop_start': lambda note: setattr(note, 'ring_waveform_loop_start', value),
            'ring_waveform_loop_end': lambda note: setattr(note, 'ring_waveform_loop_end', value)
        }
        
        # Helper methods for waveform updates
        def _update_waveform(note, waveform):
            note.waveform = waveform
            note.waveform_loop_end = len(waveform)
            
        def _update_ring_waveform(note, waveform):
            note.ring_waveform = waveform
            note.ring_waveform_loop_end = len(waveform)
        
        # If parameter is updatable during play
        if param_name in updatable_params:
            if channel is None:
                # Update all playing notes
                def update_voice(voice):
                    if voice.active_note:
                        try:
                            updatable_params[param_name](voice.active_note)
                            log(TAG_SYNTH, f"Updated {param_name}={value} for voice {voice.get_address()}")
                        except Exception as e:
                            log(TAG_SYNTH, f"Failed to update {param_name}: {str(e)}", is_error=True)
                self.voice_pool.for_each_active_voice(update_voice)
            else:
                # Update specific channel
                voice = self.voice_pool.get_voice_by_channel(channel)
                if voice and voice.active_note:
                    try:
                        updatable_params[param_name](voice.active_note)
                        log(TAG_SYNTH, f"Updated {param_name}={value} for channel {channel}")
                    except Exception as e:
                        log(TAG_SYNTH, f"Failed to update {param_name} on channel {channel}: {str(e)}", is_error=True)

    # Action Handlers (public interface)
    def update_voice_parameter(self, param_name, value, channel):
        """Update parameter on voice by channel."""
        self.update_parameter(param_name, value, channel)

    def update_voice_waveform(self, waveform_buffer, channel):
        """Update waveform for a specific voice."""
        self.update_parameter('waveform', waveform_buffer, channel)

    def update_global_waveform(self, waveform_buffer):
        """Update global waveform with new buffer."""
        self.update_parameter('waveform', waveform_buffer, None)

    def update_amplifier_amplitude(self, target, value):
        """Update global amplifier amplitude."""
        self.update_parameter('amplitude', value, None)

    def update_ring_modulation(self, param_name, value):
        """Update ring modulation parameters."""
        self.update_parameter(param_name, value, None)

    def update_global_filter(self, param_name, value):
        """Update global filter with new parameter."""
        self.update_parameter(param_name, value, None)

    def update_global_envelope(self, param_name, value):
        """Update global envelope with new parameter."""
        if not self.path_parser.has_envelope_paths:
            return
            
        # Store the incoming parameter if provided
        if param_name is not None and value is not None:
            self.state.store(param_name, value)
        
        # Check store for all envelope parameters
        envelope_params = {}
        for param in ['attack_time', 'decay_time', 'release_time', 
                     'attack_level', 'sustain_level']:
            value = self.state.get(param)
            if value is not None:
                try:
                    envelope_params[param] = float(value)
                    log(TAG_SYNTH, f"Using envelope parameter {param}: {value}")
                except (TypeError, ValueError) as e:
                    log(TAG_SYNTH, f"Invalid envelope parameter {param}: {value}", is_error=True)
                    continue
        
        # Create and apply envelope if we have all parameters
        if len(envelope_params) == 5:  # Only create if we have all parameters
            try:
                envelope = SynthioInterfaces.create_envelope(**envelope_params)
                self.synth.envelope = envelope
                log(TAG_SYNTH, "Successfully created and set envelope")
            except Exception as e:
                log(TAG_SYNTH, f"Error creating/setting envelope: {str(e)}", is_error=True)
        else:
            missing = set(['attack_time', 'decay_time', 'release_time', 
                         'attack_level', 'sustain_level']) - set(envelope_params.keys())
            log(TAG_SYNTH, f"Missing envelope parameters: {missing}")

    def press(self, note_number, channel, note_values):
        """Press note with given values."""
        voice = self.voice_pool.press_note(note_number, channel)
        if not voice:
            return
            
        # Build note parameters from passed values and stored values
        params = self._build_note_params(note_values)
        
        try:
            note = SynthioInterfaces.create_note(**params)
            self.synth.press(note)
            voice.active_note = note
            # Add amplitude to scaler after note is created
            self.voice_pool.add_note_amplitude(voice)
            log(TAG_SYNTH, f"Created note {note_number} on channel {channel}")
        except Exception as e:
            log(TAG_SYNTH, f"Failed to create note: {str(e)}", is_error=True)
            self.voice_pool.release_note(note_number)

    def release(self, note_number, channel, note_values=None):
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

    # Voice Management Helpers (private)
    def _build_note_params(self, note_values):
        """Build note parameters from passed values and stored values."""
        params = {}
        
        # Start with any passed values
        if note_values:
            params.update(note_values)
            
        # If global amplitude is stored, apply it to the note's amplitude
        stored_amp = self.state.get('amplifier_amplitude')
        if stored_amp is not None:
            if 'amplitude' in params:
                # If note has its own amplitude, multiply with global
                params['amplitude'] *= stored_amp
            else:
                # Otherwise use global amplitude directly
                params['amplitude'] = stored_amp
            
        # Add stored frequency if not passed
        if 'frequency' not in params:
            stored_freq = self.state.get('frequency')
            if stored_freq is not None:
                params['frequency'] = stored_freq
                
        # Add stored bend if available
        stored_bend = self.state.get('bend')
        if stored_bend is not None:
            params['bend'] = stored_bend
        
        # Add filter if configured
        if self.path_parser.filter_type:
            filter_freq = self.state.get('filter_frequency')
            filter_res = self.state.get('filter_resonance')
            if filter_freq is not None and filter_res is not None:
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
        
        # Add global waveform if available
        if self.state.global_waveform is not None:
            params['waveform'] = self.state.global_waveform
            params['waveform_loop_end'] = len(self.state.global_waveform)
                
        # Add ring modulation if configured
        if self.path_parser.has_ring_mod:
            ring_freq = self.state.get('ring_frequency')
            ring_bend = self.state.get('ring_bend')
            if ring_freq is not None:
                params['ring_frequency'] = ring_freq
            if ring_bend is not None:
                params['ring_bend'] = ring_bend
                
            if self.state.global_ring_waveform is not None:
                params['ring_waveform'] = self.state.global_ring_waveform
                params['ring_waveform_loop_end'] = len(self.state.global_ring_waveform)
                
        return params

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

    # State Management Helper (private)
    def store_value(self, name, value):
        """Store a value in the state."""
        self.state.store(name, value)

    # Error Handling
    def _emergency_cleanup(self):
        """Perform emergency cleanup in case of critical errors."""
        log(TAG_SYNTH, "Performing emergency cleanup", is_error=True)
        try:
            if self.voice_pool:
                self.voice_pool.release_all()
                log(TAG_SYNTH, "Emergency released all voices")
            
            if self.midi_handler:
                self.midi_handler.cleanup()
                
            if self.synth:
                try:
                    self.synth.deinit()
                except Exception as e:
                    log(TAG_SYNTH, f"Error deinitializing synth: {str(e)}", is_error=True)
            self.synth = None
            
            self.state.clear()
                
            try:
                self.synth = self.setup.setup_synthio(self.state, self.state, self.path_parser)
                self.midi_handler.setup_handlers()
                log(TAG_SYNTH, "Successfully re-initialized synthesizer after emergency")
            except Exception as e:
                log(TAG_SYNTH, f"Failed to re-initialize synth: {str(e)}", is_error=True)
                
            log(TAG_SYNTH, "Emergency cleanup complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Error during emergency cleanup: {str(e)}", is_error=True)

    def _update_math(self, name, value):
        """Handle math operation updates."""
        log(TAG_SYNTH, f"Math update: {name}={value}")
        # TODO: Implement math operations

    def _update_lfo(self, name, value):
        """Handle LFO parameter updates."""
        log(TAG_SYNTH, f"LFO update: {name}={value}")
        # TODO: Implement LFO operations
