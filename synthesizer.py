"""High-level synthesizer coordination module."""

import sys
import time
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from logging import log, TAG_SYNTH, format_value
from voices import VoicePool
from router import PathParser
from patcher import MidiHandler
from interfaces import SynthioInterfaces, FilterMode, Math, LFO
from setup import SynthesizerSetup

class SynthStore:
    def __init__(self):
        self.per_channel_values = {i: {} for i in range(1, 16)}
        self.previous_channel = {i: {} for i in range(1, 16)}
        self._batch_store = False
        
    def store(self, name, value, channel):
        if channel < 1 or channel > 15:
            log(TAG_SYNTH, f"Invalid channel {channel}", is_error=True)
            return
                
        # Strip 'set_' from name for storage and logging
        value_name = name[4:] if name.startswith('set_') else name
                
        if value_name in self.per_channel_values[channel]:
            self.previous_channel[channel][value_name] = self.per_channel_values[channel][value_name]
        self.per_channel_values[channel][value_name] = value
        
        # Only log if not in batch store mode
        if not self._batch_store:
            if value_name.endswith('waveform'):
                log(TAG_SYNTH, f"Stored channel {channel} value {value_name}")
            else:
                log(TAG_SYNTH, f"Stored channel {channel} value {value_name}={format_value(value)}")
    
    def begin_batch_store(self):
        self._batch_store = True
        
    def end_batch_store(self, value_name):
        self._batch_store = False
        log(TAG_SYNTH, f"Updated channels 1-15 with {value_name}")
        
    def get(self, name, channel, default=None):
        if channel < 1 or channel > 15:
            log(TAG_SYNTH, f"Invalid channel {channel}", is_error=True)
            return default
            
        return self.per_channel_values[channel].get(name, default)
        
    def get_previous(self, name, channel, default=None):
        if channel < 1 or channel > 15:
            log(TAG_SYNTH, f"Invalid channel {channel}", is_error=True)
            return default
            
        return self.previous_channel[channel].get(name, default)
        
    def clear(self):
        for channel in range(1, 16):
            self.per_channel_values[channel].clear()
            self.previous_channel[channel].clear()

class SynthMonitor:
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
    PARAMS = ['attack_time', 'decay_time', 'release_time', 
              'attack_level', 'sustain_level']

    def __init__(self, state, synth):
        self.state = state
        self.synth = synth

    def store_param(self, param, value, channel):
        if param not in self.PARAMS:
            log(TAG_SYNTH, f"Invalid envelope parameter: {param}", is_error=True)
            return
            
        if channel == 0:
            self.state.begin_batch_store()
            for ch in range(1, 16):
                self.state.store(param, value, ch)
            self.state.end_batch_store(param)
        else:
            self.state.store(param, value, channel)

    def get_note_envelope(self, channel):
        if channel < 1 or channel > 15:
            return None
            
        params = {}
        
        for param in self.PARAMS:
            value = self.state.get(param, channel)
            if value is None:
                return None
                
            # No type conversion needed - router handles this
            params[param] = value
                
        try:
            return SynthioInterfaces.create_envelope(**params)
        except Exception as e:
            log(TAG_SYNTH, f"Error creating note envelope: {str(e)}", is_error=True)
            return None

