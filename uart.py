"""UART interface system providing unified communication protocols for the Candide synthesizer."""

import time
import busio
from adafruit_midi import MIDI
from adafruit_midi.midi_message import MIDIMessage, MIDIBadEvent, MIDIUnknownEvent
from adafruit_midi.control_change import ControlChange
from adafruit_midi.note_on import NoteOn 
from adafruit_midi.note_off import NoteOff
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.channel_pressure import ChannelPressure
from adafruit_midi.system_exclusive import SystemExclusive
from adafruit_midi.timing_clock import TimingClock
from constants import (
    UART_TX, UART_RX, UART_BAUDRATE, UART_TIMEOUT
)

def _log(message, is_error=False):
    """Log messages, only showing UART prefix for errors"""
    if is_error:
        print("[UART  ] " + str(message))
    else:
        print(str(message))

class MidiSubscription:
    """Represents a subscription to specific MIDI message types"""
    def __init__(self, callback, message_types=None, channels=None, cc_numbers=None):
        """
        Args:
            callback: Function to call when matching MIDI is received
            message_types: List of MIDI message classes to listen for (NoteOn, ControlChange, etc)
            channels: List of channels to listen on (None = all channels)
            cc_numbers: List of CC numbers to listen for (only for ControlChange messages)
        """
        self.callback = callback
        self.message_types = message_types if message_types is not None else []
        self.channels = channels if channels is not None else None  # None means all channels
        self.cc_numbers = cc_numbers if cc_numbers is not None else None

    def matches(self, message):
        """Check if a MIDI message matches this subscription"""
        if not self.message_types or type(message) in self.message_types:
            if self.channels is None or message.channel in self.channels:
                if isinstance(message, ControlChange) and self.cc_numbers is not None:
                    return message.control in self.cc_numbers
                return True
        return False

class UartTransport:
    def __init__(self, tx_pin=UART_TX, rx_pin=UART_RX, 
                 baudrate=UART_BAUDRATE, timeout=UART_TIMEOUT):
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.baudrate = baudrate
        self.timeout = timeout
        self.subscribers = []
        self._initialize_uart()
        
        self.midi = MIDI(
            midi_in=self.uart,
            midi_out=self.uart,  # Keep for protocol handling
            in_channel=None,     # Listen on all channels
            out_channel=0,
            in_buf_size=128,     # Larger buffer for SysEx
            debug=True           # Can be set to False in production
        )

    def _initialize_uart(self):
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
            _log("[UART  ] UART initialized: baudrate={}, timeout={}".format(
                self.baudrate, self.timeout), is_error=True)
        except Exception as e:
            _log("[UART  ] UART initialization failed: " + str(e), is_error=True)
            raise

    def subscribe(self, callback, message_types=None, channels=None, cc_numbers=None):
        """Subscribe to specific MIDI messages"""
        subscription = MidiSubscription(callback, message_types, channels, cc_numbers)
        self.subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription):
        """Remove a subscription"""
        if subscription in self.subscribers:
            self.subscribers.remove(subscription)

    @property
    def in_waiting(self):
        return self.uart.in_waiting or 0

    def write(self, data):
        if data:
            return self.uart.write(data)
        return 0

    def read(self, size=None):
        if self.in_waiting:
            data = self.uart.read()
            if data:
                return data
        return None

    def log_incoming_data(self):
        """Process and distribute incoming MIDI data to subscribers"""
        if self.in_waiting:
            msg = self.midi.receive()
            if msg is not None:
                # Log the message if in debug mode
                if isinstance(msg, NoteOn):
                    _log(f"[UART  ] 🎵 MIDI: Note On - note={msg.note}, velocity={msg.velocity}, channel={msg.channel+1}")
                elif isinstance(msg, NoteOff):
                    _log(f"[UART  ]🎵 MIDI: Note Off - note={msg.note}, velocity={msg.velocity}, channel={msg.channel+1}")
                elif isinstance(msg, ControlChange):
                    _log(f"[UART  ]🎵 MIDI: CC - control={msg.control}, value={msg.value}, channel={msg.channel+1}")
                elif isinstance(msg, ChannelPressure):
                    _log(f"[UART  ]🎵 MIDI: Channel Pressure - pressure={msg.pressure}, channel={msg.channel+1}")
                elif isinstance(msg, PitchBend):
                    bend_value = msg.pitch_bend - 8192
                    _log(f"[UART  ]🎵 MIDI: Pitch Bend - value={bend_value} (raw={msg.pitch_bend}), channel={msg.channel+1}")
                elif isinstance(msg, MIDIBadEvent):
                    # Skip logging bad events - they're just filtered messages
                    pass
                elif isinstance(msg, MIDIUnknownEvent):
                    _log(f"[UART  ]MIDI Warning: Unknown status: {msg.status}", is_error=True)
                
                # Only distribute valid MIDI messages that match subscriptions
                if not isinstance(msg, (MIDIBadEvent, MIDIUnknownEvent)):
                    # Distribute to matching subscribers
                    for subscription in self.subscribers:
                        if subscription.matches(msg):
                            try:
                                subscription.callback(msg)
                            except Exception as e:
                                _log(f"[UART  ] Error in MIDI subscriber callback: {e}", is_error=True)

    def flush_buffers(self):
        """Flush input/output buffers"""
        while self.in_waiting:
            self.read()

    def cleanup(self):
        """Clean up resources"""
        if hasattr(self, 'uart'):
            _log("[UART  ] Cleaning up UART", is_error=True)
            self.flush_buffers()
            self.uart.deinit()
        self.subscribers.clear()

class TextProtocol:
    """Maintained for backward compatibility"""
    def __init__(self, transport):
        self.transport = transport
        self.message_timeout = 0.05

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
    def __init__(self, transport):
        self.transport = transport

    def flush_buffers(self):
        """Delegate buffer flushing to transport"""
        self.transport.flush_buffers()

    def subscribe(self, callback, message_types=None, channels=None, cc_numbers=None):
        """Subscribe to specific MIDI messages"""
        return self.transport.subscribe(callback, message_types, channels, cc_numbers)

    def unsubscribe(self, subscription):
        """Remove a subscription"""
        self.transport.unsubscribe(subscription)

    def send(self, message):
        """Send a MIDI message through the transport"""
        if hasattr(self.transport, 'midi'):
            self.transport.midi.send(message)

    def reset_input_buffer(self):
        """Reset the input buffer"""
        self.transport.flush_buffers()

    def reset_output_buffer(self):
        """Reset the output buffer"""
        self.transport.flush_buffers()

    def cleanup(self):
        pass

class UartManager:
    _instance = None
    _transport = None
    _text_protocol = None
    _midi = None

    @classmethod
    def initialize(cls):
        if cls._instance is None:
            _log("[UART  ] Initializing UART Manager", is_error=True)
            cls._instance = cls()
            cls._transport = UartTransport(
                tx_pin=UART_TX,
                rx_pin=UART_RX,
                baudrate=UART_BAUDRATE,
                timeout=UART_TIMEOUT
            )
            cls._text_protocol = TextProtocol(cls._transport)
            cls._midi = MidiInterface(cls._transport)
            _log("[UART  ] UART Manager initialized", is_error=True)
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
        _log("[UART  ] Cleaning up UART Manager", is_error=True)
        if cls._transport:
            cls._transport.cleanup()
        cls._transport = None
        cls._text_protocol = None
        cls._midi = None
        cls._instance = None
        _log("[UART  ] UART Manager cleanup complete", is_error=True)
