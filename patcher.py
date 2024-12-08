"""MIDI message handling and routing module."""

import sys
import synthio
from modules import create_waveform
from constants import (
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

class MidiHandler:
    """Handles MIDI message processing and routing."""
    def __init__(self, synth_state, voice_pool, path_parser):
        self.synth_state = synth_state
        self.voice_pool = voice_pool
        self.path_parser = path_parser
        self.subscription = None

    def handle_message(self, msg, synth):
        """Log and route incoming MIDI messages."""
        # Log received MIDI message
        if msg == 'noteon':
            _log("Received MIDI note-on: ch={} note={} vel={}".format(
                msg.channel, msg.note, msg.velocity))
        elif msg == 'noteoff':
            _log("Received MIDI note-off: ch={} note={}".format(
                msg.channel, msg.note))
        elif msg == 'cc':
            _log("Received MIDI CC: ch={} cc={} val={}".format(
                msg.channel, msg.control, msg.value))
        elif msg == 'pitchbend':
            _log("Received MIDI pitch bend: ch={} val={}".format(
                msg.channel, msg.pitch_bend))
        elif msg == 'channelpressure':
            _log("Received MIDI pressure: ch={} val={}".format(
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
        _log("Targeting {}.{} with note-on".format(msg.note, msg.channel))
        
        # Use waveform based on path configuration
        if 'waveform' in self.path_parser.fixed_values:
            waveform = create_waveform(self.path_parser.fixed_values['waveform'])
            _log(f"Using fixed base waveform: {self.path_parser.fixed_values['waveform']}")
        elif self.synth_state.base_morph:
            midi_value = int(self.path_parser.current_morph_position * 127)
            waveform = self.synth_state.base_morph.get_waveform(midi_value)
            _log(f"Using pre-calculated base morphed waveform at position {self.path_parser.current_morph_position}")
        else:
            waveform = self.synth_state.global_waveform
        
        # Create ring waveform based on path configuration
        if self.path_parser.current_ring_params['waveform']:
            ring_waveform = create_waveform(self.path_parser.current_ring_params['waveform'])
            _log(f"Using fixed ring waveform: {self.path_parser.current_ring_params['waveform']}")
        elif self.synth_state.ring_morph:
            midi_value = int(self.path_parser.current_ring_morph_position * 127)
            ring_waveform = self.synth_state.ring_morph.get_waveform(midi_value)
            _log(f"Using pre-calculated ring morphed waveform at position {self.path_parser.current_ring_morph_position}")
        else:
            ring_waveform = self.synth_state.global_ring_waveform
        
        note_params = {
            'frequency': synthio.midi_to_hz(msg.note),
            'waveform': waveform,
            'filter_type': self.path_parser.filter_type,
            'filter_frequency': self.path_parser.current_filter_params['frequency'],
            'filter_resonance': self.path_parser.current_filter_params['resonance'],
            'ring_frequency': self.path_parser.current_ring_params['frequency'],
            'ring_waveform': ring_waveform,
            'ring_bend': self.path_parser.current_ring_params['bend']
        }
        
        self.voice_pool.press_note(msg.note, msg.channel, synth, **note_params)

    def handle_note_off(self, msg, synth):
        _log("Targeting {}.{} with note-off".format(msg.note, msg.channel))
        voice = self.voice_pool.release_note(msg.note, synth)
        if not voice:
            _log("No voice found at {}.{}".format(msg.note, msg.channel), is_error=True)

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
                _log("Updated {} = {}".format(original_path, value))
                
                self._handle_parameter_update(path_parts, param_name, value, msg.value, synth)

    def handle_pitch_bend(self, msg, synth):
        if 'pitchbend' in self.path_parser.enabled_messages:
            midi_value = (msg.pitch_bend >> 7) & 0x7F
            voice = self.voice_pool.get_voice_by_channel(msg.channel)
            if voice and voice.active_note:
                for param_name, range_obj in self.path_parser.key_ranges.items():
                    if 'pitch_bend' in self.path_parser.midi_mappings:
                        value = range_obj.convert(midi_value)
                        if param_name == 'bend':
                            voice.update_active_note(synth, bend=value)
                        elif param_name == 'panning':
                            voice.update_active_note(synth, panning=value)

    def handle_pressure(self, msg, synth):
        if 'pressure' in self.path_parser.enabled_messages:
            voice = self.voice_pool.get_voice_by_channel(msg.channel)
            if voice and voice.active_note:
                for param_name, range_obj in self.path_parser.key_ranges.items():
                    if 'pressure' in self.path_parser.midi_mappings:
                        value = range_obj.convert(msg.pressure)
                        if param_name == 'amplitude':
                            voice.update_active_note(synth, amplitude=value)

    def _handle_parameter_update(self, path_parts, param_name, value, midi_value, synth):
        """Handle updates to various parameter types."""
        # Base waveform morph
        if (path_parts[0] == 'oscillator' and 
            path_parts[1] == 'waveform' and 
            path_parts[2] == 'morph'):
            self.path_parser.current_morph_position = value
            if self.synth_state.base_morph:
                new_waveform = self.synth_state.base_morph.get_waveform(midi_value)
                self._update_all_voices(synth, waveform=new_waveform)
                
        # Ring waveform morph
        elif (path_parts[0] == 'oscillator' and 
              path_parts[1] == 'ring' and 
              path_parts[2] == 'waveform' and 
              path_parts[3] == 'morph'):
            self.path_parser.current_ring_morph_position = value
            if self.synth_state.ring_morph:
                new_ring_waveform = self.synth_state.ring_morph.get_waveform(midi_value)
                self._update_all_voices(synth, ring_waveform=new_ring_waveform)
                
        # Other parameters (ring frequency, bend, envelope, filter)
        elif param_name in ('ring_frequency', 'ring_bend', 'attack_time', 'decay_time', 
                          'release_time', 'attack_level', 'sustain_level', 'frequency', 'resonance'):
            self._update_parameter_value(param_name, value, synth)

    def _update_all_voices(self, synth, **params):
        """Update all active voices with new parameters."""
        for voice in self.voice_pool.voices:
            if voice.active_note:
                voice.update_active_note(synth, **params)

    def _update_parameter_value(self, param_name, value, synth):
        """Update specific parameter values and apply changes."""
        if param_name == 'ring_frequency':
            self.path_parser.current_ring_params['frequency'] = value
            self._update_all_voices(synth, ring_frequency=value)
        elif param_name == 'ring_bend':
            self.path_parser.current_ring_params['bend'] = value
            self._update_all_voices(synth, ring_bend=value)
        elif param_name in ('attack_time', 'decay_time', 'release_time', 'attack_level', 'sustain_level'):
            self.path_parser.current_envelope_params[param_name] = value
            synth.envelope = self.path_parser.update_envelope()
        elif param_name in ('frequency', 'resonance'):
            self.path_parser.current_filter_params[param_name] = value
            self._update_filter_params(synth)

    def _update_filter_params(self, synth):
        """Update filter parameters for all active voices."""
        for voice in self.voice_pool.voices:
            if voice.active_note:
                voice.update_active_note(synth,
                    filter_type=self.path_parser.filter_type,
                    filter_frequency=self.path_parser.current_filter_params['frequency'],
                    filter_resonance=self.path_parser.current_filter_params['resonance'])
