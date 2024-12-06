"""UART interface system providing unified communication protocols."""

import time
import busio
import sys
from constants import (
    UART_TX, UART_RX, UART_BAUDRATE, UART_TIMEOUT,
    LOG_UART, LOG_LIGHT_BLUE, LOG_RED, LOG_RESET,
    MESSAGE_TIMEOUT
)

def _log(message, is_error=False):
    """Log messages with UART prefix"""
    color = LOG_RED if is_error else LOG_LIGHT_BLUE
    if is_error:
        print(f"{color}{LOG_UART} [ERROR] {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{LOG_UART} {message}{LOG_RESET}", file=sys.stderr)

class UartTransport:
    """UART transport layer"""
    def __init__(self, tx_pin=UART_TX, rx_pin=UART_RX, 
                 baudrate=UART_BAUDRATE, timeout=UART_TIMEOUT):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.baudrate = baudrate
        self.timeout = timeout
        self._initialize_uart()

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

    def write(self, data):
        """Write data to UART"""
        if data:
            return self.uart.write(bytes(data) if isinstance(data, str) else data)
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

    def flush_buffers(self):
        """Flush UART buffers"""
        try:
            # Try CircuitPython's reset_input_buffer
            self.uart.reset_input_buffer()
        except AttributeError:
            # Fallback for CircuitPython UART
            while self.in_waiting:
                self.uart.read()
        _log("Buffers flushed")

    def cleanup(self):
        """Clean up resources"""
        if hasattr(self, 'uart'):
            _log("Cleaning up UART")
            self.flush_buffers()
            self.uart.deinit()

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
            # Note: midi interface will be initialized by midi.py
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
    def set_midi_interface(cls, midi_interface):
        """Allow setting the MIDI interface from midi.py"""
        cls._midi = midi_interface

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
