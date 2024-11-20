"""
MIDI Message Processing Module

Handles MIDI communication and message parsing.
Supports full MPE by accepting all MIDI channels (0-15).
Simply validates and passes through MIDI messages with channel information.
"""

import busio
import time
import sys
from adafruit_midi import MIDI
from constants import *

def _format_log_message(message):
    """
    Format a dictionary message for console logging with specific indentation rules.
    
    Args:
        message (dict): Message to format
    
    Returns:
        str: Formatted message string
    """
    def _format_value(value, indent_level=0):
        """Recursively format values with proper indentation."""
        base_indent = ' ' * 0
        extra_indent = ' ' * 2
        indent = base_indent + ' ' * (4 * indent_level)
        
        if isinstance(value, dict):
            lines = ['{']
            for k, v in value.items():
                formatted_v = _format_value(v, indent_level + 1)
                lines.append(f"{indent + extra_indent}'{k}': {formatted_v},")
            lines.append(f"{indent}}}")
            return '\n'.join(lines)
        elif isinstance(value, str):
            return f"'{value}'"
        else:
            return str(value)
    
    return _format_value(message)

def _log(message):
    """
    Conditional logging function that respects MIDI_DEBUG flag.
    Args:
        message (str or dict): Message to log
    """
    RED = "\033[31m"
    PALE_YELLOW = "\033[93m"
    RESET = "\033[0m" 
    
    if MIDI_DEBUG:
        if "[ERROR]" in str(message):
            color = RED
        else:
            color = PALE_YELLOW
        
        # If message is a dictionary, format with custom indentation
        if isinstance(message, dict):
            formatted_message = _format_log_message(message)
            print(f"{color}{formatted_message}{RESET}", file=sys.stderr)
        else:
            print(f"{color}[MIDI  ] {message}{RESET}", file=sys.stderr)

class MidiUart:
    """Handles low-level UART communication"""
    def __init__(self, midi_tx, midi_rx):
        _log("Initializing UART")
        self.uart = busio.UART(
            tx=midi_tx,
            rx=midi_rx,
            baudrate=MIDI_BAUDRATE,
            timeout=UART_TIMEOUT
        )
        # Accept all MIDI channels 0-15 for full MPE support
        self.midi = MIDI(
            midi_in=self.uart,
            in_channel=tuple(range(16))  # All MIDI channels
        )
        _log("UART initialized successfully")

    def read_byte(self):
        """Read a single byte from UART if available"""
        if self.uart.in_waiting:
            return self.uart.read(1)[0]
        return None

    def write(self, data):
        """Write data to UART"""
        _log(f"Writing {len(data)} bytes to UART")
        return self.uart.write(data)

    @property
    def in_waiting(self):
        """Number of bytes waiting to be read"""
        return self.uart.in_waiting

    def cleanup(self):
        """Clean shutdown of UART"""
        if self.uart:
            _log("Deinitializing UART")
            self.uart.deinit()

class MidiLogic:
    """Handles MIDI message parsing and validation"""
    def __init__(self, uart, text_callback):
        _log("Initializing MIDI Logic")
        self.uart = uart
        self.text_callback = text_callback
        self.midi = MIDI(midi_in=self.uart, in_channel=0)

    def check_for_messages(self):
        """Check for and parse MIDI messages"""
        try:
            while self.uart.in_waiting:
                # Read status byte
                status_byte = self.uart.read(1)
                if not status_byte:
                    break

                status = status_byte[0]
                if status & 0x80:  # Is this a status byte?
                    channel = status & 0x0F
                    msg_type = status & 0xF0
                    event = None

                    # Parse different message types
                    if msg_type == MidiMessageType.NOTE_ON:
                        note_byte = self.uart.read(1)
                        velocity_byte = self.uart.read(1)
                        if note_byte is None or velocity_byte is None:
                            _log("[ERROR] Incomplete NOTE_ON message")
                            break
                        event = {
                            'type': 'note_on',
                            'channel': channel,
                            'data': {
                                'note': note_byte[0],
                                'velocity': velocity_byte[0]
                            }
                        }
                        _log(f"Received NOTE_ON: Channel {channel}, Note {note_byte[0]}, Velocity {velocity_byte[0]}")
                        _log(event)

                    elif msg_type == MidiMessageType.NOTE_OFF:
                        note_byte = self.uart.read(1)
                        velocity_byte = self.uart.read(1)
                        if note_byte is None or velocity_byte is None:
                            _log("[ERROR] Incomplete NOTE_OFF message")
                            break
                        event = {
                            'type': 'note_off',
                            'channel': channel,
                            'data': {
                                'note': note_byte[0],
                                'velocity': velocity_byte[0]
                            }
                        }
                        _log(f"Received NOTE_OFF: Channel {channel}, Note {note_byte[0]}, Velocity {velocity_byte[0]}")
                        _log(event)

                    elif msg_type == MidiMessageType.CONTROL_CHANGE:
                        control_byte = self.uart.read(1)
                        value_byte = self.uart.read(1)
                        if control_byte is None or value_byte is None:
                            _log("[ERROR] Incomplete CONTROL_CHANGE message")
                            break
                        event = {
                            'type': 'cc',
                            'channel': channel,
                            'data': {
                                'number': control_byte[0],
                                'value': value_byte[0]
                            }
                        }
                        _log(f"Received CC:")
                        _log(event)

                    elif msg_type == MidiMessageType.CHANNEL_PRESSURE:
                        pressure_byte = self.uart.read(1)
                        if pressure_byte is None:
                            _log("[ERROR] Incomplete CHANNEL_PRESSURE message")
                            break
                        event = {
                            'type': 'pressure',
                            'channel': channel,
                            'data': {
                                'value': pressure_byte[0]
                            }
                        }
                        _log(f"Received CHANNEL_PRESSURE: Channel {channel}, Pressure {pressure_byte[0]}")
                        _log(event)

                    elif msg_type == MidiMessageType.PITCH_BEND:
                        lsb_byte = self.uart.read(1)
                        msb_byte = self.uart.read(1)
                        if lsb_byte is None or msb_byte is None:
                            _log("[ERROR] Incomplete PITCH_BEND message")
                            break
                        bend_value = (msb_byte[0] << 7) | lsb_byte[0]
                        event = {
                            'type': 'pitch_bend',
                            'channel': channel,
                            'data': {
                                'value': bend_value
                            }
                        }
                        _log(f"Received PITCH_BEND: Channel {channel}, Value {bend_value}")
                        _log(event)

                    # Pass parsed message to callback if valid
                    if event and self.text_callback:
                        self.text_callback(event)

        except Exception as e:
            _log(f"[ERROR] Error reading UART: {str(e)}")

    def cleanup(self):
        """Clean shutdown"""
        _log("Cleaning up MIDI system...")
