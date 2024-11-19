"""
MIDI Message Processing Module

Handles MIDI communication and message parsing.
Supports full MPE by accepting all MIDI channels (0-15).
Simply validates and passes through MIDI messages with channel information.
"""

import busio
import time
from adafruit_midi import MIDI
from constants import *

class MidiUart:
    """Handles low-level UART communication"""
    def __init__(self, midi_tx, midi_rx):
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
        print("UART initialized")

    def read_byte(self):
        """Read a single byte from UART if available"""
        if self.uart.in_waiting:
            return self.uart.read(1)[0]
        return None

    def write(self, data):
        """Write data to UART"""
        return self.uart.write(data)

    @property
    def in_waiting(self):
        """Number of bytes waiting to be read"""
        return self.uart.in_waiting

    def cleanup(self):
        """Clean shutdown of UART"""
        if self.uart:
            self.uart.deinit()

class MidiLogic:
    """Handles MIDI message parsing and validation"""
    def __init__(self, uart, text_callback):
        print("Initializing MIDI Logic")
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
                            break
                        event = {
                            'type': 'note_on',
                            'channel': channel,
                            'data': {
                                'note': note_byte[0],
                                'velocity': velocity_byte[0]
                            }
                        }

                    elif msg_type == MidiMessageType.NOTE_OFF:
                        note_byte = self.uart.read(1)
                        velocity_byte = self.uart.read(1)
                        if note_byte is None or velocity_byte is None:
                            break
                        event = {
                            'type': 'note_off',
                            'channel': channel,
                            'data': {
                                'note': note_byte[0],
                                'velocity': velocity_byte[0]
                            }
                        }

                    elif msg_type == MidiMessageType.CONTROL_CHANGE:
                        control_byte = self.uart.read(1)
                        value_byte = self.uart.read(1)
                        if control_byte is None or value_byte is None:
                            break
                        event = {
                            'type': 'cc',
                            'channel': channel,
                            'data': {
                                'number': control_byte[0],
                                'value': value_byte[0]
                            }
                        }

                    elif msg_type == MidiMessageType.CHANNEL_PRESSURE:
                        pressure_byte = self.uart.read(1)
                        if pressure_byte is None:
                            break
                        event = {
                            'type': 'pressure',
                            'channel': channel,
                            'data': {
                                'value': pressure_byte[0]
                            }
                        }

                    elif msg_type == MidiMessageType.PITCH_BEND:
                        lsb_byte = self.uart.read(1)
                        msb_byte = self.uart.read(1)
                        if lsb_byte is None or msb_byte is None:
                            break
                        bend_value = (msb_byte[0] << 7) | lsb_byte[0]
                        event = {
                            'type': 'pitch_bend',
                            'channel': channel,
                            'data': {
                                'value': bend_value
                            }
                        }

                    # Pass parsed message to callback if valid
                    if event and self.text_callback:
                        if MIDI_DEBUG:
                            print(f"MIDI Message: {event['type']} - Channel {event['channel']}, Data {event['data']}")
                        self.text_callback(event)

        except Exception as e:
            if str(e):
                print(f"Error reading UART: {str(e)}")

    def cleanup(self):
        """Clean shutdown"""
        if MIDI_DEBUG:
            print("Cleaning up MIDI system...")