class Synthesizer:
    _param_updates = {
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
        'filter_frequency': lambda note, value: log(TAG_SYNTH, "Filter update handled by filter block"),
        'filter_resonance': lambda note, value: log(TAG_SYNTH, "Filter update handled by filter block"),
        'oscillator_frequency': lambda note, value: log(TAG_SYNTH, "Note frequency cannot be updated during play"),
        'math_operation': lambda note, value: log(TAG_SYNTH, "Math operations not yet implemented"),
        'lfo_parameter': lambda note, value: log(TAG_SYNTH, "LFO operations not yet implemented")
    }
    
    def __init__(self, midi_interface, audio_system=None):
        self.setup = SynthesizerSetup(midi_interface, audio_system)
        
        components = self.setup.initialize()
        self.synth = components['synth']
        self.voice_pool = components['voice_pool']
        self.path_parser = components['path_parser']
        self.state = components['state']
        self.monitor = components['monitor']
        self.midi_handler = components['midi_handler']
        
        self.envelope_handler = EnvelopeHandler(self.state, self.synth)
        
        self.midi_handler.synthesizer = self
        
        self.setup.set_synthesizer(self)
        
        self._current_filter_type = None
        
        log(TAG_SYNTH, "Synthesizer initialized")

    def cleanup(self):
        self.setup.cleanup(self)
    
    def register_ready_callback(self, callback):
        self.midi_handler.register_ready_callback(callback)

    def set_parameter(self, param_name, value, channel):
        # Store using original name (store will strip set_ prefix)
        if channel == 0:
            self.state.begin_batch_store()
            for ch in range(1, 16):
                self.state.store(param_name, value, ch)
                # Pass base name to _update_parameter
                base_name = param_name[4:] if param_name.startswith('set_') else param_name
                self._update_parameter(base_name, value, ch)
            base_name = param_name[4:] if param_name.startswith('set_') else param_name
            self.state.end_batch_store(base_name)
        else:
            self.state.store(param_name, value, channel)
            # Pass base name to _update_parameter
            base_name = param_name[4:] if param_name.startswith('set_') else param_name
            self._update_parameter(base_name, value, channel)

    def _update_parameter(self, param_name, value, channel):
        if param_name.startswith('filter_'):
            filter_freq = self.state.get('filter_frequency', channel)
            filter_res = self.state.get('filter_resonance', channel)
                    
            if filter_freq is not None and filter_res is not None:
                def update_voice(voice):
                    if voice.active_note:
                        try:
                            filter = SynthioInterfaces.create_filter(
                                self._current_filter_type,
                                filter_freq,
                                resonance=filter_res
                            )
                            if filter:
                                voice.active_note.filter = filter
                                log(TAG_SYNTH, f"Updated filter for voice {voice.get_address()}")
                        except Exception as e:
                            log(TAG_SYNTH, f"Failed to update voice filter: {str(e)}", is_error=True)
                
                voice = self.voice_pool.get_voice_by_channel(channel)
                if voice:
                    update_voice(voice)
            return
        
        if param_name in self._param_updates:
            voice = self.voice_pool.get_voice_by_channel(channel)
            if voice and voice.active_note:
                try:
                    self._param_updates[param_name](voice.active_note, value)
                    if not param_name.endswith('waveform'):
                        log(TAG_SYNTH, f"Updated {param_name}={format_value(value)} for channel {channel}")
                    else:
                        log(TAG_SYNTH, f"Updated {param_name} for channel {channel}")
                except Exception as e:
                    log(TAG_SYNTH, f"Failed to update {param_name} on channel {channel}: {str(e)}", is_error=True)

    def set_frequency(self, value, channel):
        self.set_parameter('set_frequency', value, channel)

    def set_amplitude(self, value, channel):
        self.set_parameter('set_amplitude', value, channel)

    def set_bend(self, value, channel):
        self.set_parameter('set_bend', value, channel)

    def set_panning(self, value, channel):
        self.set_parameter('set_panning', value, channel)

    def set_waveform(self, value, channel):
        self.set_parameter('set_waveform', value, channel)

    def set_ring_frequency(self, value, channel):
        self.set_parameter('set_ring_frequency', value, channel)

    def set_ring_bend(self, value, channel):
        self.set_parameter('set_ring_bend', value, channel)

    def set_ring_waveform(self, value, channel):
        self.set_parameter('set_ring_waveform', value, channel)

    def set_synth_filter_low_pass_frequency(self, value, channel):
        self._current_filter_type = 'low_pass'
        self.set_parameter('filter_frequency', value, channel)

    def set_synth_filter_low_pass_resonance(self, value, channel):
        self._current_filter_type = 'low_pass'
        self.set_parameter('filter_resonance', value, channel)

    def set_synth_filter_high_pass_frequency(self, value, channel):
        self._current_filter_type = 'high_pass'
        self.set_parameter('filter_frequency', value, channel)

    def set_synth_filter_high_pass_resonance(self, value, channel):
        self._current_filter_type = 'high_pass'
        self.set_parameter('filter_resonance', value, channel)

    def set_synth_filter_band_pass_frequency(self, value, channel):
        self._current_filter_type = 'band_pass'
        self.set_parameter('filter_frequency', value, channel)

    def set_synth_filter_band_pass_resonance(self, value, channel):
        self._current_filter_type = 'band_pass'
        self.set_parameter('filter_resonance', value, channel)

    def set_synth_filter_notch_frequency(self, value, channel):
        self._current_filter_type = 'notch'
        self.set_parameter('filter_frequency', value, channel)

    def set_synth_filter_notch_resonance(self, value, channel):
        self._current_filter_type = 'notch'
        self.set_parameter('filter_resonance', value, channel)

    def set_envelope_attack_level(self, value, channel):
        self.envelope_handler.store_param('attack_level', value, channel)

    def set_envelope_attack_time(self, value, channel):
        self.envelope_handler.store_param('attack_time', value, channel)

    def set_envelope_decay_time(self, value, channel):
        self.envelope_handler.store_param('decay_time', value, channel)

    def set_envelope_sustain_level(self, value, channel):
        self.envelope_handler.store_param('sustain_level', value, channel)

    def set_envelope_release_time(self, value, channel):
        self.envelope_handler.store_param('release_time', value, channel)

    def press_voice(self, note_number, channel, note_values):
        if channel == 0:
            channel = 1
            
        for name, value in note_values.items():
            self.state.store(name, value, channel)
            
        voice = self.voice_pool.press_note(note_number, channel)
        if not voice:
            return
            
        params = self._build_note_params(channel)
        
        try:
            note = SynthioInterfaces.create_note(**params)
            self.synth.press(note)
            voice.active_note = note
            self.voice_pool.add_note_amplitude(voice)
            log(TAG_SYNTH, f"Created note {note_number} on channel {channel}")
            
        except Exception as e:
            log(TAG_SYNTH, f"Failed to create note: {str(e)}", is_error=True)
            self.voice_pool.release_note(note_number)

    def release_voice(self, note_number, channel):
        if channel == 0:
            channel = 1
            
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
        if channel < 1 or channel > 15:
            log(TAG_SYNTH, f"Invalid channel {channel}", is_error=True)
            return {}
            
        params = {}
        
        note_params = [
            'amplitude', 'bend', 'panning',
            'waveform', 'waveform_loop_start', 'waveform_loop_end',
            'ring_frequency', 'ring_bend', 'ring_waveform',
            'ring_waveform_loop_start', 'ring_waveform_loop_end'
        ]
        
        frequency = self.state.get('frequency', channel)
        if frequency is not None:
            params['frequency'] = frequency
            
        for name in note_params:
            value = self.state.get(name, channel)
            if value is not None:
                params[name] = value
                
        if 'waveform' in params and 'waveform_loop_end' not in params:
            params['waveform_loop_end'] = len(params['waveform'])
        if 'ring_waveform' in params and 'ring_waveform_loop_end' not in params:
            params['ring_waveform_loop_end'] = len(params['ring_waveform'])
            
        filter_freq = self.state.get('filter_frequency', channel)
        filter_res = self.state.get('filter_resonance', channel)
                
        if filter_freq is not None and filter_res is not None and self._current_filter_type:
            try:
                filter = SynthioInterfaces.create_filter(
                    self._current_filter_type,
                    filter_freq,
                    resonance=filter_res
                )
                params['filter'] = filter
            except Exception as e:
                log(TAG_SYNTH, f"Failed to create filter: {str(e)}", is_error=True)
                
        envelope = self.envelope_handler.get_note_envelope(channel)
        if envelope is not None:
            params['envelope'] = envelope
                    
        return params

    def store_value(self, name, value, channel):
        self.set_parameter(name, value, channel)

    def _emergency_cleanup(self):
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
                self.synth = self.setup.setup_synthio(self.state)
                self.midi_handler.setup_handlers()
                log(TAG_SYNTH, "Successfully re-initialized synthesizer after emergency")
            except Exception as e:
                log(TAG_SYNTH, f"Failed to re-initialize synth: {str(e)}", is_error=True)
                
            log(TAG_SYNTH, "Emergency cleanup complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Error during emergency cleanup: {str(e)}", is_error=True)
