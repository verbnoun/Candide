import busio
import time
from collections import deque

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

class MPEZone:
    """Represents an MPE Zone (Lower or Upper) with its channel assignments"""
    def __init__(self, is_lower_zone):
        self.is_lower_zone = is_lower_zone
        self.manager_channel = Constants.ZONE_MANAGER if is_lower_zone else Constants.ZONE_END
        self.member_channels = []
        self.active = False
        
        # Controller state tracking
        self.manager_pitch_bend = 8192  # Center position
        self.manager_pressure = 0
        self.manager_timbre = 64  # Center for CC74
        
        # Configuration
        self.pitch_bend_range = Constants.MPE_MASTER_PITCH_BEND_RANGE
        
    def configure(self, member_count):
        """Configure zone with specified number of member channels"""
        self.active = member_count > 0
        if not self.active:
            self.member_channels = []
            return
            
        if self.is_lower_zone:
            # Channels 2-N for lower zone
            self.member_channels = list(range(Constants.ZONE_START, Constants.ZONE_START + member_count))
        else:
            # Channels N-15 for upper zone
            self.member_channels = list(range(Constants.ZONE_END - member_count + 1, Constants.ZONE_END + 1))

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
        
        # Track initial states received before note-on
        self.received_initial_pitch = False
        self.received_initial_pressure = False
        self.received_initial_timbre = False

class ZoneManager:
    """Manages MPE zones"""
    def __init__(self):
        self.lower_zone = MPEZone(is_lower_zone=True)
        self.upper_zone = MPEZone(is_lower_zone=False)
        self.lower_zone.configure(Constants.DEFAULT_ZONE_MEMBER_COUNT)

    def get_zone_for_channel(self, channel):
        """Determine which zone a channel belongs to"""
        if channel == self.lower_zone.manager_channel and self.lower_zone.active:
            return self.lower_zone
        if channel == self.upper_zone.manager_channel and self.upper_zone.active:
            return self.upper_zone
            
        if channel in self.lower_zone.member_channels:
            return self.lower_zone
        if channel in self.upper_zone.member_channels:
            return self.upper_zone
            
        return None

    def reset_zone(self, zone):
        """Reset all state for a zone"""
        zone.active = False
        zone.member_channels = []

class VoiceManager:
    """Manages MPE voice allocation and tracking"""
    def __init__(self):
        self.active_voices = {}  # (channel, note): MPEVoiceState
        self.channel_notes = {}  # channel: set of active notes

    def allocate_channel(self, note, zone):
        """Get next available channel for a new note"""
        if not zone.active:
            return None
            
        # Find least recently used available channel
        for channel in zone.member_channels:
            if channel not in self.channel_notes or not self.channel_notes[channel]:
                return channel
                
        # If all channels are in use, find one with fewest active notes
        min_notes = float('inf')
        best_channel = None
        
        for channel in zone.member_channels:
            note_count = len(self.channel_notes.get(channel, set()))
            if note_count < min_notes:
                min_notes = note_count
                best_channel = channel
                
        return best_channel

    def add_voice(self, channel, note):
        """Add new voice to tracking"""
        voice = MPEVoiceState(channel, note)
        self.active_voices[(channel, note)] = voice
        
        if channel not in self.channel_notes:
            self.channel_notes[channel] = set()
        self.channel_notes[channel].add(note)
        
        return voice

    def release_voice(self, channel, note):
        """Release voice and clean up tracking"""
        voice_key = (channel, note)
        if voice_key in self.active_voices:
            del self.active_voices[voice_key]
            if channel in self.channel_notes:
                self.channel_notes[channel].discard(note)
            return True
        return False

    def get_voice(self, channel, note):
        """Get voice state for channel and note"""
        return self.active_voices.get((channel, note))

class ControllerManager:
    """Manages controller states for channels"""
    def __init__(self):
        self.channel_states = {}  # channel: dict of controller states

    def handle_controller_update(self, channel, controller_type, value, zone_manager):
        """Handle controller state update for a channel"""
        if channel not in self.channel_states:
            self.channel_states[channel] = {}
            
        self.channel_states[channel][controller_type] = value
        
        zone = zone_manager.get_zone_for_channel(channel)
        if not zone:
            return
            
        if channel == zone.manager_channel:
            if controller_type == 'pitch_bend':
                zone.manager_pitch_bend = value
            elif controller_type == 'pressure':
                zone.manager_pressure = value
            elif controller_type == 'timbre':
                zone.manager_timbre = value

