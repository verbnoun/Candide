"""MIDI interface system providing MIDI message handling and MPE support with filtering."""

from constants import LOG_MIDI, LOG_LIGHT_ORANGE, LOG_RED, LOG_RESET, MidiMessageType
import supervisor

# MIDI Message Types
MIDI_NOTE_OFF = 0x80          # Note Off
MIDI_NOTE_ON = 0x90           # Note On
MIDI_POLY_PRESSURE = 0xA0     # Polyphonic Key Pressure
MIDI_CONTROL_CHANGE = 0xB0    # Control Change
MIDI_CHANNEL_PRESSURE = 0xD0  # Channel Pressure
MIDI_PITCH_BEND = 0xE0        # Pitch Bend
MIDI_SYSTEM_MESSAGE = 0xF0    # System Message

# MPE Configuration
MPE_LOWER_ZONE_MASTER = 0  # Channel 1
MPE_UPPER_ZONE_MASTER = 15  # Channel 16
MPE_TIMBRE_CC = 74

# MPE Filtering Configuration
MPE_FILTER_CONFIG = {
    'max_messages_per_second': 0, #20 # Total MPE messages across all channels
    'pitch_bend_ratio': 50,    # 50% of remaining bandwidth
    'pressure_ratio': 30,      # 30% of remaining bandwidth
    'timbre_ratio': 20,        # 20% of remaining bandwidth
    'pitch_bend_threshold': 64,  # ~1% of total range (0-16383)
    'pressure_threshold': 4,     # ~3% of total range (0-127)
    'timbre_threshold': 4        # ~3% of total range (0-127)
}

def _log(message, is_error=False, is_debug=False):
    """Log messages with MIDI prefix"""
    color = LOG_RED if is_error else LOG_LIGHT_ORANGE
    prefix = "[ERROR] " if is_error else ""
    print("{}{}".format(color, LOG_MIDI) + prefix + " " + message + LOG_RESET)

class MPEMessageCounter:
    """Tracks MPE message counts globally and per channel"""
    def __init__(self):
        self.reset_counters()
        self.last_reset_time = supervisor.ticks_ms()
        
    def reset_counters(self):
        """Reset all message counters"""
        self.total_messages = 0
        self.pitch_bend_messages = 0
        self.pressure_messages = 0
        self.timbre_messages = 0
        self.channel_messages = {}
        for ch in range(16):
            self.channel_messages[ch] = 0
        
    def update_rate_limits(self):
        """Check and reset counters based on time"""
        current_time = supervisor.ticks_ms()
        if (current_time - self.last_reset_time) >= 1000:  # 1 second in ms
            self.reset_counters()
            self.last_reset_time = current_time
            
    def can_process_message(self, msg_type):
        """Check if a message can be processed based on ratios and limits"""
        self.update_rate_limits()
        
        # Note messages are always processed
        if msg_type in ['noteon', 'noteoff']:
            return True
            
        # Check total message limit
        if self.total_messages >= MPE_FILTER_CONFIG['max_messages_per_second']:
            return False
            
        # Calculate available slots for each type
        available_slots = MPE_FILTER_CONFIG['max_messages_per_second'] - self.total_messages
        
        if msg_type == 'pitchbend':
            max_allowed = (available_slots * MPE_FILTER_CONFIG['pitch_bend_ratio']) // 100
            return self.pitch_bend_messages < max_allowed
        elif msg_type == 'channelpressure':
            max_allowed = (available_slots * MPE_FILTER_CONFIG['pressure_ratio']) // 100
            return self.pressure_messages < max_allowed
        elif msg_type == 'cc':  # Timbre
            max_allowed = (available_slots * MPE_FILTER_CONFIG['timbre_ratio']) // 100
            return self.timbre_messages < max_allowed
            
        return True
        
    def count_message(self, msg_type, channel):
        """Count a processed message"""
        self.total_messages += 1
        self.channel_messages[channel] += 1
        
        if msg_type == 'pitchbend':
            self.pitch_bend_messages += 1
        elif msg_type == 'channelpressure':
            self.pressure_messages += 1
        elif msg_type == 'cc':  # Timbre
            self.timbre_messages += 1
            
    def get_channel_stats(self, channel):
        """Get message statistics for a channel"""
        return {
            'total': self.channel_messages[channel],
            'pitch_bend': self.pitch_bend_messages,
            'pressure': self.pressure_messages,
            'timbre': self.timbre_messages
        }

class MidiSubscription:
    """Filtered MIDI message subscription"""
    def __init__(self, callback, message_types=None, channels=None, cc_numbers=None):
        self.callback = callback
        self.message_types = message_types if message_types is not None else []
        self.channels = set(channels) if channels is not None else None
        self.cc_numbers = set(cc_numbers) if cc_numbers is not None else None
        _log("Created subscription for types=" + str(message_types) + " channels=" + str(channels) + " cc=" + str(cc_numbers))

    def matches(self, message):
        """Check if a MIDI message matches this subscription's filters."""
        if self.message_types and message.type not in self.message_types:
            return False
            
        if self.channels is not None and message.channel not in self.channels:
            return False
            
        if message.type == 'cc' and self.cc_numbers is not None:
            return message.control in self.cc_numbers
            
        return True

