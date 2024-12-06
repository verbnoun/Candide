"""UART interface system providing unified communication protocols with MPE support for the Candide synthesizer."""

import time
import busio
import sys
from constants import (
    UART_TX, UART_RX, UART_BAUDRATE, UART_TIMEOUT,
    LOG_UART, LOG_LIGHT_BLUE, LOG_RED, LOG_RESET,
    MESSAGE_TIMEOUT, MidiMessageType
)

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
    """Log messages with UART prefix"""
    color = LOG_RED if is_error else LOG_LIGHT_BLUE
    if is_error:
        print(f"{color}{LOG_UART} [ERROR] {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{LOG_UART} {message}{LOG_RESET}", file=sys.stderr)

def _log_midi_bytes(prefix, data):
    """Log MIDI bytes in hex format"""
    hex_data = [f"0x{b:02x}" for b in data]
    _log(f"{prefix}: {hex_data}")

def _log_midi_message(msg):
    """Log interpreted MIDI message"""
    if msg.type == 'noteon':
        _log(f"🎵 MIDI: Note On - note={msg.note}, velocity={msg.velocity}, channel={msg.channel+1}")
    elif msg.type == 'noteoff':
        _log(f"🎵 MIDI: Note Off - note={msg.note}, velocity={msg.velocity}, channel={msg.channel+1}")
    elif msg.type == 'cc':
        _log(f"🎵 MIDI: CC{msg.control} - value={msg.value}, channel={msg.channel+1}")
    elif msg.type == 'channelpressure':
        _log(f"🎵 MIDI: Channel Pressure - pressure={msg.pressure}, channel={msg.channel+1}")
    elif msg.type == 'pitchbend':
        _log(f"🎵 MIDI: Pitch Bend - value={msg.pitch_bend-8192} (raw={msg.pitch_bend}), channel={msg.channel+1}")

class MidiMessage:
    """Represents a MIDI message compatible with synthesizer.py expectations"""
    def __init__(self, status, data=None):
        self.status = status
        self.data = data if data else []
        self.channel = status & 0x0F if status < 0xF0 else None
        self.message_type = status & 0xF0 if status < 0xF0 else status
        
        # Initialize properties with defaults
        self.type = 'unknown'
        self.note = 0
        self.velocity = 0
        self.control = 0
        self.value = 0
        self.pressure = 0
        self.pitch_bend = 8192
        
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
                self.note = self.data[0]
                self.velocity = self.data[1]
        elif self.type == 'cc':
            if len(self.data) >= 2:
                self.control = self.data[0]
                self.value = self.data[1]
        elif self.type == 'channelpressure':
            if len(self.data) >= 1:
                self.pressure = self.data[0]
        elif self.type == 'pitchbend':
            if len(self.data) >= 2:
                self.pitch_bend = (self.data[1] << 7) | self.data[0]

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

class MPEZone:
    """Represents an MPE zone configuration"""
    def __init__(self, manager_channel: int, num_member_channels: int):
        self.manager_channel = manager_channel
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

