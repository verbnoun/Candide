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
from timing import timing_stats, TimingContext

# Buffer threshold for overflow protection
BUFFER_THRESHOLD = 64  # Adjust based on system capabilities

# MIDI Constants
MIDI_NOTE_MIN = 0
MIDI_NOTE_MAX = 127
MIDI_STATUS_MASK = 0x80  # Status byte indicator (bit 7 set)

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
    if not MIDI_DEBUG:
        return
        
    RED = "\033[31m"
    LIGHT_CYAN = "\033[96m"
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        formatted_message = _format_log_message(message)
        print(f"{LIGHT_CYAN}{formatted_message}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message):
            color = RED
        else:
            color = LIGHT_CYAN
        print(f"{color}[MIDI  ] {message}{RESET}", file=sys.stderr)

class MidiLogic:
    """Handles MIDI message parsing and routing"""
    def __init__(self, *, uart=None, router=None, connection_manager=None, voice_manager=None):
        """
        Initialize MIDI Logic with keyword-only arguments
        
        Args:
            uart: Transport instance for MIDI communication
            router: Router for processing MIDI messages
            connection_manager: Connection manager for handshake and state
            voice_manager: Voice manager for synthesizer control
        """
        if uart is None or router is None or connection_manager is None or voice_manager is None:
            raise ValueError("All arguments (uart, router, connection_manager, voice_manager) are required")
        
        _log("Initializing MIDI Logic")
        self.uart = uart
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
                'in_mpe_setup': False,
                'active_notes': set()  # Track active notes per channel
            }
            
        # Track partial message state
        self.reset_partial_message()
        
        # MPE rate limiting configuration
        self.mpec_rate_limit = 60  # Default 100 messages/sec
        self.channel_last_mpec = {channel: 0 for channel in range(16)}
        self.active_mpe_channels = set()

    def reset_partial_message(self):
        """Reset partial message tracking to initial state"""
        self.partial_message = {
            'status': None,
            'bytes_received': [],
            'expected_bytes': 0
        }
        # Reset message timing
        self.current_message_id = None

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

    def _validate_channel(self, channel, note=None):
        """Validate channel and note combination to prevent conflicts"""
        if note is not None:
            # Validate note number range
            if note < MIDI_NOTE_MIN or note > MIDI_NOTE_MAX:
                _log(f"[WARNING] Note number {note} out of valid range (0-127)")
                return False
                
            # Check if note already active on another channel
            for ch, state in self.channel_state.items():
                if ch != channel and note in state['active_notes']:
                    _log(f"[WARNING] Note {note} already active on channel {ch}")
                    return False
        return True

    def _should_process_mpec(self, channel):
        """Determine if an MPE continuous controller message should be processed"""
        now = time.monotonic()
        if channel not in self.active_mpe_channels:
            return True
            
        # Calculate message slots per channel
        active_count = len(self.active_mpe_channels)
        if active_count == 0:
            return True
            
        slot_time = 1.0 / (self.mpec_rate_limit / active_count)
        if now - self.channel_last_mpec[channel] >= slot_time:
            self.channel_last_mpec[channel] = now
            return True
        return False

    def _read_uart_byte(self):
        """Safely read a single byte from UART with error handling"""
        try:
            data = self.uart.read(1)
            if data is None or len(data) == 0:
                return None
            # Start timing on first byte of new message
            if self.current_message_id is None:
                self.current_message_id = timing_stats.start_message_timing()
            return data[0]
        except Exception as e:
            _log(f"[ERROR] UART read error: {str(e)}")
            return None

    def _is_status_byte(self, byte):
        """Check if a byte is a status byte (bit 7 set)"""
        return byte & MIDI_STATUS_MASK == MIDI_STATUS_MASK

    def _process_message(self, message_bytes):
        """Process a complete MIDI message"""
        if not message_bytes or len(message_bytes) < 1:
            return False
            
        try:
            with TimingContext(timing_stats, "midi", self.current_message_id):
                status = message_bytes[0]
                if not self._is_status_byte(status):
                    _log(f"[WARNING] Invalid status byte: 0x{status:02X}")
                    return False
                    
                channel = status & 0x0F
                msg_type = status & 0xF0
                data_bytes = message_bytes[1:]
                
                event = None

                if msg_type == MidiMessageType.NOTE_ON:
                    if len(data_bytes) < 2:
                        _log("[WARNING] Incomplete note on message")
                        return False
                        
                    note = data_bytes[0]
                    if not self._validate_channel(channel, note):
                        return False
                        
                    self.channel_state[channel]['active_notes'].add(note)
                    self.active_mpe_channels.add(channel)
                    
                    event = {
                        'type': 'note_on',
                        'channel': channel,
                        'data': {
                            'note': note,
                            'velocity': data_bytes[1],
                            'initial_pitch_bend': self.channel_state[channel]['pitch_bend'],
                            'initial_pressure': self.channel_state[channel]['pressure'],
                            'initial_timbre': self.channel_state[channel]['cc74']
                        }
                    }
                    _log(f"Received from Controller: Note On")
                    _log(event)
                    self.channel_state[channel]['in_mpe_setup'] = False

                elif msg_type == MidiMessageType.NOTE_OFF:
                    if len(data_bytes) < 2:
                        _log("[WARNING] Incomplete note off message")
                        return False
                        
                    note = data_bytes[0]
                    if note < MIDI_NOTE_MIN or note > MIDI_NOTE_MAX:
                        _log(f"[WARNING] Note off number {note} out of valid range (0-127)")
                        return False
                        
                    if note in self.channel_state[channel]['active_notes']:
                        self.channel_state[channel]['active_notes'].remove(note)
                    
                    if not self.channel_state[channel]['active_notes']:
                        self.active_mpe_channels.discard(channel)
                    
                    event = {
                        'type': 'note_off',
                        'channel': channel,
                        'data': {
                            'note': note,
                            'velocity': data_bytes[1]
                        }
                    }
                    _log(f"Received from Controller: Note Off")
                    _log(event)

                elif msg_type == MidiMessageType.CONTROL_CHANGE:
                    if len(data_bytes) < 2:
                        _log("[WARNING] Incomplete control change message")
                        return False
                        
                    if not self._should_process_mpec(channel):
                        return False
                        
                    if data_bytes[0] == 74:  # CC74 (timbre)
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
                    if len(data_bytes) < 1:
                        _log("[WARNING] Incomplete channel pressure message")
                        return False
                        
                    if not self._should_process_mpec(channel):
                        return False
                        
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
                    if len(data_bytes) < 2:
                        _log("[WARNING] Incomplete pitch bend message")
                        return False
                        
                    if not self._should_process_mpec(channel):
                        return False
                        
                    bend_value = (data_bytes[1] << 7) | data_bytes[0]
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

                # Route message if we created an event
                if event:
                    # Attach timing ID to event for tracking through the chain
                    event['timing_id'] = self.current_message_id
                    
                    # Handle note_off messages with high priority
                    if event['type'] == 'note_off':
                        # Send directly to router, bypassing connection manager
                        self.router.process_message(event, self.voice_manager, high_priority=True)
                    else:
                        self.connection_manager.handle_midi_message(event)
                        if self.connection_manager.is_connected():
                            self.router.process_message(event, self.voice_manager)

        except Exception as e:
            _log(f"[ERROR] Error processing message: {str(e)}")
            return False
        return True

    def check_for_messages(self):
        """Check for and parse MIDI messages"""
        try:
            while self.uart.in_waiting:
                # Check for buffer overflow
                if self.uart.in_waiting > BUFFER_THRESHOLD:
                    _log("[WARNING] Buffer overflow detected - preserving note_off messages")
                    # Scan buffer for note_off messages
                    temp_buffer = self.uart.read(self.uart.in_waiting)
                    if temp_buffer:
                        for i in range(len(temp_buffer)-2):
                            if (temp_buffer[i] & 0xF0) == MidiMessageType.NOTE_OFF:
                                # Process note_off message
                                if i + 2 < len(temp_buffer):
                                    self._process_message(temp_buffer[i:i+3])
                    # Clear remaining buffer
                    self.reset_partial_message()
                    return
                
                # If no partial message is being tracked, read a new status byte
                if not self.partial_message['status']:
                    status_byte = self._read_uart_byte()
                    if status_byte is None:
                        break

                    # Always check for new status byte
                    if self._is_status_byte(status_byte):
                        channel = status_byte & 0x0F
                        msg_type = status_byte & 0xF0
                        _log(f"Status byte: 0x{status_byte:02X}, channel: {channel}, msg_type: 0x{msg_type:02X}")

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
                            'status': status_byte,
                            'channel': channel,
                            'msg_type': msg_type,
                            'bytes_received': [],
                            'expected_bytes': expected_bytes
                        }
                        _log(f"New partial message state: {self.partial_message}")
                    else:
                        # Not a valid status byte, skip
                        _log(f"[WARNING] Skipping invalid status byte: 0x{status_byte:02X}")
                        continue

                # Read data bytes for the current message
                while len(self.partial_message['bytes_received']) < self.partial_message['expected_bytes']:
                    data_byte = self._read_uart_byte()
                    if data_byte is None:
                        # Incomplete message, wait for more data
                        _log("Incomplete data bytes - waiting for more")
                        return
                        
                    # If we get a status byte while reading data bytes, start a new message
                    if self._is_status_byte(data_byte):
                        _log("[WARNING] Got status byte while reading data bytes - starting new message")
                        self.reset_partial_message()
                        # Push the status byte back to be processed
                        status_byte = data_byte
                        channel = status_byte & 0x0F
                        msg_type = status_byte & 0xF0
                        
                        if msg_type in [MidiMessageType.NOTE_ON, MidiMessageType.NOTE_OFF, MidiMessageType.CONTROL_CHANGE]:
                            expected_bytes = 2
                        elif msg_type == MidiMessageType.CHANNEL_PRESSURE:
                            expected_bytes = 1
                        elif msg_type == MidiMessageType.PITCH_BEND:
                            expected_bytes = 2
                        else:
                            continue
                            
                        self.partial_message = {
                            'status': status_byte,
                            'channel': channel,
                            'msg_type': msg_type,
                            'bytes_received': [],
                            'expected_bytes': expected_bytes
                        }
                        _log(f"New partial message state from data byte: {self.partial_message}")
                        continue
                        
                    self.partial_message['bytes_received'].append(data_byte)
                    _log(f"Data bytes received: {self.partial_message['bytes_received']}")

                # Process the complete message
                try:
                    message_bytes = [self.partial_message['status']] + self.partial_message['bytes_received']
                    if not self._process_message(message_bytes):
                        _log("[WARNING] Failed to process message")

                except Exception as e:
                    _log(f"[ERROR] Error processing message: {str(e)}")
                    self.flush_uart_buffer()
                    self.reset_partial_message()
                    return

                # Reset partial message tracking and log
                timing_stats.end_message_timing(self.current_message_id)
                self.reset_partial_message()
                _log("Partial message cleared")

        except Exception as e:
            _log(f"[ERROR] Error reading UART: {str(e)}")
            _log(f"Error occurred with partial message state: {self.partial_message}")
            _log(f"UART in_waiting after error: {self.uart.in_waiting}")
            # Clean up on error
            self.flush_uart_buffer()
            self.reset_partial_message()

    def flush_uart_buffer(self):
        """Clear all pending data from UART buffer"""
        _log(f"Flushing UART buffer - bytes waiting: {self.uart.in_waiting}")
        try:
            while self.uart.in_waiting:
                self.uart.read(1)
            _log("UART buffer flushed")
        except Exception as e:
            _log(f"[ERROR] Failed to flush UART: {str(e)}")

    def cleanup(self):
        """Clean shutdown"""
        _log("Cleaning up MIDI system...")
        self.flush_uart_buffer()