class MPEZone:
    """Manages an MPE zone (lower or upper)"""
    def __init__(self, is_lower_zone=True):
        self.is_lower_zone = is_lower_zone
        self.master_channel = MPE_LOWER_ZONE_MASTER if is_lower_zone else MPE_UPPER_ZONE_MASTER
        
        self.member_channels = list(range(1, 15))  # Channels 2-15
        
        # Initialize per-channel state
        self.channel_states = {}
        for channel in self.member_channels:
            self.channel_states[channel] = {
                'active_notes': {},  # note_num: velocity
                'pressure': 0,
                'timbre': 64,  # CC 74
                'pitch_bend': 8192  # 14-bit centered
            }
            
    def get_physical_channel(self, member_channel):
        """Convert logical member channel to physical MIDI channel"""
        if self.is_lower_zone:
            return member_channel
        else:
            return member_channel + (MPE_UPPER_ZONE_MASTER - 14)
            
    def is_master_channel(self, channel):
        """Check if channel is the zone master"""
        return channel == self.master_channel
        
    def is_member_channel(self, channel):
        """Check if channel is a member channel"""
        if self.is_lower_zone:
            return channel in self.member_channels
        else:
            return (channel - (MPE_UPPER_ZONE_MASTER - 14)) in self.member_channels

    def update_state(self, msg, message_counter):
        """Update zone state based on MIDI message"""
        channel = msg.channel
        zone_name = 'lower' if self.is_lower_zone else 'upper'
        
        if msg.type == 'noteon':
            _log("MPE Note On: zone=" + zone_name + " ch=" + str(channel) + " note=" + str(msg.note) + " vel=" + str(msg.velocity))
            if channel in self.channel_states:
                self.channel_states[channel]['active_notes'][msg.note] = msg.velocity
                
        elif msg.type == 'noteoff':
            _log("MPE Note Off: zone=" + zone_name + " ch=" + str(channel) + " note=" + str(msg.note))
            if channel in self.channel_states:
                if msg.note in self.channel_states[channel]['active_notes']:
                    del self.channel_states[channel]['active_notes'][msg.note]
                    # Log MPE statistics for this channel
                    stats = message_counter.get_channel_stats(channel)
                    _log("Channel " + str(channel) + " MPE stats - Total: " + str(stats['total']) + 
                         ", Pitch: " + str(stats['pitch_bend']) + ", Pressure: " + str(stats['pressure']) + 
                         ", Timbre: " + str(stats['timbre']))
                    
        elif msg.type == 'channelpressure':
            if channel in self.channel_states:
                delta = abs(msg.pressure - self.channel_states[channel]['pressure'])
                if delta >= MPE_FILTER_CONFIG['pressure_threshold']:
                    _log("MPE Pressure: zone=" + zone_name + " ch=" + str(channel) + " pressure=" + str(msg.pressure))
                    self.channel_states[channel]['pressure'] = msg.pressure
                
        elif msg.type == 'pitchbend':
            if channel in self.channel_states:
                delta = abs(msg.pitch_bend - self.channel_states[channel]['pitch_bend'])
                if delta >= MPE_FILTER_CONFIG['pitch_bend_threshold']:
                    _log("MPE Pitch Bend: zone=" + zone_name + " ch=" + str(channel) + " value=" + str(msg.pitch_bend))
                    self.channel_states[channel]['pitch_bend'] = msg.pitch_bend
                
        elif msg.type == 'cc':
            if msg.control == MPE_TIMBRE_CC and channel in self.channel_states:
                delta = abs(msg.value - self.channel_states[channel]['timbre'])
                if delta >= MPE_FILTER_CONFIG['timbre_threshold']:
                    _log("MPE CC: zone=" + zone_name + " ch=" + str(channel) + " cc=" + str(msg.control) + " value=" + str(msg.value))
                    self.channel_states[channel]['timbre'] = msg.value