class UartTransport:
    """UART transport layer with direct MIDI parsing"""
    def __init__(self, tx_pin=UART_TX, rx_pin=UART_RX, 
                 baudrate=UART_BAUDRATE, timeout=UART_TIMEOUT):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.baudrate = baudrate
        self.timeout = timeout
        self.subscribers = []
        self._initialize_uart()
        
        # MIDI parsing
        self.parser = MidiParser()
        
        # MPE state
        self.lower_zone = None
        self.upper_zone = None
        
        # RPN state tracking
        self.rpn_state = {ch: {'msb': None, 'lsb': None} for ch in range(16)}
        
        # Note tracking
        self.active_notes = {ch: set() for ch in range(16)}
        
        # Controller state
        self.controller_state = {
            ch: {
                'pitch_bend': 8192,
                'pressure': 0,
                'timbre': 64
            } for ch in range(16)
        }

    def _initialize_uart(self):
        """Initialize UART with specified parameters"""
        try:
            self.uart = busio.UART(
                tx=self.tx_pin,
                rx=self.rx_pin,
                baudrate=self.baudrate,
                timeout=self.timeout,
                bits=8,
                parity=None,
                stop=1
            )
            _log(f"UART initialized: baudrate={self.baudrate}, timeout={self.timeout}")
        except Exception as e:
            _log(f"UART initialization failed: {str(e)}", is_error=True)
            raise

    def _handle_rpn(self, channel, msg):
        """Handle RPN messages"""
        cc_num = msg.control
        value = msg.value
        
        if cc_num == RPN_MSB_CC:
            self.rpn_state[channel]['msb'] = value
        elif cc_num == RPN_LSB_CC:
            self.rpn_state[channel]['lsb'] = value
        elif cc_num == DATA_ENTRY_MSB_CC:
            msb = self.rpn_state[channel]['msb']
            lsb = self.rpn_state[channel]['lsb']
            if msb is not None and lsb is not None:
                rpn = (msb << 7) | lsb
                if rpn == RPN_MPE_CONFIGURATION:
                    self._handle_mpe_config(channel, value)
                elif rpn == RPN_PITCH_BEND_RANGE:
                    self._handle_pitch_bend_range(channel, value)

    def _handle_mpe_config(self, channel, num_channels):
        """Handle MPE configuration message"""
        if channel == 0:  # Lower zone
            if num_channels == 0:
                self.lower_zone = None
            else:
                self.lower_zone = MPEZone(0, num_channels)
            _log(f"Lower zone configured with {num_channels} channels")
        elif channel == 15:  # Upper zone
            if num_channels == 0:
                self.upper_zone = None
            else:
                self.upper_zone = MPEZone(15, num_channels)
            _log(f"Upper zone configured with {num_channels} channels")

    def _handle_pitch_bend_range(self, channel, semitones):
        """Handle pitch bend range setting"""
        zone = self._get_zone_for_channel(channel)
        if zone:
            if channel == zone.manager_channel:
                zone.pb_range = semitones
            else:
                zone.member_pb_range = semitones

    def _get_zone_for_channel(self, channel):
        """Get the MPE zone a channel belongs to"""
        if self.lower_zone and (
            channel == self.lower_zone.manager_channel or 
            channel in self.lower_zone.member_channels
        ):
            return self.lower_zone
        if self.upper_zone and (
            channel == self.upper_zone.manager_channel or 
            channel in self.upper_zone.member_channels
        ):
            return self.upper_zone
        return None

    def _handle_note_off(self, msg):
        """Handle Note Off message with priority"""
        channel = msg.channel
        note = msg.note
        velocity = msg.velocity
        
        if note in self.active_notes[channel]:
            self.active_notes[channel].remove(note)
            _log_midi_message(msg)
            self._distribute_message(msg)

    def _handle_note_on(self, msg):
        """Handle Note On message"""
        channel = msg.channel
        note = msg.note
        velocity = msg.velocity
        
        if velocity == 0:  # Note On with velocity 0 is Note Off
            self._handle_note_off(msg)
        else:
            self.active_notes[channel].add(note)
            _log_midi_message(msg)
            self._distribute_message(msg)

    def _handle_control_change(self, msg):
        """Handle Control Change message"""
        channel = msg.channel
        control = msg.control
        value = msg.value
        
        if control in [RPN_MSB_CC, RPN_LSB_CC, DATA_ENTRY_MSB_CC, DATA_ENTRY_LSB_CC]:
            self._handle_rpn(channel, msg)
        else:
            if control == MPE_CC_TIMBRE:
                self.controller_state[channel]['timbre'] = value
            _log_midi_message(msg)
            self._distribute_message(msg)

    def _handle_channel_pressure(self, msg):
        """Handle Channel Pressure message"""
        channel = msg.channel
        pressure = msg.pressure
        self.controller_state[channel]['pressure'] = pressure
        _log_midi_message(msg)
        self._distribute_message(msg)

    def _handle_pitch_bend(self, msg):
        """Handle Pitch Bend message"""
        channel = msg.channel
        value = msg.pitch_bend
        self.controller_state[channel]['pitch_bend'] = value
        _log_midi_message(msg)
        self._distribute_message(msg)

    def process_midi_messages(self):
        """Process incoming MIDI data"""
        while self.in_waiting:
            byte = self.uart.read(1)
            if not byte:
                break
                
            _log_midi_bytes("Receiving", byte)
            
            msg = self.parser.process_byte(byte[0])
            if msg:
                # Prioritize Note Off messages
                if msg.type == 'noteoff':
                    self._handle_note_off(msg)
                elif msg.type == 'noteon':
                    self._handle_note_on(msg)
                elif msg.type == 'cc':
                    self._handle_control_change(msg)
                elif msg.type == 'channelpressure':
                    self._handle_channel_pressure(msg)
                elif msg.type == 'pitchbend':
                    self._handle_pitch_bend(msg)

    def _distribute_message(self, msg):
        """Distribute MIDI message to subscribers"""
        for subscription in self.subscribers:
            if subscription.matches(msg):
                try:
                    subscription.callback(msg)
                except Exception as e:
                    _log(f"Error in MIDI subscriber callback: {e}", is_error=True)

    def write(self, data):
        """Write data to UART"""
        if data:
            return self.uart.write(bytes(data))
        return 0

    def read(self, size=None):
        """Read from UART"""
        if size is None:
            return self.uart.read()
        return self.uart.read(size)

    @property
    def in_waiting(self):
        """Get number of bytes waiting in receive buffer"""
        try:
            return self.uart.in_waiting
        except AttributeError:
            return self.uart.readable()

    def subscribe(self, callback, message_types=None, channels=None, cc_numbers=None):
        """Subscribe to MIDI messages"""
        subscription = MidiSubscription(callback, message_types, channels, cc_numbers)
        self.subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription):
        """Remove a subscription"""
        if subscription in self.subscribers:
            self.subscribers.remove(subscription)

    def flush_buffers(self):
        """Flush UART buffers"""
        try:
            # Try CircuitPython's reset_input_buffer
            self.uart.reset_input_buffer()
        except AttributeError:
            # Fallback for CircuitPython UART
            while self.in_waiting:
                self.uart.read()
        
        # No explicit output buffer reset needed for CircuitPython UART
        self.parser = MidiParser()  # Reset parser state
        _log("Buffers flushed")

    def cleanup(self):
        """Clean up resources"""
        if hasattr(self, 'uart'):
            _log("Cleaning up UART")
            self.flush_buffers()
            self.uart.deinit()
        self.subscribers.clear()