class ConfigurationManager:
    """Handles MPE configuration"""
    def __init__(self, zone_manager):
        self.zone_manager = zone_manager

    def handle_mpe_config(self, channel, member_count):
        """Handle MPE Configuration Message"""
        if channel == Constants.ZONE_MANAGER:
            self.zone_manager.lower_zone.configure(member_count)
            if Constants.DEBUG:
                print(f"Configured Lower Zone with {member_count} members")
        elif channel == Constants.ZONE_END:
            self.zone_manager.upper_zone.configure(member_count)
            if Constants.DEBUG:
                print(f"Configured Upper Zone with {member_count} members")

class MidiUart:
    """Handles low-level UART communication and buffering"""
    def __init__(self, midi_tx, midi_rx):
        self.uart = busio.UART(
            tx=midi_tx,
            rx=midi_rx,
            baudrate=Constants.MIDI_BAUDRATE,
            timeout=Constants.UART_TIMEOUT
        )
        self.message_buffer = []
        self.last_status = None
        self.last_status_time = 0
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

class MidiParser:
    """Parses raw MIDI bytes into structured messages"""
    def __init__(self):
        self.message_buffer = []
        self.last_status = None
        self.last_status_time = 0

    def handle_byte(self, byte, current_time):
        """Handle a single MIDI byte and return a complete message if available"""
        if byte is None:
            return None

        # Status byte
        if byte & 0x80:
            if Constants.DEBUG:
                print(f"MIDI Status: 0x{byte:02X}")
            self.last_status = byte
            self.last_status_time = current_time
            self.message_buffer = [byte]
            return None

        # Data byte
        if (self.last_status and 
            current_time - self.last_status_time < Constants.RUNNING_STATUS_TIMEOUT):
            if not self.message_buffer:
                self.message_buffer = [self.last_status]
        
        if Constants.DEBUG:
            print(f"MIDI Data: 0x{byte:02X}")
        self.message_buffer.append(byte)

        # Check if we have a complete message
        if self._is_complete_message():
            message = self._parse_message()
            if Constants.DEBUG and message:
                print(f"Complete MIDI Message: {message}")
            self.message_buffer = []
            return message

        # Check for message timeout
        if current_time - self.last_status_time > Constants.MESSAGE_TIMEOUT:
            self.message_buffer = []

        return None

    def _is_complete_message(self):
        """Check if buffer contains complete MIDI message"""
        if not self.message_buffer:
            return False
            
        status = self.message_buffer[0]
        if status & 0x80 != 0x80:
            return False
            
        message_type = status & 0xF0
        expected_length = 3
        if message_type in (Constants.PROGRAM_CHANGE, Constants.CHANNEL_PRESSURE):
            expected_length = 2
        elif message_type == Constants.SYSTEM_MESSAGE:
            expected_length = 1
            
        return len(self.message_buffer) == expected_length

    def _parse_message(self):
        """Parse complete MIDI message from buffer"""
        if not self._is_complete_message():
            return None

        status = self.message_buffer[0]
        message_type = status & 0xF0
        channel = status & 0x0F

        event = {
            'type': None,
            'channel': channel,
            'data': {}
        }

        if message_type == Constants.NOTE_ON:
            velocity = self.message_buffer[2]
            if velocity > 0:
                event['type'] = 'note_on'
                event['data'] = {
                    'note': self.message_buffer[1],
                    'velocity': velocity
                }
            else:
                event['type'] = 'note_off'
                event['data'] = {
                    'note': self.message_buffer[1],
                    'velocity': 0
                }

        elif message_type == Constants.NOTE_OFF:
            event['type'] = 'note_off'
            event['data'] = {
                'note': self.message_buffer[1],
                'velocity': self.message_buffer[2]
            }

        elif message_type == Constants.CHANNEL_PRESSURE:
            event['type'] = 'pressure'
            event['data'] = {'value': self.message_buffer[1]}

        elif message_type == Constants.PITCH_BEND:
            event['type'] = 'pitch_bend'
            lsb = self.message_buffer[1]
            msb = self.message_buffer[2]
            value = (msb << 7) | lsb
            event['data'] = {
                'lsb': lsb,
                'msb': msb,
                'value': value
            }

        elif message_type == Constants.CONTROL_CHANGE:
            event['type'] = 'cc'
            event['data'] = {
                'number': self.message_buffer[1],
                'value': self.message_buffer[2]
            }

        return event

