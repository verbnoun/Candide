"""High-level synthesizer coordination module."""

import sys
import time
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from logging import log, TAG_SYNTH
from voices import VoicePool
from router import PathParser
from patcher import MidiHandler
from interfaces import SynthioInterfaces, FilterMode, Math, LFO
from setup import SynthesizerSetup

class SynthState:
    """Centralized store for synthesizer state including values and waveforms."""
    def __init__(self):
        # Value storage
        self.values = {}  # Global values
        self.per_channel_values = {i: {} for i in range(1, 16)}  # Channel-specific values (1-15)
        self.previous = {}  # Previous global values
        self.previous_channel = {i: {} for i in range(1, 16)}  # Previous channel values
        
    def store(self, name, value, channel=None):
        """Store a value and keep track of previous.
        
        Args:
            name: Parameter name
            value: Value to store
            channel: Channel number (1-15) or None for global
        """
        if channel is not None:
            if channel < 1 or channel > 15:
                log(TAG_SYNTH, f"Invalid channel {channel}", is_error=True)
                return
                
            if name in self.per_channel_values[channel]:
                self.previous_channel[channel][name] = self.per_channel_values[channel][name]
            self.per_channel_values[channel][name] = value
            log(TAG_SYNTH, f"Stored channel {channel} value {name}={value}")
        else:
            if name in self.values:
                self.previous[name] = self.values[name]
            self.values[name] = value
            log(TAG_SYNTH, f"Stored global value {name}={value}")
        
    def get(self, name, channel=None, default=None):
        """Get a stored value.
        
        Args:
            name: Parameter name
            channel: Channel number (1-15) or None for global
            default: Default value if not found
            
        Returns:
            Stored value or default
        """
        if channel is not None:
            if channel < 1 or channel > 15:
                log(TAG_SYNTH, f"Invalid channel {channel}", is_error=True)
                return default
            # Get channel value, fall back to global if None
            channel_value = self.per_channel_values[channel].get(name)
            if channel_value is not None:
                return channel_value
        return self.values.get(name, default)
        
    def get_previous(self, name, channel=None, default=None):
        """Get previous value if it exists.
        
        Args:
            name: Parameter name
            channel: Channel number (1-15) or None for global
            default: Default value if not found
            
        Returns:
            Previous value or default
        """
        if channel is not None:
            if channel < 1 or channel > 15:
                log(TAG_SYNTH, f"Invalid channel {channel}", is_error=True)
                return default
            # Get channel previous, fall back to global previous if None
            channel_prev = self.previous_channel[channel].get(name)
            if channel_prev is not None:
                return channel_prev
        return self.previous.get(name, default)
        
    def clear(self):
        """Clear all stored values."""
        self.values.clear()
        self.previous.clear()
        for channel in range(1, 16):
            self.per_channel_values[channel].clear()
            self.previous_channel[channel].clear()

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
                log(TAG_SYNTH, f"Synthesizer object is None", is_error=True)
                return False
            self.last_health_check = current_time
            return True
        return True
    
