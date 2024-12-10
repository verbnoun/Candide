"""MIDI message handling and routing module."""

import sys
from logging import log, TAG_PATCH

class MidiHandler:
    """Handles MIDI message processing and routing."""
    def __init__(self, synth_state, voice_pool, path_parser):
        self.synth_state = synth_state
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
        """Handle note-on message using routing table."""
        # Get note number from MIDI (pass through)
        note_number = msg.note
        log(TAG_PATCH, "Targeting {}.{} with note-on".format(note_number, msg.channel))
        
        # Get all actions for note_on
        actions = self.path_parser.midi_mappings.get('note_on', [])
        
        # First handle press action
        for action in actions:
            if 'action' in action and action['action'] == 'press':
                if action['handler'] == 'handle_press':
                    # Let synthesizer handle voice creation and note press
                    self.synthesizer.handle_note_on(note_number, msg.channel)
                    break
                    
        # Then handle all other actions
        for action in actions:
            if 'action' not in action and action['handler'] != 'handle_press':  # Skip press action
                # Get value based on source/lookup/value
                if 'source' in action:
                    if action['source'] == 'note_number':
                        value = note_number
                    elif action['source'] == 'velocity':
                        value = msg.velocity
                elif 'lookup' in action:
                    value = action['lookup'].convert(msg.note)
                else:
                    value = action['value']
                    
                # Route to appropriate handler
                handler = getattr(self.synthesizer, action['handler'])
                if action['scope'] == 'per_key':
                    handler(action['target'], value, msg.channel)  # Pass channel
                else:
                    handler(action['target'], value)

    def handle_note_off(self, msg, synth):
        """Handle note-off message using routing table."""
        # Get note number from MIDI (pass through)
        note_number = msg.note
        log(TAG_PATCH, "Targeting {}.{} with note-off".format(note_number, msg.channel))
        
        # Get all actions for note_off
        actions = self.path_parser.midi_mappings.get('note_off', [])
        
        # First handle release action
        for action in actions:
            if 'action' in action and action['action'] == 'release':
                if action['handler'] == 'handle_release':
                    # Let synthesizer handle voice release
                    self.synthesizer.handle_note_off(note_number, msg.channel)
                    break
                    
        # Then handle any other actions
        for action in actions:
            if 'action' not in action and action['handler'] != 'handle_release':  # Skip release action
                # Get value based on source/lookup/value
                if 'source' in action:
                    if action['source'] == 'velocity':
                        value = msg.velocity
                elif 'lookup' in action:
                    value = action['lookup'].convert(msg.velocity)
                else:
                    value = action['value']
                    
                # Route to appropriate handler
                handler = getattr(self.synthesizer, action['handler'])
                if action['scope'] == 'per_key':
                    handler(action['target'], value, msg.channel)  # Pass channel
                else:
                    handler(action['target'], value)

    def handle_cc(self, msg, synth):
        """Handle CC message using routing table."""
        cc_trigger = f"cc{msg.control}"
        if msg.control in self.path_parser.enabled_ccs:
            # Get all actions for this CC
            actions = self.path_parser.midi_mappings.get(cc_trigger, [])
            
            # Execute each action
            for action in actions:
                # Get value based on lookup/value
                if 'lookup' in action:
                    value = action['lookup'].convert(msg.value)
                else:
                    value = action['value']
                    
                log(TAG_PATCH, f"CC{msg.control} -> {action['target']} = {value}")
                
                # Route to appropriate handler
                handler = getattr(self.synthesizer, action['handler'])
                if action['scope'] == 'per_key':
                    handler(action['target'], value, msg.channel)  # Pass channel
                else:
                    handler(action['target'], value)

    def handle_pitch_bend(self, msg, synth):
        """Handle pitch bend message using routing table."""
        if 'pitchbend' in self.path_parser.enabled_messages:
            midi_value = (msg.pitch_bend >> 7) & 0x7F
            
            # Get all actions for pitch_bend
            actions = self.path_parser.midi_mappings.get('pitch_bend', [])
            
            # Execute each action
            for action in actions:
                # Get value based on lookup
                if 'lookup' in action:
                    value = action['lookup'].convert(midi_value)
                    
                    # Route to appropriate handler
                    handler = getattr(self.synthesizer, action['handler'])
                    if action['scope'] == 'per_key':
                        handler(action['target'], value, msg.channel)  # Pass channel
                    else:
                        handler(action['target'], value)

    def handle_pressure(self, msg, synth):
        """Handle pressure message using routing table."""
        if 'pressure' in self.path_parser.enabled_messages:
            # Get all actions for pressure
            actions = self.path_parser.midi_mappings.get('pressure', [])
            
            # Execute each action
            for action in actions:
                # Get value based on lookup
                if 'lookup' in action:
                    value = action['lookup'].convert(msg.pressure)
                    
                    # Route to appropriate handler
                    handler = getattr(self.synthesizer, action['handler'])
                    if action['scope'] == 'per_key':
                        handler(action['target'], value, msg.channel)  # Pass channel
                    else:
                        handler(action['target'], value)
