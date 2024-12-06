"""MIDI interface system providing MIDI message handling and MPE support."""

import sys
from constants import (
    LOG_MIDI, LOG_LIGHT_ORANGE, LOG_RED, LOG_RESET,
    MidiMessageType
)
from uart import UartManager

# MIDI Constants
MIDI_NOTE_OFF = MidiMessageType.NOTE_OFF
MIDI_NOTE_ON = MidiMessageType.NOTE_ON
MIDI_POLY_PRESSURE = MidiMessageType.POLY_PRESSURE
MIDI_CONTROL_CHANGE = MidiMessageType.CONTROL_CHANGE
MIDI_PROGRAM_CHANGE = MidiMessageType.PROGRAM_CHANGE
MIDI_CHANNEL_PRESSURE = MidiMessageType.CHANNEL_PRESSURE
MIDI_PITCH_BEND = MidiMessageType.PITCH_BEND
MIDI_SYSTEM_MESSAGE = MidiMessageType.SYSTEM_MESSAGE

# MPE Constants
MPE_RPN_MSB = 0x00
MPE_RPN_LSB = 0x06
DEFAULT_ZONE_PB_RANGE = 2  # Semitones for manager channel
DEFAULT_NOTE_PB_RANGE = 48  # Semitones for member channels
MPE_CC_TIMBRE = 74  # CC#74 for third dimension control

# RPN Constants
RPN_MSB_CC = 101
RPN_LSB_CC = 100
DATA_ENTRY_MSB_CC = 6
DATA_ENTRY_LSB_CC = 38
RPN_PITCH_BEND_RANGE = 0x0000
RPN_MPE_CONFIGURATION = 0x0006

def _log(message, is_error=False):
    """Log messages with MIDI prefix"""
    color = LOG_RED if is_error else LOG_LIGHT_ORANGE
    if is_error:
        print(f"{color}{LOG_MIDI} [ERROR] {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{LOG_MIDI} {message}{LOG_RESET}", file=sys.stderr)

def _log_midi_bytes(prefix, data):
    """Log MIDI bytes in hex format"""
    hex_data = [f"0x{b:02x}" for b in data]
    _log(f"{prefix}: {hex_data}")

def _log_midi_message(msg):
    """Log interpreted MIDI message"""
    if msg.type == 'noteon':
        _log(f"Note On Message:")
        _log(f"  type: {msg.type}")
        _log(f"  channel: {msg.channel}")  # Remove +1 to match actual MIDI channel
        _log(f"  note: {msg.note} (0x{msg.note:02x})")
        _log(f"  velocity: {msg.velocity} (0x{msg.velocity:02x})")
    elif msg.type == 'noteoff':
        _log(f"Note Off Message:")
        _log(f"  type: {msg.type}")
        _log(f"  channel: {msg.channel}")  # Remove +1 to match actual MIDI channel
        _log(f"  note: {msg.note} (0x{msg.note:02x})")
        _log(f"  velocity: {msg.velocity} (0x{msg.velocity:02x})")
    elif msg.type == 'cc':
        _log(f"Control Change Message:")
        _log(f"  type: {msg.type}")
        _log(f"  channel: {msg.channel}")  # Remove +1 to match actual MIDI channel
        _log(f"  control: {msg.control} (0x{msg.control:02x})")
        _log(f"  value: {msg.value} (0x{msg.value:02x})")
    elif msg.type == 'channelpressure':
        _log(f"Channel Pressure Message:")
        _log(f"  type: {msg.type}")
        _log(f"  channel: {msg.channel}")  # Remove +1 to match actual MIDI channel
        _log(f"  pressure: {msg.pressure} (0x{msg.pressure:02x})")
    elif msg.type == 'pitchbend':
        _log(f"Pitch Bend Message:")
        _log(f"  type: {msg.type}")
        _log(f"  channel: {msg.channel}")  # Remove +1 to match actual MIDI channel
        _log(f"  value: {msg.pitch_bend} (0x{msg.pitch_bend:04x})")

class MidiMessage:
    """Base MIDI message class compatible with synthesizer expectations"""
    def __init__(self, status, data=None):
        self.status = status
        self.data = data if data else []
        self.channel = status & 0x0F if status < 0xF0 else None  # Keep 0-based channel internally
        self.message_type = status & 0xF0 if status < 0xF0 else status
        
        # Initialize properties with defaults
        self.type = 'unknown'
        self._note = 0
        self._velocity = 0
        self._control = 0
        self._value = 0
        self._pressure = 0
        self._pitch_bend = 8192
        
        # Update properties based on message type
        self._update_type()
        self._update_properties()

    def _update_type(self):
        """Get message type string for compatibility with synthesizer.py"""
        if self.message_type == MIDI_NOTE_ON and (len(self.data) >= 2 and self.data[1] > 0):
            self.type = 'noteon'
        elif self.message_type == MIDI_NOTE_OFF or (
            self.message_type == MIDI_NOTE_ON and len(self.data) >= 2 and self.data[1] == 0
        ):
            self.type = 'noteoff'
        elif self.message_type == MIDI_CONTROL_CHANGE:
            self.type = 'cc'
        elif self.message_type == MIDI_CHANNEL_PRESSURE:
            self.type = 'channelpressure'
        elif self.message_type == MIDI_PITCH_BEND:
            self.type = 'pitchbend'

    def _update_properties(self):
        """Update compatibility properties based on message type"""
        if self.type in ('noteon', 'noteoff'):
            if len(self.data) >= 2:
                self._note = self.data[0]
                self._velocity = self.data[1]
        elif self.type == 'cc':
            if len(self.data) >= 2:
                self._control = self.data[0]
                self._value = self.data[1]
        elif self.type == 'channelpressure':
            if len(self.data) >= 1:
                self._pressure = self.data[0]
        elif self.type == 'pitchbend':
            if len(self.data) >= 2:
                # LSB first, then MSB
                self._pitch_bend = (self.data[1] << 7) | self.data[0]

    @property
    def note(self):
        """Note number (0-127)"""
        return self._note

    @property
    def velocity(self):
        """Note velocity (0-127)"""
        return self._velocity

    @property
    def control(self):
        """CC controller number (0-127)"""
        return self._control

    @property
    def value(self):
        """CC value (0-127)"""
        return self._value

    @property
    def pressure(self):
        """Channel pressure value (0-127)"""
        return self._pressure

    @property
    def pitch_bend(self):
        """Pitch bend value (0-16383, centered at 8192)"""
        return self._pitch_bend

    @property
    def length(self):
        """Get expected message length based on status byte"""
        if self.message_type in [MIDI_PROGRAM_CHANGE, MIDI_CHANNEL_PRESSURE]:
            return 2
        elif self.message_type < MIDI_SYSTEM_MESSAGE:
            return 3
        return 1

    def is_complete(self):
        """Check if message has all required bytes"""
        return len(self.data) + 1 >= self.length

    def __eq__(self, other):
        """Enable isinstance() checks with string types"""
        if isinstance(other, str):
            return self.type == other
        return NotImplemented