class EnvelopeHandler:
    """Manages envelope parameters and creation."""
    PARAMS = ['attack_time', 'decay_time', 'release_time', 
              'attack_level', 'sustain_level']

    def __init__(self, state, synth):
        self.state = state
        self.synth = synth

    def store_param(self, param, value, channel=None):
        """Store param in state and check for complete envelope."""
        if param not in self.PARAMS:
            log(TAG_SYNTH, f"Invalid envelope parameter: {param}", is_error=True)
            return
            
        # Store the parameter
        self.state.store(param, value, channel)
        
        # For global params, check if we have a complete set
        if channel is None:
            self._update_global_envelope()

    def _update_global_envelope(self):
        """Check store for complete parameter set and update synth envelope."""
        params = {}
        
        # Check for all required parameters
        for param in self.PARAMS:
            value = self.state.get(param)  # Get from global store
            if value is None:
                # Missing a parameter, can't update yet
                return
            try:
                params[param] = float(value)
            except (TypeError, ValueError) as e:
                log(TAG_SYNTH, f"Invalid envelope parameter {param}: {value}", is_error=True)
                return
                
        # We have all parameters, create and set envelope
        try:
            if self.synth is not None:
                envelope = SynthioInterfaces.create_envelope(**params)
                self.synth.envelope = envelope
                log(TAG_SYNTH, "Updated global envelope")
        except Exception as e:
            log(TAG_SYNTH, f"Error updating global envelope: {str(e)}", is_error=True)

    def get_note_envelope(self, channel):
        """Get envelope for note, using channel params with global fallback."""
        if channel is None:
            return None
            
        params = {}
        has_channel_params = False
        
        # Try to get each parameter, falling back to global if needed
        for param in self.PARAMS:
            # First check channel-specific value
            value = self.state.get(param, channel)
            if value is None:
                # Fall back to global value
                value = self.state.get(param)
                if value is None:
                    # No value found, can't create envelope
                    return None
            else:
                has_channel_params = True
                
            try:
                params[param] = float(value)
            except (TypeError, ValueError) as e:
                log(TAG_SYNTH, f"Invalid envelope parameter {param}: {value}", is_error=True)
                return None
                
        # Only create note envelope if we found at least one channel-specific param
        if has_channel_params:
            try:
                return SynthioInterfaces.create_envelope(**params)
            except Exception as e:
                log(TAG_SYNTH, f"Error creating note envelope: {str(e)}", is_error=True)
                return None
                
        return None