class MidiSubscription:
    """Represents a subscription to MIDI messages"""
    def __init__(self, callback, message_types=None, channels=None, cc_numbers=None):
        self.callback = callback
        self.message_types = message_types if message_types is not None else []
        self.channels = channels if channels is not None else None
        self.cc_numbers = cc_numbers if cc_numbers is not None else None

    def matches(self, message):
        """Check if message matches subscription criteria"""
        if not self.message_types or type(message) in self.message_types:
            if self.channels is None or message.channel in self.channels:
                if message.type == 'cc' and self.cc_numbers is not None:
                    return message.control in self.cc_numbers
                return True
        return False

class TextProtocol:
    """Text protocol interface"""
    def __init__(self, transport):
        self.transport = transport
        self.message_timeout = MESSAGE_TIMEOUT

    def write(self, message):
        if not isinstance(message, str):
            message = str(message)
        if not message.endswith('\n'):
            message += '\n'
        return self.transport.write(message.encode('utf-8'))

    def read(self, size=None):
        data = self.transport.read(size)
        return data.decode('utf-8') if data else None

    def read_line(self):
        buffer = bytearray()
        while True:
            if self.transport.in_waiting:
                byte = self.transport.read(1)
                if byte == b'\n':
                    return buffer.decode('utf-8')
                buffer.extend(byte)
            else:
                return None

    def flush_buffers(self):
        self.transport.flush_buffers()

    def cleanup(self):
        pass

class MidiInterface:
    """MIDI interface"""
    def __init__(self, transport):
        self.transport = transport

    def flush_buffers(self):
        self.transport.flush_buffers()

    def subscribe(self, callback, message_types=None, channels=None, cc_numbers=None):
        return self.transport.subscribe(callback, message_types, channels, cc_numbers)

    def unsubscribe(self, subscription):
        self.transport.unsubscribe(subscription)

    def send(self, message):
        """Send raw MIDI message bytes"""
        if isinstance(message, (bytes, bytearray)):
            self.transport.write(message)

    def reset_input_buffer(self):
        self.transport.flush_buffers()

    def reset_output_buffer(self):
        self.transport.flush_buffers()

    def cleanup(self):
        pass

class UartManager:
    """Singleton manager for UART interfaces"""
    _instance = None
    _transport = None
    _text_protocol = None
    _midi = None

    @classmethod
    def initialize(cls):
        if cls._instance is None:
            _log("Initializing UART Manager")
            cls._instance = cls()
            cls._transport = UartTransport(
                tx_pin=UART_TX,
                rx_pin=UART_RX,
                baudrate=UART_BAUDRATE,
                timeout=UART_TIMEOUT
            )
            cls._text_protocol = TextProtocol(cls._transport)
            cls._midi = MidiInterface(cls._transport)
            _log("UART Manager initialized")
        return cls._instance

    @classmethod
    def get_interfaces(cls):
        if cls._instance is None:
            cls.initialize()
        return cls._transport, cls._text_protocol

    @classmethod
    def get_midi_interface(cls):
        if cls._instance is None:
            cls.initialize()
        return cls._midi

    @classmethod
    def cleanup(cls):
        _log("Cleaning up UART Manager")
        if cls._transport:
            cls._transport.cleanup()
        cls._transport = None
        cls._text_protocol = None
        cls._midi = None
        cls._instance = None
        _log("UART Manager cleanup complete")
