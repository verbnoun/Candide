"""UART interface system providing unified communication protocols."""

import time
import busio
import sys
from constants import (
    UART_TX, UART_RX, UART_BAUDRATE, UART_TIMEOUT,
    MESSAGE_TIMEOUT
)
from logging import log, TAG_UART

class UartTransport:
    """UART transport layer"""
    def __init__(self, tx_pin=UART_TX, rx_pin=UART_RX, 
                 baudrate=UART_BAUDRATE, timeout=UART_TIMEOUT):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.baudrate = baudrate
        self.timeout = timeout
        self._tx_queue = []       # Simple list for CircuitPython
        self._tx_busy = False     # Flag to track if currently sending
        self._initialize_uart()

    def _initialize_uart(self):
        """Initialize UART with specified parameters"""
        try:
            self.uart = busio.UART(self.tx_pin, self.rx_pin,
                                 baudrate=self.baudrate,
                                 timeout=self.timeout)
            log(TAG_UART, f"UART initialized: baudrate={self.baudrate}, timeout={self.timeout}")
        except Exception as e:
            log(TAG_UART, f"UART initialization failed: {str(e)}", is_error=True)
            raise

    def write(self, data):
        """Write data to UART"""
        if not data:
            return 0
            
        # Convert to bytes if string
        data_bytes = bytes(data) if isinstance(data, str) else data
        
        # Add to queue
        self._tx_queue.append(data_bytes)
        
        # Process queue if not busy
        if not self._tx_busy:
            return self._process_tx_queue()
        return len(data_bytes)  # Return length of queued data

    def _process_tx_queue(self):
        """Process queued TX messages one at a time"""
        if self._tx_busy or not self._tx_queue:
            return 0

        try:
            self._tx_busy = True
            data = self._tx_queue.pop(0)  # Use pop(0) instead of popleft()
            bytes_written = self.uart.write(data)
            return bytes_written
        except Exception as e:
            log(TAG_UART, f"TX error: {str(e)}", is_error=True)
            return 0
        finally:
            self._tx_busy = False
            # Process next message if queue not empty
            if self._tx_queue:
                self._process_tx_queue()

    def read(self, size=None):
        """Read from UART"""
        data = self.uart.read(size) if size is not None else self.uart.read()
        if data:
            # Convert bytes to hex representation for logging
            hex_data = ' '.join([f'0x{b:02x}' for b in data])
            log(TAG_UART, f"Received bytes: {hex_data}")
        return data

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
        # Clear TX queue
        self._tx_queue.clear()
        self._tx_busy = False
        log(TAG_UART, "Buffers flushed")

    def cleanup(self):
        """Clean up resources"""
        if hasattr(self, 'uart'):
            log(TAG_UART, "Cleaning up UART")
            self.flush_buffers()
            self.uart.deinit()

class TextProtocol:
    """Text protocol interface"""
    def __init__(self, transport):
        self.transport = transport
        self.message_timeout = MESSAGE_TIMEOUT
        self._message_counter = 0  # Counter for message numbering (0-9)

    def write(self, message):
        if not isinstance(message, str):
            message = str(message)
        # Get current counter value and increment
        n = self._message_counter
        self._message_counter = (self._message_counter + 1) % 10  # Wrap 0-9
        # Add numbered brackets to all messages
        message = f"[{n}[{message.strip()}]{n}]"
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
            log(TAG_UART, "Initializing UART Manager")
            cls._instance = cls()
            cls._transport = UartTransport(
                tx_pin=UART_TX,
                rx_pin=UART_RX,
                baudrate=UART_BAUDRATE,
                timeout=UART_TIMEOUT
            )
            cls._text_protocol = TextProtocol(cls._transport)
            # Note: midi interface will be initialized by midi.py
            log(TAG_UART, "UART Manager initialized")
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
        log(TAG_UART, "Cleaning up UART Manager")
        if cls._transport:
            cls._transport.cleanup()
        cls._transport = None
        cls._text_protocol = None
        cls._midi = None
        cls._instance = None
        log(TAG_UART, "UART Manager cleanup complete")
