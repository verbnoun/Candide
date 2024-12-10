"""MIDI message handling and routing module."""

import sys
import synthio
from logging import log, TAG_PATCH

class MidiHandler:
    """Handles MIDI message processing and routing."""
    def __init__(self, synth_state, voice_pool, path_parser):
        self.synth_state = synth_state
        self.voice_pool = voice_pool
        self.path_parser = path_parser
        self.subscription = None
        self.synthesizer = None  # Set by Synthesizer class

    def handle_message(self, msg, synth):
        """Log and route incoming MIDI messages."""
        # Log received MIDI message
        if msg == 'noteon':
            log(TAG_PATCH, "Received MIDI note-on: ch={} note={} vel={}".format(
                msg.channel, msg.note, msg.velocity))
        elif msg == 'noteoff':
            log(TAG_PATCH, "Received MIDI note-off: ch={} note={}".format(
                msg.channel, msg.note))
        elif msg == 'cc':
            log(TAG_PATCH, "Received MIDI CC: ch={} cc={} val={}".format(
                msg.channel, msg.control, msg.value))
        elif msg == 'pitchbend':
            log(TAG_PATCH, "Received MIDI pitch bend: ch={} val={}".format(
                msg.channel, msg.pitch_bend))
        elif msg == 'channelpressure':
            log(TAG_PATCH, "Received MIDI pressure: ch={} val={}".format(
                msg.channel, msg.pressure))

        # Route message to appropriate handler
        if msg == 'noteon' and msg.velocity > 0:
            self.handle_note_on(msg, synth)
        elif msg == 'noteoff' or (msg == 'noteon' and msg.velocity == 0):
            self.handle_note_off(msg, synth)
        elif msg == 'cc':
            self.handle_cc(msg, synth)
        elif msg == 'pitchbend':
            self.handle_pitch_bend(msg, synth)
        elif msg == 'channelpressure':
            self.handle_pressure(msg, synth)

    def handle_note_on(self, msg, synth):
        log(TAG_PATCH, "Targeting {}.{} with note-on".format(msg.note, msg.channel))
        
        # Use waveform based on path configuration
        if 'waveform' in self.path_parser.set_values:
            waveform = self.synth_state.global_waveform
            log(TAG_PATCH, f"Using base waveform: {self.path_parser.set_values['waveform']}")
        elif self.synth_state.base_morph:
            midi_value = int(self.synth_state.get_value('morph_position') * 127)
            waveform = self.synth_state.base_morph.get_waveform(midi_value)
            log(TAG_PATCH, f"Using pre-calculated base morphed waveform at position {self.synth_state.get_value('morph_position')}")
        else:
            waveform = self.synth_state.global_waveform
        
        # Get ring waveform based on path configuration
        if self.path_parser.has_ring_mod:
            if 'ring_waveform' in self.path_parser.set_values:
                ring_waveform = self.synth_state.global_ring_waveform
                log(TAG_PATCH, f"Using ring waveform: {self.path_parser.set_values['ring_waveform']}")
            elif self.synth_state.ring_morph:
                midi_value = int(self.synth_state.get_value('ring_morph_position') * 127)
                ring_waveform = self.synth_state.ring_morph.get_waveform(midi_value)
                log(TAG_PATCH, f"Using pre-calculated ring morphed waveform at position {self.synth_state.get_value('ring_morph_position')}")
            else:
                ring_waveform = self.synth_state.global_ring_waveform
        
        # Create filter if filter type is specified
        filter_obj = None
        if self.path_parser.filter_type:
            filter_freq = self.synth_state.get_value('filter_frequency') or 0
            filter_res = self.synth_state.get_value('filter_resonance') or 0
            
            if 'frequency' in self.path_parser.global_ranges:
                filter_freq = self.path_parser.convert_value('frequency', filter_freq)
            if 'resonance' in self.path_parser.global_ranges:
                filter_res = self.path_parser.convert_value('resonance', filter_res)
                
            try:
                filter_obj = SynthioInterfaces.create_filter(
                    synth,
                    self.path_parser.filter_type,
                    filter_freq,
                    filter_res
                )
            except Exception as e:
                log(TAG_PATCH, f"Failed to create filter: {str(e)}", is_error=True)
        
        note_params = {
            'frequency': synthio.midi_to_hz(msg.note),
            'waveform': waveform
        }

        # Only add ring mod params if ring mod is enabled
        if self.path_parser.has_ring_mod:
            note_params.update({
                'ring_frequency': self.synth_state.get_value('ring_frequency') or 0,
                'ring_waveform': ring_waveform,
                'ring_bend': self.synth_state.get_value('ring_bend') or 0
            })
        
        # Only add filter if it was created successfully
        if filter_obj:
            note_params['filter'] = filter_obj
        
        self.synthesizer.handle_note_on(msg.note, msg.channel, **note_params)

    def handle_note_off(self, msg, synth):
        log(TAG_PATCH, "Targeting {}.{} with note-off".format(msg.note, msg.channel))
        self.synthesizer.handle_note_off(msg.note, msg.channel)

    def handle_cc(self, msg, synth):
        cc_trigger = f"cc{msg.control}"
        if msg.control in self.path_parser.enabled_ccs:
            path_info = self.path_parser.midi_mappings.get(cc_trigger)
            if path_info:
                original_path, param_name = path_info
                path_parts = original_path.split('/')
                
                if (path_parts[0] == 'oscillator' and 
                    path_parts[1] == 'ring' and 
                    path_parts[2] == 'waveform' and 
                    path_parts[3] == 'morph'):
                    param_name = 'ring_morph'
                    
                value = self.path_parser.convert_value(param_name, msg.value, True)
                log(TAG_PATCH, "Updated {} = {}".format(original_path, value))
                
                self._handle_parameter_update(path_parts, param_name, value, msg.value, synth)

    def handle_pitch_bend(self, msg, synth):
        if 'pitchbend' in self.path_parser.enabled_messages:
            midi_value = (msg.pitch_bend >> 7) & 0x7F
            voice = self.voice_pool.get_voice_by_channel(msg.channel)
            if voice:
                for param_name, range_obj in self.path_parser.key_ranges.items():
                    if 'pitch_bend' in self.path_parser.midi_mappings:
                        value = range_obj.convert(midi_value)
                        if param_name == 'bend':
                            self.synthesizer.handle_voice_update(voice, bend=value)
                        elif param_name == 'panning':
                            self.synthesizer.handle_voice_update(voice, panning=value)

    def handle_pressure(self, msg, synth):
        if 'pressure' in self.path_parser.enabled_messages:
            voice = self.voice_pool.get_voice_by_channel(msg.channel)
            if voice:
                for param_name, range_obj in self.path_parser.key_ranges.items():
                    if 'pressure' in self.path_parser.midi_mappings:
                        value = range_obj.convert(msg.pressure)
                        if param_name == 'amplitude':
                            self.synthesizer.handle_voice_update(voice, amplitude=value)

    def _handle_parameter_update(self, path_parts, param_name, value, midi_value, synth):
        """Handle updates to various parameter types."""
        # Base waveform morph
        if (path_parts[0] == 'oscillator' and 
            path_parts[1] == 'waveform' and 
            path_parts[2] == 'morph'):
            self.synth_state.update_value('morph_position', value)
            if self.synth_state.base_morph:
                new_waveform = self.synth_state.base_morph.get_waveform(midi_value)
                for voice in self.voice_pool.voices:
                    if voice.is_active():
                        self.synthesizer.handle_voice_update(voice, waveform=new_waveform)
                
        # Ring waveform morph
        elif (path_parts[0] == 'oscillator' and 
              path_parts[1] == 'ring' and 
              path_parts[2] == 'waveform' and 
              path_parts[3] == 'morph'):
            self.synth_state.update_value('ring_morph_position', value)
            if self.synth_state.ring_morph:
                new_ring_waveform = self.synth_state.ring_morph.get_waveform(midi_value)
                for voice in self.voice_pool.voices:
                    if voice.is_active():
                        self.synthesizer.handle_voice_update(voice, ring_waveform=new_ring_waveform)
                
        # Other parameters (ring frequency, bend, envelope, filter)
        elif param_name in ('ring_frequency', 'ring_bend', 'attack_time', 'decay_time', 
                          'release_time', 'attack_level', 'sustain_level', 'frequency', 'resonance'):
            self._update_parameter_value(param_name, value, synth)

    def _update_parameter_value(self, param_name, value, synth):
        """Update specific parameter values and apply changes."""
        if param_name == 'ring_frequency':
            self.synth_state.update_value('ring_frequency', value)
            for voice in self.voice_pool.voices:
                if voice.is_active():
                    self.synthesizer.handle_voice_update(voice, ring_frequency=value)
        elif param_name == 'ring_bend':
            self.synth_state.update_value('ring_bend', value)
            for voice in self.voice_pool.voices:
                if voice.is_active():
                    self.synthesizer.handle_voice_update(voice, ring_bend=value)
        elif param_name in ('attack_time', 'decay_time', 'release_time', 'attack_level', 'sustain_level'):
            self.synth_state.update_value(param_name, value)
            synth.envelope = self.synthesizer._create_envelope()
        elif param_name in ('frequency', 'resonance'):
            self.synth_state.update_value(f'filter_{param_name}', value)
            self._update_filter_params(synth)

    def _update_filter_params(self, synth):
        """Update filter parameters for all active voices."""
        if not self.path_parser.filter_type:
            return
            
        # Convert filter parameters using ranges if available
        filter_freq = self.synth_state.get_value('filter_frequency') or 0
        filter_res = self.synth_state.get_value('filter_resonance') or 0
        
        if 'frequency' in self.path_parser.global_ranges:
            filter_freq = self.path_parser.convert_value('frequency', filter_freq)
        if 'resonance' in self.path_parser.global_ranges:
            filter_res = self.path_parser.convert_value('resonance', filter_res)
            
        for voice in self.voice_pool.voices:
            if voice.is_active():
                try:
                    new_filter = SynthioInterfaces.create_filter(
                        synth,
                        self.path_parser.filter_type,
                        filter_freq,
                        filter_res
                    )
                    self.synthesizer.handle_voice_update(voice, filter=new_filter)
                except Exception as e:
                    log(TAG_PATCH, f"Failed to update filter: {str(e)}", is_error=True)
