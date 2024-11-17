import busio
import time
from adafruit_midi import MIDI
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff
from adafruit_midi.control_change import ControlChange
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.channel_pressure import ChannelPressure

class Constants:
    DEBUG = False
    
    # UART/MIDI Settings
    MIDI_BAUDRATE = 31250  # Aligned with Bartleby
    UART_TIMEOUT = 0.001
    RUNNING_STATUS_TIMEOUT = 0.2
    MESSAGE_TIMEOUT = 0.05
    BUFFER_SIZE = 4096
    
    # MPE Configuration
    ZONE_MANAGER = 0       # MIDI channel 1 (zero-based) - aligned with Bartleby
    ZONE_START = 1        # First member channel
    ZONE_END = 15        # Last member channel
    DEFAULT_ZONE_MEMBER_COUNT = 15
    
    # Default MPE Pitch Bend Ranges - aligned with Bartleby
    MPE_MASTER_PITCH_BEND_RANGE = 2    # ±2 semitones default for Manager Channel
    MPE_MEMBER_PITCH_BEND_RANGE = 48   # ±48 semitones default for Member Channels
    
    # MIDI Message Types
    NOTE_OFF = 0x80
    NOTE_ON = 0x90
    POLY_PRESSURE = 0xA0
    CONTROL_CHANGE = 0xB0
    PROGRAM_CHANGE = 0xC0
    CHANNEL_PRESSURE = 0xD0
    PITCH_BEND = 0xE0
    SYSTEM_MESSAGE = 0xF0
    
    # MPE Control Change Numbers - aligned with Bartleby
    CC_TIMBRE = 74
    
    # RPN Messages - aligned with Bartleby
    RPN_MSB = 0
    RPN_LSB_MPE = 6
    RPN_LSB_PITCH = 0
    
    # Expression Message Timing
    CC_RELEASE_WINDOW = 0.05  # 50ms window for CC messages after note-off

class MPEVoiceState:
    """Tracks the state of an active MPE voice with all its control values"""
    def __init__(self, channel, note):
        self.channel = channel
        self.note = note
        self.active = True
        
        # Control states - initialize to defaults
        self.pitch_bend = 8192  # Center position
        self.pressure = 0
        self.timbre = 64  # CC74 center position
        
        # Timing
        self.note_on_time = time.monotonic()
        self.last_cc_time = self.note_on_time  # Track last CC message time
        self.release_time = None  # Set when note is released
        
    def release(self):
        """Mark voice as released and record timing"""
        self.active = False
        self.release_time = time.monotonic()
        if Constants.DEBUG:
            print(f"Voice released: Channel {self.channel}, Note {self.note}")
    
    def can_process_cc(self):
        """Check if CC messages should still be processed"""
        if self.active:
            return True
        if self.release_time is None:
            return False
        # Allow CC processing within release window
        return (time.monotonic() - self.release_time) <= Constants.CC_RELEASE_WINDOW

class VoiceManager:
    """Manages MPE voice tracking"""
    def __init__(self):
        self.active_voices = {}  # (channel, note): MPEVoiceState
        self.channel_notes = {}  # channel: set of active notes

    def add_voice(self, channel, note):
        """Add new voice to tracking"""
        voice = MPEVoiceState(channel, note)
        self.active_voices[(channel, note)] = voice
        
        if channel not in self.channel_notes:
            self.channel_notes[channel] = set()
        self.channel_notes[channel].add(note)
        
        if Constants.DEBUG:
            print(f"Added voice: Channel {channel}, Note {note}")
        
        return voice

    def release_voice(self, channel, note):
        """Release voice and clean up tracking"""
        voice_key = (channel, note)
        if voice_key in self.active_voices:
            voice = self.active_voices[voice_key]
            voice.release()  # Mark as released and record timing
            if channel in self.channel_notes:
                self.channel_notes[channel].discard(note)
            
            if Constants.DEBUG:
                print(f"Released voice: Channel {channel}, Note {note}")
            
            return True
        
        if Constants.DEBUG:
            print(f"Failed to release voice: Channel {channel}, Note {note} not found")
        
        return False

    def get_voice(self, channel, note):
        """Get voice state for channel and note"""
        return self.active_voices.get((channel, note))

    def cleanup_released_voices(self):
        """Remove voices that are past their CC release window"""
        current_time = time.monotonic()
        for voice_key in list(self.active_voices.keys()):
            voice = self.active_voices[voice_key]
            if (not voice.active and voice.release_time is not None and 
                (current_time - voice.release_time) > Constants.CC_RELEASE_WINDOW):
                del self.active_voices[voice_key]
                if Constants.DEBUG:
                    print(f"Cleaned up released voice: Channel {voice.channel}, Note {voice.note}")

