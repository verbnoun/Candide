"""UART interface system providing unified communication protocols for the Candide synthesizer."""

import time
import busio
from adafruit_midi import MIDI
from adafruit_midi.midi_message import MIDIMessage
from adafruit_midi.control_change import ControlChange
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.channel_pressure import ChannelPressure
from constants import (
    UART_TX, UART_RX, UART_BAUDRATE, UART_TIMEOUT
)

def _log(message):
    print("[UART  ] " + str(message))

def _format_bytes(data):
    """Format bytes as hex string with interpretation"""
    if not data:
        return "empty"
    return ' '.join([f"{b:#04x}" for b in data])

class TransportProtocol:
    def __init__(self):
        self.last_write = 0
        self.message_timeout = 0.1

    def write(self, message):
        raise NotImplementedError("Subclasses must implement write method")

    def read(self, size=None):
        raise NotImplementedError("Subclasses must implement read method")

    def flush_buffers(self):
        raise NotImplementedError("Subclasses must implement flush_buffers method")

    def cleanup(self):
        raise NotImplementedError("Subclasses must implement cleanup method")

class UartTransport(TransportProtocol):
    def __init__(self, tx_pin=UART_TX, rx_pin=UART_RX, 
                 baudrate=UART_BAUDRATE, timeout=UART_TIMEOUT):
        super().__init__()
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.baudrate = baudrate
        self.timeout = timeout
        self._initialize_uart()
        self.read_buffer_size = 64
        self._buffer = bytearray()

    def _initialize_uart(self):
        try:
            self.uart = busio.UART(
                tx=self.tx_pin,
                rx=self.rx_pin,
                baudrate=self.baudrate,
                timeout=0,
                bits=8,
                parity=None,
                stop=1
            )
            _log("UART transport initialized successfully")
        except Exception as e:
            _log("[ERROR] UART initialization failed: " + str(e))
            raise

    @property
    def in_waiting(self):
        waiting = len(self._buffer) + (self.uart.in_waiting or 0)
        if waiting > 0:
            _log(f"Data waiting: {waiting} bytes (buffer: {len(self._buffer)}, uart: {self.uart.in_waiting or 0})")
        return waiting

    def write(self, message):
        if isinstance(message, str):
            message = message.encode('utf-8')
        _log(f"Writing bytes: {_format_bytes(message)}")
        return self.uart.write(message)

    def read(self, size=None):
        # Read new data from UART into our buffer
        if self.uart.in_waiting:
            new_data = self.uart.read()
            if new_data:
                _log(f"Received raw bytes: {_format_bytes(new_data)}")
                self._buffer.extend(new_data)

        # If no size specified or not enough data, return empty bytes
        if size is None or size > len(self._buffer):
            if self._buffer:
                data = bytes(self._buffer)
                _log(f"Returning all buffer data: {_format_bytes(data)}")
                self._buffer = bytearray()
                return data
            return b''  # Return empty bytes instead of None
        
        # If size specified and we have enough data
        data = bytes(self._buffer[:size])
        _log(f"Returning {size} bytes: {_format_bytes(data)}")
        self._buffer = self._buffer[size:]
        return data

    def log_incoming_data(self):
        """Read incoming data without logging"""
        if self.in_waiting:
            self.read(self.read_buffer_size)

    def flush_buffers(self, timeout=1):
        start_time = time.monotonic()
        flushed_data = []
        while time.monotonic() - start_time < timeout:
            if self.uart.in_waiting:
                data = self.uart.read()
                if data:
                    flushed_data.extend(data)
            else:
                break
        if flushed_data:
            _log(f"Flushed bytes: {_format_bytes(bytes(flushed_data))}")
        self._buffer = bytearray()

    def cleanup(self):
        if hasattr(self, 'uart'):
            self.flush_buffers()
            self.uart.deinit()

class TextProtocol(TransportProtocol):
    def __init__(self, transport):
        super().__init__()
        self.transport = transport
        self.message_timeout = 0.05

    def write(self, message):
        if not isinstance(message, str):
            message = str(message)
        if not message.endswith('\n'):
            message += '\n'
        return self.transport.write(message)

    def read(self, size=None):
        return self.transport.read(size)

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

