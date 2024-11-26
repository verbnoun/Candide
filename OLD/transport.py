"""
Transport Layer Management Module

Provides abstract and concrete implementations for 
communication transport mechanisms in the Candide Synthesizer.

Key Responsibilities:
- Define abstract transport interface
- Provide concrete UART and text protocol implementations
- Handle low-level communication protocols
- Manage buffer flushing and message timing
- Support extensible communication strategies
"""

import time
import sys
import busio
from constants import *

class TransportProtocol:
    """Abstract base class for transport protocols"""
    def __init__(self):
        self.last_write = 0
        self.message_timeout = 0.1  # Default timeout

    def write(self, message):
        """Abstract method for writing messages"""
        raise NotImplementedError("Subclasses must implement write method")

    def read(self):
        """Abstract method for reading messages"""
        raise NotImplementedError("Subclasses must implement read method")

    def flush_buffers(self):
        """Abstract method for clearing communication buffers"""
        raise NotImplementedError("Subclasses must implement flush_buffers method")

    def cleanup(self):
        """Abstract method for cleaning up transport resources"""
        raise NotImplementedError("Subclasses must implement cleanup method")

    def _log(self, message):
        """Conditional logging with consistent formatting"""
        RED = "\033[31m"
        WHITE = "\033[37m"
        RESET = "\033[0m"
        
        color = RED if "[ERROR]" in message else WHITE
        print(f"{color}[TRANSPORT] {message}{RESET}", file=sys.stderr)

class UartTransport(TransportProtocol):
    """UART-specific transport implementation"""
    def __init__(self, tx_pin, rx_pin, baudrate=MIDI_BAUDRATE, timeout=UART_TIMEOUT):
        super().__init__()
        self._log("Initializing UART transport...")
        
        try:
            self.uart = busio.UART(
                tx=tx_pin,
                rx=rx_pin,
                baudrate=baudrate,
                timeout=timeout,
                bits=8,
                parity=None,
                stop=1
            )
            self._log("UART transport initialized successfully")
        except Exception as e:
            self._log(f"[ERROR] UART initialization failed: {str(e)}")
            raise

    @property
    def in_waiting(self):
        """Number of bytes waiting to be read"""
        return self.uart.in_waiting

    def write(self, message):
        """Write message to UART with timing control"""
        current_time = time.monotonic()
        delay_needed = self.message_timeout - (current_time - self.last_write)
        
        if delay_needed > 0:
            time.sleep(delay_needed)
        
        if isinstance(message, str):
            message = message.encode('utf-8')
        
        result = self.uart.write(message)
        self.last_write = time.monotonic()
        return result

    def read(self, size=None):
        """Read from UART"""
        if size is None:
            return self.uart.read()
        return self.uart.read(size)

    def flush_buffers(self, timeout=5):
        """Clear UART input buffers"""
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if self.uart.in_waiting:
                self.uart.read()
            else:
                break

    def cleanup(self):
        """Clean shutdown of UART"""
        if hasattr(self, 'uart'):
            self._log("Deinitializing UART...")
            self.flush_buffers()
            self.uart.deinit()

class TextProtocol(TransportProtocol):
    """Text protocol implementation that uses an existing transport"""
    def __init__(self, transport):
        super().__init__()
        self.transport = transport
        self.message_timeout = 0.05  # Shorter timeout for text messages
        self._log("Text protocol initialized")

    def write(self, message):
        """Write text message with protocol-specific handling"""
        if not isinstance(message, str):
            message = str(message)
        
        # Ensure message ends with newline for protocol consistency
        if not message.endswith('\n'):
            message += '\n'
        
        current_time = time.monotonic()
        delay_needed = self.message_timeout - (current_time - self.last_write)
        if delay_needed > 0:
            time.sleep(delay_needed)
            
        result = self.transport.write(message)
        self.last_write = time.monotonic()
        return result

    def read(self, size=None):
        """Read using underlying transport"""
        return self.transport.read(size)

    def flush_buffers(self):
        """Flush using underlying transport"""
        self.transport.flush_buffers()

    def cleanup(self):
        """No cleanup needed as we don't own the transport"""
        pass

class TransportFactory:
    """Factory for creating transport instances"""
    @staticmethod
    def create_uart_transport(tx_pin, rx_pin, **kwargs):
        """Create a UART transport"""
        return UartTransport(tx_pin, rx_pin, **kwargs)

    @staticmethod
    def create_text_protocol(transport):
        """Create a text protocol using existing transport"""
        return TextProtocol(transport)
