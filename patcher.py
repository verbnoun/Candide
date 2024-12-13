"""MIDI message handling and routing module."""

import sys
import array
from logging import log, TAG_PATCH

class MidiHandler:
    """Handles MIDI message processing, routing, and setup."""
    def __init__(self, synth_state, path_parser):
        self.synth_state = synth_state
        self.path_parser = path_parser
        self.midi_interface = None
        self.subscription = None
        self.synthesizer = None  # Set by Synthesizer class
        self.ready_callback = None

    def setup_handlers(self):
        """Set up MIDI message handlers."""
        if self.subscription:
            self.midi_interface.unsubscribe(self.subscription)
            self.subscription = None
            
        log(TAG_PATCH, "Setting up MIDI handlers...")
            
        message_types = [msg_type for msg_type in 
                        ('noteon', 'noteoff', 'cc', 'pitchbend', 'channelpressure')
                        if msg_type in self.path_parser.enabled_messages]
            
        if not message_types:
            raise ValueError("No MIDI message types enabled in paths")
            
        self.subscription = self.midi_interface.subscribe(
            self.handle_message,
            message_types=message_types,
            cc_numbers=self.path_parser.enabled_ccs if 'cc' in self.path_parser.enabled_messages else None
        )
        log(TAG_PATCH, f"MIDI handlers configured for: {self.path_parser.enabled_messages}")
        
        if self.ready_callback:
            log(TAG_PATCH, "Configuration complete - signaling ready")
            self.ready_callback()

    def send_set_values(self):
        """Send set values to targets."""
        actions = self.path_parser.midi_mappings.get('set', [])
        if not actions:
            return
            
        log(TAG_PATCH, "Sending set values...")
        for action in actions:
            try:
                # Get the handler method from synthesizer
                handler = getattr(self.synthesizer, action['handler'])
                
                # Get value from lookup table
                if 'lookup' in action:
                    # For waveforms, use whole buffer
                    if action.get('is_waveform'):
                        value = action['lookup']
                    # For numeric tables, use index 0
                    else:
                        value = action['lookup'][0]
                else:
                    value = None
                
                log(TAG_PATCH, f"Setting {action['target']} = {value}")
                
                # Special case for waveform updates which only take the buffer
                if action['handler'] == 'update_global_waveform':
                    handler(value)
                else:
                    # Only include channel if router says to
                    channel = 0 if 'use_channel' in action else None
                    handler(action['target'], value, channel)
                        
            except Exception as e:
                log(TAG_PATCH, f"Failed to send set value: {str(e)}", is_error=True)

    def cleanup(self):
        """Clean up MIDI subscription."""
        if self.subscription:
            self.midi_interface.unsubscribe(self.subscription)
            self.subscription = None
            log(TAG_PATCH, "Unsubscribed from MIDI messages")

    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready."""
        self.ready_callback = callback
        log(TAG_PATCH, "Ready callback registered")

    def set_midi_interface(self, midi_interface):
        """Set the MIDI interface to use."""
        self.midi_interface = midi_interface
        log(TAG_PATCH, "MIDI interface set")

    def handle_message(self, msg):
        """Log and route incoming MIDI messages."""
        # Log received MIDI message
        if msg.type == 'noteon':
            log(TAG_PATCH, "Received MIDI note-on: ch={} note={} vel={}".format(
                msg.channel, msg.note, msg.velocity))
        elif msg.type == 'noteoff':
            log(TAG_PATCH, "Received MIDI note-off: ch={} note={}".format(
                msg.channel, msg.note))
        elif msg.type == 'cc':
            log(TAG_PATCH, "Received MIDI CC: ch={} cc={} val={}".format(
                msg.channel, msg.control, msg.value))
        elif msg.type == 'pitchbend':
            log(TAG_PATCH, "Received MIDI pitch bend: ch={} val={}".format(
                msg.channel, msg.pitch_bend))
        elif msg.type == 'channelpressure':
            log(TAG_PATCH, "Received MIDI pressure: ch={} val={}".format(
                msg.channel, msg.pressure))

        # Route message to appropriate handler
        if msg.type == 'noteon' and msg.velocity > 0:
            self.handle_note_on(msg)
        elif msg.type == 'noteoff' or (msg.type == 'noteon' and msg.velocity == 0):
            self.handle_note_off(msg)
        elif msg.type == 'cc':
            self.handle_cc(msg)
        elif msg.type == 'pitchbend':
            self.handle_pitch_bend(msg)
        elif msg.type == 'channelpressure':
            self.handle_pressure(msg)

    def handle_note_on(self, msg):
        """Handle note-on message using routing table."""
        note_number = msg.note
        log(TAG_PATCH, "Targeting {}.{} with note-on".format(note_number, msg.channel))
        
        # Get all actions for note_on
        actions = self.path_parser.midi_mappings.get('note_on', [])
        
        # Collect values defined by actions
        note_values = {}
        
        # Process non-press actions first to collect values
        for action in actions:
            if not 'action' in action:
                # Get value from lookup table
                if 'lookup' in action:
                    # For waveforms, use whole buffer
                    if action.get('is_waveform'):
                        value = action['lookup']
                    # For numeric tables, use input value
                    else:
                        input_value = msg.note if action['target'] == 'frequency' else msg.velocity
                        value = action['lookup'][input_value]
                else:
                    value = None
                note_values[action['target']] = value
        
        # Now handle press action with collected values
        for action in actions:
            if 'action' in action and action['action'] == 'press':
                if action['handler'] == 'handle_press':
                    # Pass note number, channel, and any collected values
                    self.synthesizer.press(note_number, msg.channel, note_values)
                    break

    def handle_note_off(self, msg):
        """Handle note-off message using routing table."""
        note_number = msg.note
        log(TAG_PATCH, "Targeting {}.{} with note-off".format(note_number, msg.channel))
        
        # Get all actions for note_off
        actions = self.path_parser.midi_mappings.get('note_off', [])
        
        # Collect values defined by actions
        note_values = {}
        
        # Process non-release actions first to collect values
        for action in actions:
            if not 'action' in action:
                # Get value from lookup table
                if 'lookup' in action:
                    # For waveforms, use whole buffer
                    if action.get('is_waveform'):
                        value = action['lookup']
                    # For numeric tables, use input value
                    else:
                        value = action['lookup'][msg.velocity]
                else:
                    value = None
                note_values[action['target']] = value
        
        # Now handle release action with collected values
        for action in actions:
            if 'action' in action and action['action'] == 'release':
                if action['handler'] == 'handle_release':
                    # Pass note number, channel, and any collected values
                    self.synthesizer.release(note_number, msg.channel, note_values)
                    break

    def handle_cc(self, msg):
        """Handle CC message using routing table."""
        cc_trigger = f"cc{msg.control}"
        if msg.control in self.path_parser.enabled_ccs:
            # Get all actions for this CC
            actions = self.path_parser.midi_mappings.get(cc_trigger, [])
            
            # Execute each action
            for action in actions:
                # Get value from lookup table
                if 'lookup' in action:
                    # For waveforms, use whole buffer
                    if action.get('is_waveform'):
                        value = action['lookup']
                    # For numeric tables, use input value
                    else:
                        value = action['lookup'][msg.value]
                else:
                    value = None
                    
                log(TAG_PATCH, f"CC{msg.control} -> {action['target']} = {value}")
                
                # Route to appropriate handler
                handler = getattr(self.synthesizer, action['handler'])
                
                # Special case for waveform updates which only take the buffer
                if action['handler'] == 'update_global_waveform':
                    handler(value)
                else:
                    # Only include channel if router says to
                    channel = msg.channel if 'use_channel' in action else None
                    handler(action['target'], value, channel)

    def handle_pitch_bend(self, msg):
        """Handle pitch bend message using routing table."""
        if 'pitchbend' in self.path_parser.enabled_messages:
            # Use full 14-bit pitch bend value
            midi_value = msg.pitch_bend
            
            # Get all actions for pitch_bend
            actions = self.path_parser.midi_mappings.get('pitch_bend', [])
            
            # Execute each action
            for action in actions:
                # Get value from lookup table
                if 'lookup' in action:
                    # For waveforms, use whole buffer
                    if action.get('is_waveform'):
                        value = action['lookup']
                    # For numeric tables, use input value
                    else:
                        value = action['lookup'][midi_value]
                else:
                    value = None
                
                # Route to appropriate handler
                handler = getattr(self.synthesizer, action['handler'])
                
                # Only include channel if router says to
                channel = msg.channel if 'use_channel' in action else None
                handler(action['target'], value, channel)

    def handle_pressure(self, msg):
        """Handle pressure message using routing table."""
        if 'channelpressure' in self.path_parser.enabled_messages:
            # Get all actions for channelpressure
            actions = self.path_parser.midi_mappings.get('channelpressure', [])
            
            # Execute each action
            for action in actions:
                # Get value from lookup table
                if 'lookup' in action:
                    # For waveforms, use whole buffer
                    if action.get('is_waveform'):
                        value = action['lookup']
                    # For numeric tables, use input value
                    else:
                        value = action['lookup'][msg.pressure]
                else:
                    value = None
                
                # Route to appropriate handler
                handler = getattr(self.synthesizer, action['handler'])
                
                # Only include channel if router says to
                channel = msg.channel if 'use_channel' in action else None
                handler(action['target'], value, channel)