class MidiLogic:
    """Main MIDI handling class that coordinates components"""
    def __init__(self, uart, text_callback):
        """Initialize MIDI with shared UART"""
        print("Initializing MIDI Logic")
        self.zone_manager = ZoneManager()
        self.voice_manager = VoiceManager()
        self.controller_manager = ControllerManager()
        self.config_manager = ConfigurationManager(self.zone_manager)
        
        # Use provided UART and store callback
        self.uart = uart
        self.text_callback = text_callback
        self.parser = MidiParser()

    def check_for_messages(self):
        """Check for MIDI messages and invoke callbacks"""
        try:
            while True:
                if self.uart.in_waiting:
                    byte = self.uart.read(1)[0]
                else:
                    break

                # Handle MIDI byte
                current_time = time.monotonic()
                event = self.parser.handle_byte(byte, current_time)
                
                if event:
                    # Immediately invoke callback with parsed event
                    if self.text_callback:
                        self.text_callback(event)

                    # Update voice manager state based on the event
                    if event['type'] == 'note_on':
                        zone = self.zone_manager.get_zone_for_channel(event['channel'])
                        if zone:
                            channel = self.voice_manager.allocate_channel(event['data']['note'], zone)
                            if channel is not None:
                                self.voice_manager.add_voice(channel, event['data']['note'])
                    elif event['type'] == 'note_off':
                        self.voice_manager.release_voice(event['channel'], event['data']['note'])
                    elif event['type'] in ('pressure', 'pitch_bend'):
                        self.controller_manager.handle_controller_update(
                            event['channel'], 
                            event['type'], 
                            event['data']['value'], 
                            self.zone_manager
                        )
                    elif event['type'] == 'cc' and event['data']['number'] == Constants.CC_TIMBRE:
                        self.controller_manager.handle_controller_update(
                            event['channel'], 
                            'timbre', 
                            event['data']['value'], 
                            self.zone_manager
                        )

        except Exception as e:
            if str(e):
                print(f"Error reading UART: {str(e)}")

    def handle_config_message(self, message):
        return self.control_processor.handle_config_message(message)

    def reset_controller_defaults(self):
        self.control_processor.reset_to_defaults()

    def update(self, changed_keys, changed_pots, config):
        if not self.message_sender.ready_for_midi:
            return []
            
        midi_events = []
        
        if changed_keys:
            midi_events.extend(self.note_processor.process_key_changes(changed_keys, config))
        
        if changed_pots:
            midi_events.extend(self.control_processor.process_controller_changes(changed_pots))
        
        for event in midi_events:
            self.event_router.handle_event(event)
            
        return midi_events

    def handle_octave_shift(self, direction):
        if not self.message_sender.ready_for_midi:
            return []
        return self.note_processor.handle_octave_shift(direction)
        
    def play_greeting(self):
        """Play greeting chime using MPE"""
        if Constants.DEBUG:
            print("Playing MPE greeting sequence")
            
        base_key_id = -1
        base_pressure = 0.75
        
        greeting_notes = [60, 64, 67, 72]
        velocities = [0.6, 0.7, 0.8, 0.9]
        durations = [0.2, 0.2, 0.2, 0.4]
        
        for idx, (note, velocity, duration) in enumerate(zip(greeting_notes, velocities, durations)):
            key_id = base_key_id - idx
            channel = self.channel_manager.allocate_channel(key_id)
            note_state = self.channel_manager.add_note(key_id, note, channel, int(velocity * 127))
            
            # Send in MPE order: CC74 → Pressure → Pitch Bend → Note On
            self.message_sender.send_message([0xB0 | channel, Constants.CC_TIMBRE, Constants.TIMBRE_CENTER])
            self.message_sender.send_message([0xD0 | channel, int(base_pressure * 127)])
            self.message_sender.send_message([0xE0 | channel, 0x00, 0x40])  # Center pitch bend
            self.message_sender.send_message([0x90 | channel, note, int(velocity * 127)])
            
            time.sleep(duration)
            
            self.message_sender.send_message([0xD0 | channel, 0])  # Zero pressure
            self.message_sender.send_message([0x80 | channel, note, 0])
            self.channel_manager.release_note(key_id)
            
            time.sleep(0.05)

    def cleanup(self):
        """Clean shutdown - no need to cleanup UART as it's shared"""
        if Constants.DEBUG:
            print("\nCleaning up MIDI system...")