class MPEZone:
    """Represents an MPE zone configuration"""
    def __init__(self, manager_channel: int, num_member_channels: int):
        self.manager_channel = manager_channel  # 0 for lower zone, 15 for upper zone
        self.member_channels = set()
        if num_member_channels > 0:
            if manager_channel == 0:  # Lower zone
                self.member_channels = set(range(1, 1 + num_member_channels))
            else:  # Upper zone
                self.member_channels = set(range(14 - num_member_channels, 15))
        
        self.active_notes = {
            ch: {} for ch in self.member_channels
        }
        
        # Track controller states
        self.pb_range = DEFAULT_ZONE_PB_RANGE
        self.member_pb_range = DEFAULT_NOTE_PB_RANGE
        self.manager_pitch_bend = 8192  # Center position
        self.channel_states = {
            ch: {
                'pitch_bend': 8192,
                'pressure': 0,
                'timbre': 64
            } for ch in self.member_channels
        }

class MidiParser:
    """Parses MIDI byte stream into messages"""
    def __init__(self):
        self.current_message = None
        self.running_status = None

    def process_byte(self, byte):
        """Process a single MIDI byte, return complete message if available"""
        # Status byte
        if byte & 0x80:
            if byte < 0xF8:  # Not realtime message
                self.running_status = byte
                self.current_message = MidiMessage(byte)
            return None
        
        # Data byte
        if not self.current_message and self.running_status:
            self.current_message = MidiMessage(self.running_status)
        
        if self.current_message:
            self.current_message.data.append(byte)
            if self.current_message.is_complete():
                msg = self.current_message
                self.current_message = None
                return msg
        
        return None

class MidiSubscription:
    """Represents a subscription to MIDI messages"""
    def __init__(self, callback, message_types=None, channels=None, cc_numbers=None):
        self.callback = callback
        self.message_types = message_types if message_types is not None else []
        self.channels = channels if channels is not None else None
        self.cc_numbers = cc_numbers if cc_numbers is not None else None

    def matches(self, message):
        """Check if message matches subscription criteria"""
        if not self.message_types:
            return True
        
        for msg_type in self.message_types:
            if isinstance(msg_type, str):
                if message == msg_type:  # Uses __eq__ to compare with string
                    if self.channels is None or message.channel in self.channels:
                        if message.type == 'cc' and self.cc_numbers is not None:
                            return message.control in self.cc_numbers
                        return True
        return False

class MidiInterface:
    """MIDI interface"""
    def __init__(self, transport):
        self.transport = transport
        self.subscribers = []
        self.parser = MidiParser()
        
        # MPE state - initialize lower zone by default
        self.lower_zone = MPEZone(0, 14)  # Use channels 1-14 for notes
        self.upper_zone = None
        
        # RPN state tracking (0-based channels)
        self.rpn_state = {ch: {'msb': None, 'lsb': None} for ch in range(16)}
        
        # Note tracking (0-based channels)
        self.active_notes = {ch: set() for ch in range(16)}
        
        # Controller state (0-based channels)
        self.controller_state = {
            ch: {
                'pitch_bend': 8192,
                'pressure': 0,
                'timbre': 64
            } for ch in range(16)
        }

    def process_midi_messages(self):
        """Process incoming MIDI data"""
        while self.transport.in_waiting:
            byte = self.transport.read(1)
            if not byte:
                break
                
            msg = self.parser.process_byte(byte[0])
            if msg:
                self._distribute_message(msg)

    def _distribute_message(self, msg):
        """Distribute MIDI message to subscribers"""
        _log_midi_message(msg)
        for subscription in self.subscribers:
            if subscription.matches(msg):
                try:
                    subscription.callback(msg)
                except Exception as e:
                    _log(f"Error in MIDI subscriber callback: {e}", is_error=True)

    def subscribe(self, callback, message_types=None, channels=None, cc_numbers=None):
        """Subscribe to MIDI messages"""
        subscription = MidiSubscription(callback, message_types, channels, cc_numbers)
        self.subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription):
        """Remove a subscription"""
        if subscription in self.subscribers:
            self.subscribers.remove(subscription)

    def cleanup(self):
        """Clean up resources"""
        self.subscribers.clear()
        self.parser = MidiParser()

def initialize_midi():
    """Initialize MIDI interface and register with UartManager"""
    transport, _ = UartManager.get_interfaces()
    midi_interface = MidiInterface(transport)
    UartManager.set_midi_interface(midi_interface)
    return midi_interface