class MidiMessage:
    """MIDI message with MPE awareness"""
    def __init__(self, status_byte, data=None):
        self.status_byte = status_byte
        self.data = data if data else []
        self.channel = status_byte & 0x0F
        self.message_type = status_byte & 0xF0
        
        # Initialize with defaults
        self.type = 'unknown'
        self.note = 0
        self.velocity = 0
        self.control = 0
        self.value = 0
        self.pressure = 0
        self.pitch_bend = 8192

    def _parse_message(self):
        """Parse MIDI message and set appropriate properties"""
        try:
            if self.message_type == MIDI_NOTE_ON:
                self.note = self.data[0]
                self.velocity = self.data[1]
                self.type = 'noteon' if self.velocity > 0 else 'noteoff'
                _log("Created Note " + self.type + ": ch=" + str(self.channel) + " note=" + str(self.note) + " vel=" + str(self.velocity))
                
            elif self.message_type == MIDI_NOTE_OFF:
                self.type = 'noteoff'
                self.note = self.data[0]
                self.velocity = self.data[1]
                _log("Created Note Off: ch=" + str(self.channel) + " note=" + str(self.note))
                
            elif self.message_type == MIDI_CONTROL_CHANGE:
                self.type = 'cc'
                self.control = self.data[0]
                self.value = self.data[1]
                _log("Created CC: ch=" + str(self.channel) + " cc=" + str(self.control) + " val=" + str(self.value))
                
            elif self.message_type == MIDI_CHANNEL_PRESSURE:
                self.type = 'channelpressure'
                self.pressure = self.data[0]
                _log("Created Channel Pressure: ch=" + str(self.channel) + " pressure=" + str(self.pressure))
                
            elif self.message_type == MIDI_PITCH_BEND:
                self.type = 'pitchbend'
                self.pitch_bend = (self.data[1] << 7) | self.data[0]
                _log("Created Pitch Bend: ch=" + str(self.channel) + " value=" + str(self.pitch_bend))
                
        except Exception as e:
            _log("Error parsing MIDI message: " + str(e), is_error=True)
            self.type = 'error'

    @property
    def length(self):
        """Expected message length based on status byte"""
        if self.message_type == MIDI_CHANNEL_PRESSURE:
            return 2
        elif self.message_type < MIDI_SYSTEM_MESSAGE:
            return 3
        return 1

    def is_complete(self):
        """Check if message has all required bytes"""
        return len(self.data) + 1 >= self.length

    def __eq__(self, other):
        """Enable string type comparisons"""
        if isinstance(other, str):
            return self.type == other
        return NotImplemented

class MidiParser:
    """MIDI byte stream parser"""
    def __init__(self):
        self.current_message = None
        self.running_status = None
        self.bytes_processed = 0

    def process_byte(self, byte):
        """Process a single MIDI byte"""
        self.bytes_processed += 1
        
        if byte & 0x80:  # Status byte
            _log("Processing status byte: 0x{:02x}".format(byte), is_debug=True)
            if byte < 0xF8:  # Not realtime
                self.running_status = byte
                self.current_message = MidiMessage(byte)
            return None
            
        # Data byte - use running status if needed
        if not self.current_message and self.running_status:
            _log("Using running status: 0x{:02x}".format(self.running_status), is_debug=True)
            self.current_message = MidiMessage(self.running_status)
        
        if self.current_message:
            _log("Adding data byte: 0x{:02x}".format(byte), is_debug=True)
            self.current_message.data.append(byte)
            if self.current_message.is_complete():
                self.current_message._parse_message()  # Parse message once complete
                msg = self.current_message
                self.current_message = None
                return msg
        
        return None

class MidiInterface:
    """MIDI interface with MPE support"""
    def __init__(self, transport):
        self.transport = transport
        self.parser = MidiParser()
        self.subscribers = []
        self.message_counter = MPEMessageCounter()
        
        # Initialize MPE zones
        self.lower_zone = MPEZone(is_lower_zone=True)
        self.upper_zone = None  # Initialize upper zone only if needed
        _log("MIDI Interface initialized with MPE support")
        
    def process_midi_messages(self):
        """Process incoming MIDI data"""
        while self.transport.in_waiting:
            byte = self.transport.read(1)
            if not byte:
                break
                
            msg = self.parser.process_byte(byte[0])
            if msg and msg.type != 'unknown':
                self._handle_message(msg)

    def _handle_message(self, msg):
        """Update MPE state based on message"""
        # Always process Note On/Off messages
        if msg.type in ['noteon', 'noteoff']:
            self._process_message(msg)
            return
            
        # Filter other MPE messages based on configuration
        if self.message_counter.can_process_message(msg.type):
            self._process_message(msg)
            self.message_counter.count_message(msg.type, msg.channel)

    def _process_message(self, msg):
        """Process a message that has passed filtering"""
        # Determine which zone the message belongs to
        zone = self.lower_zone
        if self.upper_zone and msg.channel >= MPE_UPPER_ZONE_MASTER - 14:
            zone = self.upper_zone
            
        if zone:
            zone.update_state(msg, self.message_counter)
            self._distribute_message(msg)

    def _distribute_message(self, msg):
        """Send message to matching subscribers"""
        for subscription in self.subscribers:
            if subscription.matches(msg):
                try:
                    subscription.callback(msg)
                except Exception as e:
                    _log(str(e), is_error=True)

    def subscribe(self, callback, message_types=None, channels=None, cc_numbers=None):
        """Add a filtered subscription"""
        subscription = MidiSubscription(callback, message_types, channels, cc_numbers)
        self.subscribers.append(subscription)
        _log("Added subscription for types=" + str(message_types) + " channels=" + str(channels) + " cc=" + str(cc_numbers))
        return subscription

    def unsubscribe(self, subscription):
        """Remove a subscription"""
        if subscription in self.subscribers:
            self.subscribers.remove(subscription)
            _log("Removed subscription")

def initialize_midi():
    """Initialize MIDI interface"""
    from uart import UartManager
    transport, _ = UartManager.get_interfaces()
    midi_interface = MidiInterface(transport)
    UartManager.set_midi_interface(midi_interface)
    _log("MIDI system initialized")
    return midi_interface
