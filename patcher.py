"""MIDI message handling and routing module."""

import sys
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
        self.synthesizer.handle_note_on(msg.note, msg.channel)

    def handle_note_off(self, msg, synth):
        log(TAG_PATCH, "Targeting {}.{} with note-off".format(msg.note, msg.channel))
        self.synthesizer.handle_note_off(msg.note, msg.channel)

    def handle_cc(self, msg, synth):
        cc_trigger = f"cc{msg.control}"
        if msg.control in self.path_parser.enabled_ccs:
            path_info = self.path_parser.midi_mappings.get(cc_trigger)
            if path_info:
                path, param_name, routing_info = path_info
                
                # Convert MIDI value using router's lookup table
                value = self.path_parser.convert_value(param_name, msg.value, routing_info['scope'] == 'global')
                log(TAG_PATCH, f"Updated {path} = {value}")
                
                # Route value based on target
                if routing_info['target'] == 'synthio.envelope':
                    self.synthesizer.update_global_envelope(param_name, value)
                elif routing_info['target'] == 'synthio.filter':
                    self.synthesizer.update_global_filter(param_name, value)
                elif routing_info['target'] == 'synthio.morph':
                    self.synthesizer.update_morph_position(value, msg.value)  # Pass both converted and MIDI value
                elif routing_info['target'] == 'synthio.ring':
                    self.synthesizer.update_ring_modulation(param_name, value)
                elif routing_info['target'] == 'voice':
                    self.synthesizer.update_voice_parameter(param_name, value)

    def handle_pitch_bend(self, msg, synth):
        if 'pitchbend' in self.path_parser.enabled_messages:
            midi_value = (msg.pitch_bend >> 7) & 0x7F
            voice = self.voice_pool.get_voice_by_channel(msg.channel)
            if voice:
                for param_name, route in self.path_parser.key_ranges.items():
                    if 'pitch_bend' in self.path_parser.midi_mappings:
                        # Convert MIDI value using router's lookup table
                        value = route.convert(midi_value)
                        # Use routing info to determine target
                        if route.routing_info['target'] == 'voice':
                            self.synthesizer.update_voice_parameter(param_name, value, voice)

    def handle_pressure(self, msg, synth):
        if 'pressure' in self.path_parser.enabled_messages:
            voice = self.voice_pool.get_voice_by_channel(msg.channel)
            if voice:
                for param_name, route in self.path_parser.key_ranges.items():
                    if 'pressure' in self.path_parser.midi_mappings:
                        # Convert MIDI value using router's lookup table
                        value = route.convert(msg.pressure)
                        # Use routing info to determine target
                        if route.routing_info['target'] == 'voice':
                            self.synthesizer.update_voice_parameter(param_name, value, voice)