class ControllerManager:
    """Manages controller states for channels"""
    def __init__(self):
        self.cached_cc_states = {}  # channel: dict of last valid CC values

    def handle_controller_update(self, channel, controller_type, value, voice_manager):
        """Handle controller state update for a channel"""
        current_time = time.monotonic()
        
        # Update channel state cache
        if channel not in self.cached_cc_states:
            self.cached_cc_states[channel] = {}
        self.cached_cc_states[channel][controller_type] = value
        
        # Update any matching voices
        for voice_key in list(voice_manager.active_voices.keys()):
            voice = voice_manager.active_voices[voice_key]
            if voice.channel == channel and voice.can_process_cc():
                voice.last_cc_time = current_time
                # Update the controller value for this voice
                if controller_type == 'pressure':
                    voice.pressure = value
                elif controller_type == 'pitch_bend':
                    voice.pitch_bend = value
                elif controller_type == 'timbre':
                    voice.timbre = value
    
    def get_cached_state(self, channel, controller_type):
        """Get last known good value for a controller"""
        return self.cached_cc_states.get(channel, {}).get(controller_type)

class MidiUart:
    """Handles low-level UART communication and buffering"""
    def __init__(self, midi_tx, midi_rx):
        self.uart = busio.UART(
            tx=midi_tx,
            rx=midi_rx,
            baudrate=Constants.MIDI_BAUDRATE,
            timeout=Constants.UART_TIMEOUT
        )
        self.midi = MIDI(
            midi_in=self.uart,
            in_channel=tuple(range(Constants.ZONE_MANAGER, Constants.ZONE_END + 1))
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
    """Main MIDI handling class that coordinates components"""
    def __init__(self, uart, text_callback):
        """Initialize MIDI with shared UART"""
        print("Initializing MIDI Logic")
        self.voice_manager = VoiceManager()
        self.controller_manager = ControllerManager()
        
        # Use provided UART and store callback
        self.uart = uart
        self.text_callback = text_callback
        self.midi = MIDI(midi_in=self.uart, in_channel=0)

    def check_for_messages(self):
        """Check for MIDI messages using raw byte handling"""
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
                    current_time = time.monotonic()
                    event = None

                    # Handle different message types based on MIDI spec
                    if msg_type == Constants.NOTE_ON:
                        note_byte = self.uart.read(1)
                        velocity_byte = self.uart.read(1)
                        if note_byte is None or velocity_byte is None:
                            break
                        note = note_byte[0]
                        velocity = velocity_byte[0]
                        if Constants.DEBUG:
                            print(f"Raw MIDI Message: NoteOn - Channel {channel}, Note {note}, Velocity {velocity}")
                        event = {
                            'type': 'note_on',
                            'channel': channel,
                            'data': {'note': note, 'velocity': velocity}
                        }

                    elif msg_type == Constants.NOTE_OFF:
                        note_byte = self.uart.read(1)
                        velocity_byte = self.uart.read(1)
                        if note_byte is None or velocity_byte is None:
                            break
                        note = note_byte[0]
                        velocity = velocity_byte[0]
                        if Constants.DEBUG:
                            print(f"Raw MIDI Message: NoteOff - Channel {channel}, Note {note}, Velocity {velocity}")
                        event = {
                            'type': 'note_off',
                            'channel': channel,
                            'data': {'note': note, 'velocity': velocity}
                        }

                    elif msg_type == Constants.CONTROL_CHANGE:
                        control_byte = self.uart.read(1)
                        value_byte = self.uart.read(1)
                        if control_byte is None or value_byte is None:
                            break
                        control = control_byte[0]
                        value = value_byte[0]
                        if Constants.DEBUG:
                            print(f"Raw MIDI Message: ControlChange - Channel {channel}, Control {control}, Value {value}")
                        event = {
                            'type': 'cc',
                            'channel': channel,
                            'data': {'number': control, 'value': value}
                        }

                    elif msg_type == Constants.CHANNEL_PRESSURE:
                        pressure_byte = self.uart.read(1)
                        if pressure_byte is None:
                            break
                        pressure = pressure_byte[0]
                        if Constants.DEBUG:
                            print(f"Raw MIDI Message: ChannelPressure - Channel {channel}, Pressure {pressure}")
                        event = {
                            'type': 'pressure',
                            'channel': channel,
                            'data': {'value': pressure}
                        }

                    elif msg_type == Constants.PITCH_BEND:
                        lsb_byte = self.uart.read(1)
                        msb_byte = self.uart.read(1)
                        if lsb_byte is None or msb_byte is None:
                            break
                        lsb = lsb_byte[0]
                        msb = msb_byte[0]
                        bend_value = (msb << 7) | lsb
                        if Constants.DEBUG:
                            print(f"Raw MIDI Message: PitchBend - Channel {channel}, Value {bend_value}")
                        event = {
                            'type': 'pitch_bend',
                            'channel': channel,
                            'data': {'value': bend_value}
                        }

                    # Process the event if we have one
                    if event:
                        # Invoke callback
                        if self.text_callback:
                            self.text_callback(event)

                        # Clean up released voices
                        self.voice_manager.cleanup_released_voices()

                        # Update voice manager state
                        if event['type'] == 'note_on':
                            self.voice_manager.add_voice(event['channel'], event['data']['note'])
                        elif event['type'] == 'note_off':
                            self.voice_manager.release_voice(event['channel'], event['data']['note'])
                        elif event['type'] in ('pressure', 'pitch_bend', 'cc'):
                            if event['type'] == 'cc' and event['data']['number'] == Constants.CC_TIMBRE:
                                self.controller_manager.handle_controller_update(
                                    event['channel'],
                                    'timbre',
                                    event['data']['value'],
                                    self.voice_manager
                                )
                            else:
                                self.controller_manager.handle_controller_update(
                                    event['channel'],
                                    event['type'],
                                    event['data']['value'],
                                    self.voice_manager
                                )

        except Exception as e:
            if str(e):
                print(f"Error reading UART: {str(e)}")

    def _log_raw_message_info(self, msg):
        """Log raw message information before processing"""
        try:
            # Attempt to log message details
            if isinstance(msg, NoteOn):
                print(f"Raw MIDI Message: NoteOn - Channel {msg.channel}, Note {msg.note}, Velocity {msg.velocity}")
            elif isinstance(msg, NoteOff):
                print(f"Raw MIDI Message: NoteOff - Channel {msg.channel}, Note {msg.note}, Velocity {msg.velocity}")
            elif isinstance(msg, ControlChange):
                print(f"Raw MIDI Message: ControlChange - Channel {msg.channel}, Control {msg.control}, Value {msg.value}")
            elif isinstance(msg, PitchBend):
                print(f"Raw MIDI Message: PitchBend - Channel {msg.channel}, Value {msg.pitch_bend}")
            elif isinstance(msg, ChannelPressure):
                print(f"Raw MIDI Message: ChannelPressure - Channel {msg.channel}, Pressure {msg.pressure}")
            else:
                print(f"Raw MIDI Message: Unknown Type - Channel {msg.channel}")
        except Exception as e:
            print(f"Error logging raw message: {str(e)}")

    def _parse_message(self, msg, current_time):
        """Parse MIDI message into event"""
        event = {
            'type': None,
            'channel': msg.channel,
            'data': {}
        }

        if isinstance(msg, NoteOn):
            event['type'] = 'note_on'
            event['data'] = {
                'note': msg.note,
                'velocity': msg.velocity
            }
            if Constants.DEBUG:
                print(f"Note On: Channel {msg.channel}, Note {msg.note}, Velocity {msg.velocity}")
        elif isinstance(msg, NoteOff):
            event['type'] = 'note_off'
            event['data'] = {
                'note': msg.note,
                'velocity': msg.velocity
            }
            if Constants.DEBUG:
                print(f"Note Off: Channel {msg.channel}, Note {msg.note}, Velocity {msg.velocity}")
        elif isinstance(msg, ChannelPressure):
            event['type'] = 'pressure'
            event['data'] = {'value': msg.pressure}
            if Constants.DEBUG:
                print(f"Channel Pressure: Channel {msg.channel}, Pressure {msg.pressure}")
        elif isinstance(msg, PitchBend):
            event['type'] = 'pitch_bend'
            event['data'] = {
                'value': msg.pitch_bend
            }
            if Constants.DEBUG:
                print(f"Pitch Bend: Channel {msg.channel}, Value {msg.pitch_bend}")
        elif isinstance(msg, ControlChange):
            event['type'] = 'cc'
            event['data'] = {
                'number': msg.control,
                'value': msg.value
            }
            if Constants.DEBUG:
                print(f"Control Change: Channel {msg.channel}, Control {msg.control}, Value {msg.value}")

        return event

    def cleanup(self):
        """Clean shutdown - no need to cleanup UART as it's shared"""
        if Constants.DEBUG:
            print("\nCleaning up MIDI system...")
