"""MIDI interface system providing MIDI message handling and MPE support with filtering."""

from constants import LOG_MIDI, LOG_LIGHT_ORANGE, LOG_RED, LOG_RESET, MidiMessageType, MIDI_LOG
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
    'pitch_bend_ratio': 0,    # Allow 1 in 4 messages through (0 means filter all)
    'pressure_ratio': 0,      # Allow 1 in 3 messages through (0 means filter all)
    'timbre_ratio': 0,        # Allow 1 in 2 messages through (0 means filter all)
    'pitch_bend_threshold': 64,  # ~1% of total range (0-16383)
    'pressure_threshold': 4,     # ~3% of total range (0-127)
    'timbre_threshold': 4        # ~3% of total range (0-127)
}

def _log(message, is_error=False, is_debug=False):
    """Log messages with MIDI prefix"""
    if not MIDI_LOG:
        return
        
    color = LOG_RED if is_error else LOG_LIGHT_ORANGE
    prefix = "[ERROR] " if is_error else ""
    print("{}{}".format(color, LOG_MIDI) + prefix + " " + message + LOG_RESET)

class MPEMessageCounter:
    """Tracks MPE message counts globally and per channel"""
    def __init__(self):
        self.positions = {'pitch_bend': 0, 'pressure': 0, 'timbre': 0}
        if MIDI_LOG:
            self.reset_counters()
        
    def reset_counters(self):
        """Reset all message counters - only used when logging is enabled"""
        if not MIDI_LOG:
            return
            
        self.channel_messages = {}
        for ch in range(16):
            self.channel_messages[ch] = {
                'allowed': {'pitch_bend': 0, 'pressure': 0, 'timbre': 0},
                'filtered': {'pitch_bend': 0, 'pressure': 0, 'timbre': 0}
            }
            
    def can_process_message(self, msg_type, channel):
        """Check if a message can be processed based on ratios"""
        # Note messages are always processed
        if msg_type in ['noteon', 'noteoff']:
            return True
            
        # Map message type to ratio config and counter key
        ratio_map = {
            'pitchbend': ('pitch_bend_ratio', 'pitch_bend'),
            'channelpressure': ('pressure_ratio', 'pressure'),
            'cc': ('timbre_ratio', 'timbre')
        }
        
        ratio_key, count_key = ratio_map[msg_type]
        ratio = MPE_FILTER_CONFIG[ratio_key]
        
        if ratio == 0:  # Filter all if ratio is 0
            if MIDI_LOG:
                self.channel_messages[channel]['filtered'][count_key] += 1
            return False
            
        if ratio == 1:  # Allow all if ratio is 1
            if MIDI_LOG:
                self.channel_messages[channel]['allowed'][count_key] += 1
            return True
            
        # Increment position and wrap around to 1 when we hit ratio
        self.positions[count_key] = (self.positions[count_key] % ratio) + 1
        
        # Allow through when we hit ratio
        should_process = self.positions[count_key] == ratio
        
        # Update statistics only if logging is enabled
        if MIDI_LOG:
            if should_process:
                self.channel_messages[channel]['allowed'][count_key] += 1
            else:
                self.channel_messages[channel]['filtered'][count_key] += 1
            
        return should_process
            
    def get_channel_stats(self, channel):
        """Get message statistics for a channel - only used when logging is enabled"""
        if not MIDI_LOG:
            return None
            
        stats = self.channel_messages[channel]
        return {
            'pitch_bend': stats['allowed']['pitch_bend'],
            'pressure': stats['allowed']['pressure'],
            'timbre': stats['allowed']['timbre'],
            'filtered': stats['filtered']
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
                    # Log detailed MPE statistics for this channel if logging is enabled
                    if MIDI_LOG:
                        stats = message_counter.get_channel_stats(channel)
                        if stats:  # Will be None if logging is disabled
                            filtered = stats['filtered']
                            _log("Channel " + str(channel) + " MPE message statistics:")
                            _log("    Pitch Bend:")
                            _log("        Allowed: " + str(stats['pitch_bend']))
                            _log("        Filtered: " + str(filtered['pitch_bend']))
                            _log("        Total: " + str(stats['pitch_bend'] + filtered['pitch_bend']))
                            _log("    Pressure:")
                            _log("        Allowed: " + str(stats['pressure']))
                            _log("        Filtered: " + str(filtered['pressure']))
                            _log("        Total: " + str(stats['pressure'] + filtered['pressure']))
                            _log("    Timbre:")
                            _log("        Allowed: " + str(stats['timbre']))
                            _log("        Filtered: " + str(filtered['timbre']))
                            _log("        Total: " + str(stats['timbre'] + filtered['timbre']))
                    
        elif msg.type == 'channelpressure':
            if channel in self.channel_states:
                _log("MPE Pressure: zone=" + zone_name + " ch=" + str(channel) + " pressure=" + str(msg.pressure))
                self.channel_states[channel]['pressure'] = msg.pressure
                
        elif msg.type == 'pitchbend':
            if channel in self.channel_states:
                _log("MPE Pitch Bend: zone=" + zone_name + " ch=" + str(channel) + " value=" + str(msg.pitch_bend))
                self.channel_states[channel]['pitch_bend'] = msg.pitch_bend
                
        elif msg.type == 'cc':
            if msg.control == MPE_TIMBRE_CC and channel in self.channel_states:
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
    def __init__(self, message_counter):
        self.message_counter = message_counter
        self.bytes_processed = 0
        self.collecting_data = False
        self.current_status = None
        self.current_data = []
        self.channel_states = {}  # Store last values using raw bytes
        
    def get_message_type(self, status_byte):
        """Get message type from status byte for early filtering"""
        message_type = status_byte & 0xF0
        if message_type == MIDI_CHANNEL_PRESSURE:
            return 'channelpressure'
        elif message_type == MIDI_PITCH_BEND:
            return 'pitchbend'
        elif message_type == MIDI_CONTROL_CHANGE:
            return 'cc'
        return None

    def check_threshold(self, status_byte, data):
        """Check value thresholds using raw bytes before message creation"""
        msg_type = self.get_message_type(status_byte)
        if not msg_type:
            return True  # Non-continuous messages pass through
            
        channel = status_byte & 0x0F
        if channel not in self.channel_states:
            self.channel_states[channel] = {
                'pressure': 0,
                'pitch_bend_lsb': 0,
                'pitch_bend_msb': 0x40,  # Center = 8192
                'timbre': 64
            }
            
        if msg_type == 'channelpressure':
            delta = abs(data[0] - self.channel_states[channel]['pressure'])
            if delta < MPE_FILTER_CONFIG['pressure_threshold']:
                return False
            self.channel_states[channel]['pressure'] = data[0]
            
        elif msg_type == 'pitchbend':
            # Compare 14-bit values without creating objects
            current = (self.channel_states[channel]['pitch_bend_msb'] << 7) | self.channel_states[channel]['pitch_bend_lsb']
            new = (data[1] << 7) | data[0]
            delta = abs(new - current)
            if delta < MPE_FILTER_CONFIG['pitch_bend_threshold']:
                return False
            self.channel_states[channel]['pitch_bend_lsb'] = data[0]
            self.channel_states[channel]['pitch_bend_msb'] = data[1]
            
        elif msg_type == 'cc' and data[0] == MPE_TIMBRE_CC:
            delta = abs(data[1] - self.channel_states[channel]['timbre'])
            if delta < MPE_FILTER_CONFIG['timbre_threshold']:
                return False
            self.channel_states[channel]['timbre'] = data[1]
            
        return True

    def process_byte(self, byte):
        """Process a single MIDI byte with early filtering"""
        self.bytes_processed += 1
        
        if byte & 0x80:  # Status byte
            if byte < 0xF8:  # Not realtime
                self.current_status = byte
                self.current_data = []
                self.collecting_data = True
            return None
            
        if self.collecting_data:
            self.current_data.append(byte)
            expected_length = 2 if (self.current_status & 0xF0) == MIDI_CHANNEL_PRESSURE else 3
            
            if len(self.current_data) >= expected_length - 1:
                self.collecting_data = False
                channel = self.current_status & 0x0F
                
                # Early threshold check on raw bytes
                if not self.check_threshold(self.current_status, self.current_data):
                    return None
                    
                # Check rate limit before creating message
                msg_type = self.get_message_type(self.current_status)
                if msg_type and not self.message_counter.can_process_message(msg_type, channel):
                    return None
                    
                # Only create and parse message if it passes all filters
                msg = MidiMessage(self.current_status, self.current_data[:])
                msg._parse_message()
                return msg
                
        return None

class MidiInterface:
    """MIDI interface with MPE support"""
    def __init__(self, transport):
        self.transport = transport
        self.message_counter = MPEMessageCounter()
        self.parser = MidiParser(self.message_counter)
        self.subscribers = []
        
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
        self._process_message(msg)

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