class Synthesizer:
    """Main synthesizer class coordinating sound generation."""
    
    # Parameter update functions using synthio vocabulary
    _param_updates = {
        # Direct synthio properties
        'bend': lambda note, value: setattr(note, 'bend', value),
        'amplitude': lambda note, value: setattr(note, 'amplitude', value),
        'panning': lambda note, value: setattr(note, 'panning', value),
        'waveform': lambda note, value: setattr(note, 'waveform', value),
        'waveform_loop_start': lambda note, value: setattr(note, 'waveform_loop_start', value),
        'waveform_loop_end': lambda note, value: setattr(note, 'waveform_loop_end', value),
        'ring_frequency': lambda note, value: setattr(note, 'ring_frequency', value),
        'ring_bend': lambda note, value: setattr(note, 'ring_bend', value),
        'ring_waveform': lambda note, value: setattr(note, 'ring_waveform', value),
        'ring_waveform_loop_start': lambda note, value: setattr(note, 'ring_waveform_loop_start', value),
        'ring_waveform_loop_end': lambda note, value: setattr(note, 'ring_waveform_loop_end', value),
        
        # Filter logging (handled in filter block)
        'filter_frequency': lambda note, value: log(TAG_SYNTH, "Filter update handled by filter block"),
        'filter_resonance': lambda note, value: log(TAG_SYNTH, "Filter update handled by filter block"),
        
        # Unsupported operation logging
        'oscillator_frequency': lambda note, value: log(TAG_SYNTH, "Note frequency cannot be updated during play"),
        'math_operation': lambda note, value: log(TAG_SYNTH, "Math operations not yet implemented"),
        'lfo_parameter': lambda note, value: log(TAG_SYNTH, "LFO operations not yet implemented")
    }
    
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
        
        # Initialize envelope handler
        self.envelope_handler = EnvelopeHandler(self.state, self.synth)
        
        # Set synthesizer reference in midi_handler
        self.midi_handler.synthesizer = self
        
        # Set synthesizer reference in setup for updates
        self.setup.set_synthesizer(self)
        
        # Initialize current filter type
        self._current_filter_type = None
        
        log(TAG_SYNTH, "Synthesizer initialized")

    def cleanup(self):
        """Clean up resources."""
        self.setup.cleanup(self)
    
    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready."""
        self.midi_handler.register_ready_callback(callback)

    def set_parameter(self, param_name, value, channel=None):
        """Update parameter on notes based on channel specification."""
        self.state.store(param_name, value, channel)
                
        # Handling for filter parameters
        if param_name.startswith('filter_'):
            # Get global values first
            filter_freq = self.state.get('filter_frequency')
            filter_res = self.state.get('filter_resonance')
            
            # Override with channel values if they exist
            if channel is not None:
                channel_freq = self.state.get('filter_frequency', channel)
                channel_res = self.state.get('filter_resonance', channel)
                if channel_freq is not None:
                    filter_freq = channel_freq
                if channel_res is not None:
                    filter_res = channel_res
                    
            # Only proceed if we have all required filter parameters
            if filter_freq is not None and filter_res is not None:
                def update_voice(voice):
                    if voice.active_note:
                        try:
                            # Create new filter for each voice
                            # Note: filter_type is set by the specific handler (e.g. set_synth_filter_notch_frequency)
                            filter = SynthioInterfaces.create_filter(
                                self.synth,
                                self._current_filter_type,  # Set by handler
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
        
        # If parameter has an update function, apply to active notes
        if param_name in self._param_updates:
            if channel is None:
                # Update all playing notes
                def update_voice(voice):
                    if voice.active_note:
                        try:
                            self._param_updates[param_name](voice.active_note, value)
                            log(TAG_SYNTH, f"Updated {param_name}={value} for voice {voice.get_address()}")
                        except Exception as e:
                            log(TAG_SYNTH, f"Failed to update {param_name}: {str(e)}", is_error=True)
                self.voice_pool.for_each_active_voice(update_voice)
            else:
                # Update specific channel
                voice = self.voice_pool.get_voice_by_channel(channel)
                if voice and voice.active_note:
                    try:
                        self._param_updates[param_name](voice.active_note, value)
                        log(TAG_SYNTH, f"Updated {param_name}={value} for channel {channel}")
                    except Exception as e:
                        log(TAG_SYNTH, f"Failed to update {param_name} on channel {channel}: {str(e)}", is_error=True)

    # Core Parameter Handlers
    def set_frequency(self, value, channel=None):
        """Set frequency value."""
        self.set_parameter('frequency', value, channel)

    def set_amplitude(self, value, channel=None):
        """Set amplitude value."""
        self.set_parameter('amplitude', value, channel)

    def set_bend(self, value, channel=None):
        """Set bend value."""
        self.set_parameter('bend', value, channel)

    def set_panning(self, value, channel=None):
        """Set panning value."""
        self.set_parameter('panning', value, channel)

    def set_waveform(self, value, channel=None):
        """Set waveform value."""
        self.set_parameter('waveform', value, channel)

    def set_ring_frequency(self, value, channel=None):
        """Set ring modulation frequency."""
        self.set_parameter('ring_frequency', value, channel)

    def set_ring_bend(self, value, channel=None):
        """Set ring modulation bend."""
        self.set_parameter('ring_bend', value, channel)

    def set_ring_waveform(self, value, channel=None):
        """Set ring modulation waveform."""
        self.set_parameter('ring_waveform', value, channel)

    # Filter handlers - each sets its own type
    def set_synth_filter_low_pass_frequency(self, value, channel=None):
        """Set low-pass filter frequency."""
        self._current_filter_type = 'low_pass'
        self.set_parameter('filter_frequency', value, channel)

    def set_synth_filter_low_pass_resonance(self, value, channel=None):
        """Set low-pass filter resonance."""
        self._current_filter_type = 'low_pass'
        self.set_parameter('filter_resonance', value, channel)

    def set_synth_filter_high_pass_frequency(self, value, channel=None):
        """Set high-pass filter frequency."""
        self._current_filter_type = 'high_pass'
        self.set_parameter('filter_frequency', value, channel)

    def set_synth_filter_high_pass_resonance(self, value, channel=None):
        """Set high-pass filter resonance."""
        self._current_filter_type = 'high_pass'
        self.set_parameter('filter_resonance', value, channel)

    def set_synth_filter_band_pass_frequency(self, value, channel=None):
        """Set band-pass filter frequency."""
        self._current_filter_type = 'band_pass'
        self.set_parameter('filter_frequency', value, channel)

    def set_synth_filter_band_pass_resonance(self, value, channel=None):
        """Set band-pass filter resonance."""
        self._current_filter_type = 'band_pass'
        self.set_parameter('filter_resonance', value, channel)

    def set_synth_filter_notch_frequency(self, value, channel=None):
        """Set notch filter frequency."""
        self._current_filter_type = 'notch'
        self.set_parameter('filter_frequency', value, channel)

    def set_synth_filter_notch_resonance(self, value, channel=None):
        """Set notch filter resonance."""
        self._current_filter_type = 'notch'
        self.set_parameter('filter_resonance', value, channel)

    # Envelope handlers - dedicated methods for each parameter
    def set_envelope_attack_level(self, value, channel=None):
        """Set envelope attack level."""
        self.envelope_handler.store_param('attack_level', value, channel)

    def set_envelope_attack_time(self, value, channel=None):
        """Set envelope attack time."""
        self.envelope_handler.store_param('attack_time', value, channel)

    def set_envelope_decay_time(self, value, channel=None):
        """Set envelope decay time."""
        self.envelope_handler.store_param('decay_time', value, channel)

    def set_envelope_sustain_level(self, value, channel=None):
        """Set envelope sustain level."""
        self.envelope_handler.store_param('sustain_level', value, channel)

    def set_envelope_release_time(self, value, channel=None):
        """Set envelope release time."""
        self.envelope_handler.store_param('release_time', value, channel)

    def press_voice(self, note_number, channel, note_values):
        """Press note with given values."""
        voice = self.voice_pool.press_note(note_number, channel)
        if not voice:
            return
            
        # Build note parameters from stored values
        params = self._build_note_params(channel)
        
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
        
        # Store bundled values to channel
        for name, value in note_values.items():
            self.state.store(name, value, channel)

    def release_voice(self, note_number, channel, note_values=None):
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

    def _build_note_params(self, channel):
        """Build note parameters from stored values."""
        params = {}
        
        # Get frequency
        frequency = self.state.get('frequency')
        if channel is not None:
            channel_freq = self.state.get('frequency', channel)
            if channel_freq is not None:
                frequency = channel_freq
        if frequency is not None:
            params['frequency'] = frequency
            
        # Get all note parameters
        note_params = [
            'amplitude', 'bend', 'panning',
            'waveform', 'waveform_loop_start', 'waveform_loop_end',
            'ring_frequency', 'ring_bend', 'ring_waveform',
            'ring_waveform_loop_start', 'ring_waveform_loop_end'
        ]
        
        for name in note_params:
            value = self.state.get(name)
            if channel is not None:
                channel_value = self.state.get(name, channel)
                if channel_value is not None:
                    value = channel_value
            if value is not None:
                params[name] = value
                
        # Handle waveform loop ends
        if 'waveform' in params and 'waveform_loop_end' not in params:
            params['waveform_loop_end'] = len(params['waveform'])
        if 'ring_waveform' in params and 'ring_waveform_loop_end' not in params:
            params['ring_waveform_loop_end'] = len(params['ring_waveform'])
            
        # Add filter if we have all parameters
        filter_freq = self.state.get('filter_frequency')
        filter_res = self.state.get('filter_resonance')
        
        if channel is not None:
            channel_freq = self.state.get('filter_frequency', channel)
            channel_res = self.state.get('filter_resonance', channel)
            if channel_freq is not None:
                filter_freq = channel_freq
            if channel_res is not None:
                filter_res = channel_res
                
        if filter_freq is not None and filter_res is not None and self._current_filter_type:
            try:
                # Use SynthioInterfaces to create filter
                filter = SynthioInterfaces.create_filter(
                    self.synth,
                    self._current_filter_type,  # Use current filter type
                    filter_freq,
                    filter_res
                )
                params['filter'] = filter
            except Exception as e:
                log(TAG_SYNTH, f"Failed to create filter: {str(e)}", is_error=True)
                
        # Get note envelope if available
        envelope = self.envelope_handler.get_note_envelope(channel)
        if envelope is not None:
            params['envelope'] = envelope
                    
        return params

    def store_value(self, name, value, channel=None):
        """Store a value in the state."""
        self.state.store(name, value, channel)

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