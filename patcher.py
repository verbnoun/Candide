"""MIDI message handling and routing module."""

import sys
import array
from logging import log, TAG_PATCH, format_value

class MidiHandler:
    """Handles MIDI message processing, routing, and setup."""
    def __init__(self, synthesizer):
        from router import get_router
        self.synthesizer = synthesizer
        self.router = get_router()
        self.midi_interface = None
        self.subscription = None
        self.ready_callback = None

    def on_instrument_change(self, instrument_name, config_name, paths):
        """Handle instrument change as observer."""
        log(TAG_PATCH, f"Instrument changed to: {instrument_name}")
        # Parse paths to set up MIDI routing
        self.router.parse_paths(paths, config_name)
        # Set up MIDI handlers for new paths
        self.setup_handlers()
        # Send startup values to synth
        self.send_startup_values()

    def setup_handlers(self):
        """Set up MIDI message handlers based on current paths."""
        if not self.midi_interface:
            return
            
        log(TAG_PATCH, "Setting up MIDI handlers...")
        log(TAG_PATCH, f"Enabled messages: {self.router.enabled_messages}")
            
        message_types = [msg_type for msg_type in 
                        ('note_on', 'note_off', 'cc', 'pitch_bend', 'channel_pressure')
                        if msg_type in self.router.enabled_messages]
            
        log(TAG_PATCH, f"Message types to subscribe: {message_types}")
            
        if not message_types:
            log(TAG_PATCH, "No MIDI message types enabled in paths")
            return
            
        # Create new subscription (don't remove old one)
        new_subscription = self.midi_interface.subscribe(
            self.handle_message,
            message_types=message_types,
            cc_numbers=self.router.enabled_ccs if 'cc' in self.router.enabled_messages else None
        )
        
        # Clean up old subscription after new one is created
        if self.subscription:
            self.midi_interface.unsubscribe(self.subscription)
            
        self.subscription = new_subscription
        
        log(TAG_PATCH, f"MIDI handlers configured for: {self.router.enabled_messages}")
        
        if self.ready_callback:
            log(TAG_PATCH, "Configuration complete - signaling ready")
            self.ready_callback()

    def send_startup_values(self):
        """Send startup values to synthesizer."""
        startup_values, _ = self.router.get_startup_values()
        if not startup_values:
            return
            
        log(TAG_PATCH, "Sending startup values...")
        
        # Log all startup values first
        for handler, config in startup_values.items():
            value = config['value']
            channel = 1 if config['use_channel'] else 0
            if handler.startswith('lfo_setup_'):
                lfo_setup = value
                lfo_name = lfo_setup['name']
                log(TAG_PATCH, f"Setting up LFO {lfo_name}:")
                for step, params in lfo_setup['steps']:
                    log(TAG_PATCH, f"  {step}: {format_value(params)}")
            elif handler.endswith('waveform'):
                log(TAG_PATCH, f"Setting {handler} (channel {channel})")
            else:
                log(TAG_PATCH, f"Setting {handler} = {format_value(value)} (channel {channel})")
                
        # Send all values to synth
        for handler, config in startup_values.items():
            try:
                value = config['value']
                channel = 1 if config['use_channel'] else 0
                self.synthesizer.handle_value(handler, value, channel)
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
        # Set up initial handlers
        self.setup_handlers()

    def handle_message(self, msg):
        """Log and route incoming MIDI messages."""
        # Log received MIDI message
        if msg.type == 'note_on':
            log(TAG_PATCH, "Received MIDI note-on: ch={} note={} vel={}".format(
                msg.channel, msg.note, msg.velocity))
        elif msg.type == 'note_off':
            log(TAG_PATCH, "Received MIDI note-off: ch={} note={}".format(
                msg.channel, msg.note))
        elif msg.type == 'cc':
            log(TAG_PATCH, "Received MIDI CC: ch={} cc={} val={}".format(
                msg.channel, msg.control, msg.value))
        elif msg.type == 'pitch_bend':
            log(TAG_PATCH, "Received MIDI pitch bend: ch={} val={}".format(
                msg.channel, msg.bend))
        elif msg.type == 'channel_pressure':
            log(TAG_PATCH, "Received MIDI pressure: ch={} pressure={}".format(
                msg.channel, msg.pressure))

        # Get message type and values from router
        msg_type = self.router.get_message_type(msg)
        if not msg_type:
            return
            
        # Handle note off immediately since it doesn't need values
        if msg.type == 'note_off':
            self.synthesizer.release_note(msg.note, msg.channel)
            return
            
        # Get all values for this message (including velocity for note_on)
        values = self.router.get_message_values(msg, msg_type)
        if not values:
            return
            
        # Send all values
        for handler, value in values.items():
            channel = self.router.get_channel_scope(msg, {'use_channel': True})
            log(TAG_PATCH, f"Setting {handler} = {format_value(value)} on channel {channel}")
            # Log envelope parameter routing
            if handler.startswith('attack_') or handler.startswith('decay_') or handler.startswith('release_') or handler.startswith('sustain_'):
                log(TAG_PATCH, f"Routing envelope param {handler} from {msg.type} value {msg.value if hasattr(msg, 'value') else msg.velocity}")
            self.synthesizer.handle_value(handler, value, channel)
                
        # Press note after setting values
        if msg.type == 'note_on' and 'frequency' in values:
            self.synthesizer.press_note(msg.note, values['frequency'], msg.channel)
