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
        startup_values, lfo_params = self.router.get_startup_values()
        if not startup_values:
            return
            
        log(TAG_PATCH, "Sending startup values...")
        
        # Pass LFO params to synth store
        self.synthesizer.store.lfo_params = lfo_params
        
        # First pass: Set all LFO parameters
        for handler, config in startup_values.items():
            if handler.startswith('lfo_'):
                try:
                    value = config['value']
                    channel = 1 if config['use_channel'] else 0
                    log(TAG_PATCH, f"Setting LFO param {handler} = {format_value(value)} (channel {channel})")
                    self.synthesizer.handle_value(handler, value, channel)
                except Exception as e:
                    log(TAG_PATCH, f"Failed to set LFO param: {str(e)}", is_error=True)
        
        # Second pass: Set all other values (including LFO routing)
        for handler, config in startup_values.items():
            if not handler.startswith('lfo_'):
                try:
                    value = config['value']
                    channel = 1 if config['use_channel'] else 0
                    if handler.endswith('waveform'):
                        log(TAG_PATCH, f"Setting {handler} (channel {channel})")
                    else:
                        log(TAG_PATCH, f"Setting {handler} = {format_value(value)} (channel {channel})")
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

        # Route message to appropriate handler
        if msg.type == 'note_on' and msg.velocity > 0:
            self.handle_note_on(msg)
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            self.handle_note_off(msg)
        elif msg.type == 'cc':
            self.handle_cc(msg)
        elif msg.type == 'pitch_bend':
            self.handle_pitch_bend(msg)
        elif msg.type == 'channel_pressure':
            self.handle_pressure(msg)

    def handle_note_on(self, msg):
        """Handle note-on message using routing table."""
        # Collect note values from message attributes
        note_values = {}
        
        # First handle note-specific values from note_on mapping
        actions = self.router.midi_mappings.get('note_on', [])
        for action in actions:
            if 'route' in action:
                try:
                    converted = action['route'].convert(msg.note)
                    note_values[action['handler']] = converted
                    log(TAG_PATCH, f"note={msg.note} -> {action['handler']}={format_value(converted)}")
                except Exception as e:
                    log(TAG_PATCH, f"Failed to handle note value: {str(e)}", is_error=True)
        
        # Then process other message attributes
        for attr_name in dir(msg):
            # Skip internal attributes
            if attr_name.startswith('_'):
                continue
                
            # Get the value
            value = getattr(msg, attr_name)
            
            # Skip methods and non-data attributes
            if callable(value) or attr_name in ('type', 'channel', 'note'):
                continue
                
            # Check if this value has any routes
            actions = self.router.midi_mappings.get(attr_name, [])
            for action in actions:
                if 'route' in action:
                    try:
                        converted = action['route'].convert(value)
                        # Store converted value in note_values
                        note_values[action['handler']] = converted
                        log(TAG_PATCH, f"{attr_name}={value} -> {action['handler']}={format_value(converted)}")
                    except Exception as e:
                        log(TAG_PATCH, f"Failed to handle {attr_name}: {str(e)}", is_error=True)
        
        # Handle note_on trigger (press_note) with collected values
        actions = self.router.midi_mappings.get('note_on', [])
        for action in actions:
            if action['handler'] == 'press_note':
                # Get frequency from note_values (precomputed by router)
                frequency = note_values.get('frequency')
                if frequency is None:
                    log(TAG_PATCH, "No frequency mapping for note", is_error=True)
                    return
                    
                # Channel 0 means write to all channels
                channel = msg.channel  # Already 0 if global channel
                self.synthesizer.press_note(msg.note, frequency, channel)
                break

    def handle_note_off(self, msg):
        """Handle note-off message using routing table."""
        # First handle any values in the message
        for attr_name in dir(msg):
            # Skip internal attributes
            if attr_name.startswith('_'):
                continue
                
            # Get the value
            value = getattr(msg, attr_name)
            
            # Skip methods and non-data attributes
            if callable(value) or attr_name in ('type', 'channel'):
                continue
                
            # Check if this value has any routes
            actions = self.router.midi_mappings.get(attr_name, [])
            for action in actions:
                if 'route' in action:
                    try:
                        converted = action['route'].convert(value)
                        log(TAG_PATCH, f"{attr_name}={value} -> {action['handler']}={format_value(converted)}")
                        # Channel 0 or synth scope both mean write to all channels
                        channel = 0 if msg.channel == 0 or not action['use_channel'] else msg.channel
                        # Store value in synth
                        self.synthesizer.handle_value(action['handler'], value, channel)
                    except Exception as e:
                        log(TAG_PATCH, f"Failed to handle {attr_name}: {str(e)}", is_error=True)
        
        # Then handle note_off trigger (release_note)
        actions = self.router.midi_mappings.get('note_off', [])
        for action in actions:
            if action['handler'] == 'release_note':
                # Channel 0 means write to all channels
                channel = msg.channel  # Already 0 if global channel
                self.synthesizer.release_note(msg.note, channel)
                break

    def handle_cc(self, msg):
        """Handle CC message using routing table."""
        cc_trigger = f"cc{msg.control}"
        if msg.control in self.router.enabled_ccs:
            # Get all actions for this CC
            actions = self.router.midi_mappings.get(cc_trigger, [])
            
            # Execute each action
            for action in actions:
                try:
                    # Get value from route
                    if 'route' in action:
                        value = action['route'].convert(msg.value)
                    else:
                        value = msg.value
                        
                    # Log in a more concise way for waveforms
                    if action['handler'].endswith('waveform'):
                        log(TAG_PATCH, f"CC{msg.control} -> {action['handler']} = wave[{msg.value}]")
                    else:
                        log(TAG_PATCH, f"CC{msg.control} -> {action['handler']} = {format_value(value)}")
                    
                    # Channel 0 or synth scope both mean write to all channels
                    channel = 0 if msg.channel == 0 or not action['use_channel'] else msg.channel
                    # Store value in synth
                    self.synthesizer.handle_value(action['handler'], value, channel)
                    
                except Exception as e:
                    log(TAG_PATCH, f"Failed to handle CC: {str(e)}", is_error=True)

    def handle_pitch_bend(self, msg):
        """Handle pitch bend message using routing table."""
        if 'pitch_bend' in self.router.enabled_messages:
            # Use full 14-bit pitch bend value
            midi_value = msg.bend
            
            # Get all actions for pitch_bend
            actions = self.router.midi_mappings.get('pitch_bend', [])
            
            # Execute each action
            for action in actions:
                try:
                    # Get value from route
                    if 'route' in action:
                        value = action['route'].convert(midi_value)
                    else:
                        value = midi_value
                    
                    # Channel 0 or synth scope both mean write to all channels
                    channel = 0 if msg.channel == 0 or not action['use_channel'] else msg.channel
                    # Store value in synth
                    self.synthesizer.handle_value(action['handler'], value, channel)
                    
                except Exception as e:
                    log(TAG_PATCH, f"Failed to handle pitch bend: {str(e)}", is_error=True)

    def handle_pressure(self, msg):
        """Handle pressure message using routing table."""
        if 'channel_pressure' in self.router.enabled_messages:
            # Get all actions for channel_pressure
            actions = self.router.midi_mappings.get('channel_pressure', [])
            
            # Execute each action
            for action in actions:
                try:
                    # Get value from route
                    if 'route' in action:
                        value = action['route'].convert(msg.pressure)
                    else:
                        value = msg.pressure
                    
                    # Channel 0 or synth scope both mean write to all channels
                    channel = 0 if msg.channel == 0 or not action['use_channel'] else msg.channel
                    # Store value in synth
                    self.synthesizer.handle_value(action['handler'], value, channel)
                    
                except Exception as e:
                    log(TAG_PATCH, f"Failed to handle pressure: {str(e)}", is_error=True)