class MidiProtocol(TransportProtocol):
    def __init__(self, transport):
        super().__init__()
        self.transport = transport
        self.midi = MIDI(
            midi_in=self.transport,
            midi_out=self.transport,
            in_channel=None,  # Listen on all channels
            out_channel=0,    # Default to channel 1
            in_buf_size=128   # Larger buffer for safety
        )
        self.message_timeout = 0.001  # Short timeout for MIDI
        self._last_message = None
        self._raw_buffer = bytearray()

    def _format_midi_message(self, msg):
        """Format MIDI message details for logging"""
        if isinstance(msg, ControlChange):
            return f"Control Change: control={msg.control}, value={msg.value}, channel={msg.channel}"
        elif isinstance(msg, NoteOn):
            return f"Note On: note={msg.note}, velocity={msg.velocity}, channel={msg.channel}"
        elif isinstance(msg, NoteOff):
            return f"Note Off: note={msg.note}, velocity={msg.velocity}, channel={msg.channel}"
        elif isinstance(msg, PitchBend):
            return f"Pitch Bend: value={msg.pitch_bend}, channel={msg.channel}"
        elif isinstance(msg, ChannelPressure):
            return f"Channel Pressure: pressure={msg.pressure}, channel={msg.channel}"
        else:
            return f"MIDI Message: {msg}"

    @property
    def last_message(self):
        """Get the last received MIDI message"""
        return self._last_message

    def write(self, message):
        if isinstance(message, MIDIMessage):
            _log("MIDI OUT: " + self._format_midi_message(message))
            return self.midi.send(message)
        return None

    def read(self, size=None):
        """Read and parse MIDI messages from the transport"""
        # First try to parse a MIDI message
        try:
            msg = self.midi.receive()
            if msg:
                self._last_message = msg
                _log("Parsed MIDI: " + self._format_midi_message(msg))
                return msg
        except Exception as e:
            _log(f"Error parsing MIDI: {e}")

        # If no MIDI message, get raw bytes
        raw_data = self.transport.read(size)
        if raw_data:
            self._raw_buffer.extend(raw_data)
            # Check if we have a complete 3-byte MIDI message
            if len(self._raw_buffer) >= 3:
                msg_bytes = bytes(self._raw_buffer[:3])
                self._raw_buffer = self._raw_buffer[3:]
                _log(f"Raw MIDI bytes: {_format_bytes(msg_bytes)}")
                return msg_bytes
        return None

    def flush_buffers(self):
        self._raw_buffer = bytearray()
        self.transport.flush_buffers()

    def cleanup(self):
        self.flush_buffers()

class UartManager:
    _instance = None
    _transport = None
    _text_protocol = None
    _midi_protocol = None

    @classmethod
    def initialize(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._transport = UartTransport(
                tx_pin=UART_TX,
                rx_pin=UART_RX,
                baudrate=UART_BAUDRATE,
                timeout=0
            )
            cls._text_protocol = TextProtocol(cls._transport)
            cls._midi_protocol = MidiProtocol(cls._transport)
            _log("UART Manager initialized")
        return cls._instance

    @classmethod
    def get_interfaces(cls):
        """For backward compatibility, only return transport and text protocol"""
        if cls._instance is None:
            cls.initialize()
        return cls._transport, cls._text_protocol

    @classmethod
    def get_midi_interface(cls):
        """New method to get MIDI interface separately"""
        if cls._instance is None:
            cls.initialize()
        return cls._midi_protocol

    @classmethod
    def cleanup(cls):
        if cls._transport:
            cls._transport.cleanup()
            cls._transport = None
        cls._text_protocol = None
        cls._midi_protocol = None
        cls._instance = None
        _log("UART Manager cleaned up")

class TransportFactory:
    @staticmethod
    def create_uart_transport(tx_pin=UART_TX, rx_pin=UART_RX, **kwargs):
        return UartTransport(tx_pin, rx_pin, **kwargs)

    @staticmethod
    def create_text_protocol(transport):
        return TextProtocol(transport)

    @staticmethod
    def create_midi_protocol(transport):
        return MidiProtocol(transport)

    @staticmethod
    def create_uart_interfaces(tx_pin=UART_TX, rx_pin=UART_RX, **kwargs):
        return UartManager.get_interfaces()
