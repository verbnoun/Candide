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

    def send_startup_values(self):
        """Send startup values to synthesizer."""
        startup_values = self.path_parser.get_startup_values()
        if not startup_values:
            return
            
        log(TAG_PATCH, "Sending startup values...")
        for handler, value in startup_values.items():
            try:
                # Get the handler method from synthesizer
                method = getattr(self.synthesizer, handler)
                log(TAG_PATCH, f"Setting {handler} = {value}")
                method(value)
            except Exception as e:
                log(TAG_PATCH, f"Failed to send startup value: {str(e)}", is_error=True)

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
        
        # Process press_voice handler
        for action in actions:
            if action['handler'] == 'press_voice':
                # Call press_voice on synthesizer
                self.synthesizer.press_voice(note_number, msg.channel, {})
                break

    def handle_note_off(self, msg):
        """Handle note-off message using routing table."""
        note_number = msg.note
        log(TAG_PATCH, "Targeting {}.{} with note-off".format(note_number, msg.channel))
        
        # Get all actions for note_off
        actions = self.path_parser.midi_mappings.get('note_off', [])
        
        # Process release_voice handler
        for action in actions:
            if action['handler'] == 'release_voice':
                # Call release_voice on synthesizer
                self.synthesizer.release_voice(note_number, msg.channel)
                break

    def handle_cc(self, msg):
        """Handle CC message using routing table."""
        cc_trigger = f"cc{msg.control}"
        if msg.control in self.path_parser.enabled_ccs:
            # Get all actions for this CC
            actions = self.path_parser.midi_mappings.get(cc_trigger, [])
            
            # Execute each action
            for action in actions:
                try:
                    # Get value from route
                    if 'route' in action:
                        value = action['route'].convert(msg.value)
                    else:
                        value = msg.value
                        
                    log(TAG_PATCH, f"CC{msg.control} -> {action['handler']} = {value}")
                    
                    # Get handler method from synthesizer
                    handler = getattr(self.synthesizer, action['handler'])
                    
                    # Call handler with value and channel if scope is channel
                    channel = msg.channel if action['scope'] == 'channel' else None
                    handler(value, channel)
                    
                except Exception as e:
                    log(TAG_PATCH, f"Failed to handle CC: {str(e)}", is_error=True)

    def handle_pitch_bend(self, msg):
        """Handle pitch bend message using routing table."""
        if 'pitchbend' in self.path_parser.enabled_messages:
            # Use full 14-bit pitch bend value
            midi_value = msg.pitch_bend
            
            # Get all actions for pitch_bend
            actions = self.path_parser.midi_mappings.get('pitch_bend', [])
            
            # Execute each action
            for action in actions:
                try:
                    # Get value from route
                    if 'route' in action:
                        value = action['route'].convert(midi_value)
                    else:
                        value = midi_value
                    
                    # Get handler method from synthesizer
                    handler = getattr(self.synthesizer, action['handler'])
                    
                    # Call handler with value and channel if scope is channel
                    channel = msg.channel if action['scope'] == 'channel' else None
                    handler(value, channel)
                    
                except Exception as e:
                    log(TAG_PATCH, f"Failed to handle pitch bend: {str(e)}", is_error=True)

    def handle_pressure(self, msg):
        """Handle pressure message using routing table."""
        if 'channelpressure' in self.path_parser.enabled_messages:
            # Get all actions for channelpressure
            actions = self.path_parser.midi_mappings.get('channelpressure', [])
            
            # Execute each action
            for action in actions:
                try:
                    # Get value from route
                    if 'route' in action:
                        value = action['route'].convert(msg.pressure)
                    else:
                        value = msg.pressure
                    
                    # Get handler method from synthesizer
                    handler = getattr(self.synthesizer, action['handler'])
                    
                    # Call handler with value and channel if scope is channel
                    channel = msg.channel if action['scope'] == 'channel' else None
                    handler(value, channel)
                    
                except Exception as e:
                    log(TAG_PATCH, f"Failed to handle pressure: {str(e)}", is_error=True)
