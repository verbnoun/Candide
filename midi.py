"""MIDI interface system providing MIDI message handling and MPE support with filtering."""

import supervisor
from constants import MidiMessageType
from logging import log, TAG_MIDI

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
    'pitch_bend_ratio': 1,    # Allow 1 in X messages through (0 means filter all)
    'pressure_ratio': 1,      # Allow 1 in X messages through (0 means filter all)
    'timbre_ratio': 0,        # Allow 1 in X messages through (0 means filter all)
    'pitch_bend_threshold': 64,  # ~1% of total range (0-16383)
    'pressure_threshold': 4,     # ~3% of total range (0-127)
    'timbre_threshold': 4        # ~3% of total range (0-127)
}

class MPEMessageCounter:
    """Tracks MPE message counts globally and per channel"""
    def __init__(self):
        self.positions = {'pitch_bend': 0, 'pressure': 0, 'timbre': 0}
        self.reset_counters()
        
    def reset_counters(self):
        """Reset all message counters"""
        self.channel_messages = {}
        for ch in range(16):
            self.channel_messages[ch] = {
                'allowed': {'pitch_bend': 0, 'pressure': 0, 'timbre': 0},
                'filtered': {'pitch_bend': 0, 'pressure': 0, 'timbre': 0}
            }
            
    def can_process_message(self, msg_type, channel):
        """Check if a message can be processed based on ratios"""
        # Note messages are always processed
        if msg_type in ['note_on', 'note_off']:
            return True
            
        # Map message type to ratio config and counter key
        ratio_map = {
            'pitch_bend': ('pitch_bend_ratio', 'pitch_bend'),
            'channel_pressure': ('pressure_ratio', 'pressure'),
            'cc': ('timbre_ratio', 'timbre')
        }
        
        ratio_key, count_key = ratio_map[msg_type]
        ratio = MPE_FILTER_CONFIG[ratio_key]
        
        if ratio == 0:  # Filter all if ratio is 0
            self.channel_messages[channel]['filtered'][count_key] += 1
            return False
            
        if ratio == 1:  # Allow all if ratio is 1
            self.channel_messages[channel]['allowed'][count_key] += 1
            return True
            
        # Increment position and wrap around to 1 when we hit ratio
        self.positions[count_key] = (self.positions[count_key] % ratio) + 1
        
        # Allow through when we hit ratio
        should_process = self.positions[count_key] == ratio
        
        if should_process:
            self.channel_messages[channel]['allowed'][count_key] += 1
        else:
            self.channel_messages[channel]['filtered'][count_key] += 1
            
        return should_process
            
    def get_channel_stats(self, channel):
        """Get message statistics for a channel"""
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
        log(TAG_MIDI, f"Created subscription for types={message_types} channels={channels} cc={cc_numbers}")

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
                'bend': 8192  # 14-bit centered
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
        
        if msg.type == 'note_on':
            log(TAG_MIDI, f"MPE Note On: zone={zone_name} ch={channel} note={msg.note} vel={msg.velocity}")
            if channel in self.channel_states:
                self.channel_states[channel]['active_notes'][msg.note] = msg.velocity
                
        elif msg.type == 'note_off':
            log(TAG_MIDI, f"MPE Note Off: zone={zone_name} ch={channel} note={msg.note} release_vel={msg.release_velocity}")
            if channel in self.channel_states:
                if msg.note in self.channel_states[channel]['active_notes']:
                    del self.channel_states[channel]['active_notes'][msg.note]
                    # Log detailed MPE statistics for this channel
                    stats = message_counter.get_channel_stats(channel)
                    filtered = stats['filtered']
                    log(TAG_MIDI, f"Channel {channel} MPE message statistics:")
                    log(TAG_MIDI, f"    Pitch Bend:")
                    log(TAG_MIDI, f"        Allowed: {stats['pitch_bend']}")
                    log(TAG_MIDI, f"        Filtered: {filtered['pitch_bend']}")
                    log(TAG_MIDI, f"        Total: {stats['pitch_bend'] + filtered['pitch_bend']}")
                    log(TAG_MIDI, f"    Pressure:")
                    log(TAG_MIDI, f"        Allowed: {stats['pressure']}")
                    log(TAG_MIDI, f"        Filtered: {filtered['pressure']}")
                    log(TAG_MIDI, f"        Total: {stats['pressure'] + filtered['pressure']}")
                    log(TAG_MIDI, f"    Timbre:")
                    log(TAG_MIDI, f"        Allowed: {stats['timbre']}")
                    log(TAG_MIDI, f"        Filtered: {filtered['timbre']}")
                    log(TAG_MIDI, f"        Total: {stats['timbre'] + filtered['timbre']}")
                    
        elif msg.type == 'channel_pressure':
            if channel in self.channel_states:
                log(TAG_MIDI, f"MPE Pressure: zone={zone_name} ch={channel} pressure={msg.pressure}")
                self.channel_states[channel]['pressure'] = msg.pressure
                
        elif msg.type == 'pitch_bend':
            if channel in self.channel_states:
                log(TAG_MIDI, f"MPE Pitch Bend: zone={zone_name} ch={channel} value={msg.bend}")
                self.channel_states[channel]['bend'] = msg.bend
                
        elif msg.type == 'cc':
            if msg.control == MPE_TIMBRE_CC and channel in self.channel_states:
                log(TAG_MIDI, f"MPE CC: zone={zone_name} ch={channel} cc={msg.control} value={msg.value}")
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
        self.release_velocity = 0  # Added release_velocity attribute
        self.control = 0
        self.value = 0
        self.pressure = 0
        self.bend = 8192

    def _parse_message(self):
        """Parse MIDI message and set appropriate properties"""
        try:
            if self.message_type == MIDI_NOTE_ON:
                self.note = self.data[0]
                self.velocity = self.data[1]
                self.type = 'note_on' if self.velocity > 0 else 'note_off'
                if self.velocity == 0:  # Note off via note-on with zero velocity
                    self.release_velocity = 0
                log(TAG_MIDI, f"Created Note {self.type}: ch={self.channel} note={self.note} vel={self.velocity}")
                
            elif self.message_type == MIDI_NOTE_OFF:
                self.type = 'note_off'
                self.note = self.data[0]
                self.release_velocity = self.data[1]  # Use release_velocity instead of velocity for note-off
                log(TAG_MIDI, f"Created Note Off: ch={self.channel} note={self.note} release_vel={self.release_velocity}")
                
            elif self.message_type == MIDI_CONTROL_CHANGE:
                self.type = 'cc'
                self.control = self.data[0]
                self.value = self.data[1]
                log(TAG_MIDI, f"Created CC: ch={self.channel} cc={self.control} val={self.value}")
                
            elif self.message_type == MIDI_CHANNEL_PRESSURE:
                self.type = 'channel_pressure'
                self.pressure = self.data[0]
                log(TAG_MIDI, f"Created Channel Pressure: ch={self.channel} pressure={self.pressure}")
                
            elif self.message_type == MIDI_PITCH_BEND:
                self.type = 'pitch_bend'
                self.bend = (self.data[1] << 7) | self.data[0]
                log(TAG_MIDI, f"Created Pitch Bend: ch={self.channel} value={self.bend}")
                
        except Exception as e:
            log(TAG_MIDI, f"Error parsing MIDI message: {str(e)}", is_error=True)
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
            return 'channel_pressure'
        elif message_type == MIDI_PITCH_BEND:
            return 'pitch_bend'
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
            
        if msg_type == 'channel_pressure':
            delta = abs(data[0] - self.channel_states[channel]['pressure'])
            if delta < MPE_FILTER_CONFIG['pressure_threshold']:
                return False
            self.channel_states[channel]['pressure'] = data[0]
            
        elif msg_type == 'pitch_bend':
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
                
                # Channel 0 bypasses all filtering
                if channel == 0:
                    msg = MidiMessage(self.current_status, self.current_data[:])
                    msg._parse_message()
                    return msg
                
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
        log(TAG_MIDI, "MIDI Interface initialized with MPE support")
        
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
                    log(TAG_MIDI, str(e), is_error=True)

    def subscribe(self, callback, message_types=None, channels=None, cc_numbers=None):
        """Add a filtered subscription"""
        subscription = MidiSubscription(callback, message_types, channels, cc_numbers)
        self.subscribers.append(subscription)
        log(TAG_MIDI, f"Added subscription for types={message_types} channels={channels} cc={cc_numbers}")
        return subscription

    def unsubscribe(self, subscription):
        """Remove a subscription"""
        if subscription in self.subscribers:
            self.subscribers.remove(subscription)
            log(TAG_MIDI, "Removed subscription")

def initialize_midi():
    """Initialize MIDI interface"""
    from uart import UartManager
    transport, _ = UartManager.get_interfaces()
    midi_interface = MidiInterface(transport)
    UartManager.set_midi_interface(midi_interface)
    log(TAG_MIDI, "MIDI system initialized")
    return midi_interface
