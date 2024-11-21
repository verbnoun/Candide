"""
MIDI Message Processing Module

Handles MIDI communication, message parsing, and routing.
Supports full MPE by accepting all MIDI channels (0-15).
Routes MIDI messages to router and connection manager.
"""

import time
import sys
import binascii
from adafruit_midi import MIDI
from constants import *

def _format_log_message(message):
    """Format a dictionary message for console logging"""
    def _format_value(value, indent_level=0):
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
    """Conditional logging function"""
    RED = "\033[31m"
    PALE_YELLOW = "\033[93m"
    RESET = "\033[0m" 
    
    if MIDI_DEBUG:
        if "[ERROR]" in str(message):
            color = RED
        else:
            color = PALE_YELLOW
        
        if isinstance(message, dict):
            formatted_message = _format_log_message(message)
            print(f"{color}{formatted_message}{RESET}", file=sys.stderr)
        else:
            print(f"{color}[MIDI  ] {message}{RESET}", file=sys.stderr)

class MidiLogic:
    """Handles MIDI message parsing and routing"""
    def __init__(self, uart, router, connection_manager, voice_manager):
        _log("Initializing MIDI Logic")
        self.uart = uart  # Now expects a transport instance
        self.router = router
        self.connection_manager = connection_manager
        self.voice_manager = voice_manager
        
        # Track MPE state per channel
        self.channel_state = {}
        for channel in range(16):
            self.channel_state[channel] = {
                'pitch_bend': 8192,  # Center value
                'pressure': 0,
                'cc74': 64,  # Center value for timbre
                'in_mpe_setup': False
            }
            
        # Track partial message state
        self.partial_message = {
            'status': None,
            'bytes_received': [],
            'expected_bytes': 0
        }

    def _hex_dump(self, data):
        """Create a hex dump of the given data"""
        if not data:
            return "No data to dump"
        
        if isinstance(data, list):
            data = bytes(data)
        
        hex_str = binascii.hexlify(data).decode('utf-8')
        hex_groups = [hex_str[i:i+2] for i in range(0, len(hex_str), 2)]
        
        lines = []
        for i in range(0, len(hex_groups), 8):
            line_group = hex_groups[i:i+8]
            hex_line = ' '.join(line_group)
            ascii_line = ''.join([chr(int(h, 16)) if 32 <= int(h, 16) < 127 else '.' for h in line_group])
            lines.append(f"{hex_line:<24} {ascii_line}")
        
        return "\n".join(lines)

    def check_for_messages(self):
        """Check for and parse MIDI messages"""
        try:
            while self.uart.in_waiting:
                # If no partial message is being tracked, read a new status byte
                if not self.partial_message['status']:
                    status_byte = self.uart.read(1)
                    if not status_byte:
                        break

                    status = status_byte[0]
                    if status & 0x80:  # Is this a status byte?
                        channel = status & 0x0F
                        msg_type = status & 0xF0

                        # Determine expected number of data bytes based on message type
                        if msg_type in [MidiMessageType.NOTE_ON, MidiMessageType.NOTE_OFF, MidiMessageType.CONTROL_CHANGE]:
                            expected_bytes = 2
                        elif msg_type == MidiMessageType.CHANNEL_PRESSURE:
                            expected_bytes = 1
                        elif msg_type == MidiMessageType.PITCH_BEND:
                            expected_bytes = 2
                        else:
                            # Unsupported message type, skip
                            continue

                        # Track partial message
                        self.partial_message = {
                            'status': status,
                            'channel': channel,
                            'msg_type': msg_type,
                            'bytes_received': [],
                            'expected_bytes': expected_bytes
                        }

                # Read data bytes for the current message
                while len(self.partial_message['bytes_received']) < self.partial_message['expected_bytes']:
                    data_byte = self.uart.read(1)
                    if data_byte is None:
                        # Not enough bytes yet, wait for next iteration
                        return
                    self.partial_message['bytes_received'].append(data_byte[0])

                # Process the complete message
                status = self.partial_message['status']
                channel = self.partial_message['channel']
                msg_type = self.partial_message['msg_type']
                data_bytes = self.partial_message['bytes_received']
                event = None

                if msg_type == MidiMessageType.NOTE_ON:
                    event = {
                        'type': 'note_on',
                        'channel': channel,
                        'data': {
                            'note': data_bytes[0],
                            'velocity': data_bytes[1],
                            # Include current MPE state
                            'initial_pitch_bend': self.channel_state[channel]['pitch_bend'],
                            'initial_pressure': self.channel_state[channel]['pressure'],
                            'initial_timbre': self.channel_state[channel]['cc74']
                        }
                    }
                    _log(f"Received from Controller: Note On")
                    _log(event)
                    self.channel_state[channel]['in_mpe_setup'] = False

                elif msg_type == MidiMessageType.NOTE_OFF:
                    event = {
                        'type': 'note_off',
                        'channel': channel,
                        'data': {
                            'note': data_bytes[0],
                            'velocity': data_bytes[1]
                        }
                    }
                    _log(f"Received from Controller: Note Off")
                    _log(event)

                elif msg_type == MidiMessageType.CONTROL_CHANGE:
                    # Track CC74 (timbre) state
                    if data_bytes[0] == 74:
                        self.channel_state[channel]['cc74'] = data_bytes[1]
                    
                    event = {
                        'type': 'cc',
                        'channel': channel,
                        'data': {
                            'number': data_bytes[0],
                            'value': data_bytes[1]
                        }
                    }
                    _log(f"Received from Controller: CC")
                    _log(event)

                elif msg_type == MidiMessageType.CHANNEL_PRESSURE:
                    # Track pressure state
                    self.channel_state[channel]['pressure'] = data_bytes[0]
                    event = {
                        'type': 'pressure',
                        'channel': channel,
                        'data': {
                            'value': data_bytes[0]
                        }
                    }
                    _log(f"Received from Controller: Channel Pressure")
                    _log(event)

                elif msg_type == MidiMessageType.PITCH_BEND:
                    bend_value = (data_bytes[1] << 7) | data_bytes[0]
                    # Track pitch bend state
                    self.channel_state[channel]['pitch_bend'] = bend_value
                    event = {
                        'type': 'pitch_bend',
                        'channel': channel,
                        'data': {
                            'value': bend_value
                        }
                    }
                    _log(f"Received from Controller: Pitch Bend")
                    _log(event)

                # Route message to both connection manager and router
                if event:
                    # Always send to connection manager for handshake detection
                    self.connection_manager.handle_midi_message(event)
                    
                    # Send to router if connection manager is in connected state
                    if self.connection_manager.is_connected():
                        self.router.process_message(event, self.voice_manager)

                # Reset partial message tracking
                self.partial_message = {
                    'status': None,
                    'bytes_received': [],
                    'expected_bytes': 0
                }

        except Exception as e:
            _log(f"[ERROR] Error reading UART: {str(e)}")

    def cleanup(self):
        """Clean shutdown"""
        _log("Cleaning up MIDI system...")
