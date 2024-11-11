import busio
import usb_midi
import time
from collections import deque

class Constants:
    DEBUG = True
    SEE_HEARTBEAT = False
    
    # UART/MIDI Settings
    BAUDRATE = 31250
    UART_TIMEOUT = 0.001
    RUNNING_STATUS_TIMEOUT = 0.2
    MESSAGE_TIMEOUT = 0.05
    BUFFER_SIZE = 4096
    
    # MPE Configuration
    LOWER_ZONE_MANAGER = 0      # MIDI channel 1 (zero-based)
    UPPER_ZONE_MANAGER = 15     # MIDI channel 16 (zero-based)
    DEFAULT_ZONE_MEMBER_COUNT = 15
    
    # Default MPE Pitch Bend Ranges
    MANAGER_PITCH_BEND_RANGE = 2    # ±2 semitones default for Manager Channel
    MEMBER_PITCH_BEND_RANGE = 48    # ±48 semitones default for Member Channels
    
    # MIDI Message Types
    NOTE_OFF = 0x80
    NOTE_ON = 0x90
    POLY_PRESSURE = 0xA0
    CONTROL_CHANGE = 0xB0
    PROGRAM_CHANGE = 0xC0
    CHANNEL_PRESSURE = 0xD0
    PITCH_BEND = 0xE0
    SYSTEM_MESSAGE = 0xF0
    
    # MPE Control Change Numbers
    CC_TIMBRE = 74
    
    # RPN Messages
    RPN_PITCH_BEND_RANGE = 0x0000
    RPN_MPE_CONFIGURATION = 0x0006

class MPEZone:
    """Represents an MPE Zone (Lower or Upper) with its channel assignments"""
    def __init__(self, is_lower_zone):
        self.is_lower_zone = is_lower_zone
        self.manager_channel = Constants.LOWER_ZONE_MANAGER if is_lower_zone else Constants.UPPER_ZONE_MANAGER
        self.member_channels = []
        self.active = False
        
        # Controller state tracking
        self.manager_pitch_bend = 8192  # Center position
        self.manager_pressure = 0
        self.manager_timbre = 64  # Center for CC74
        
        # Configuration
        self.pitch_bend_range = Constants.MANAGER_PITCH_BEND_RANGE
        
    def configure(self, member_count):
        """Configure zone with specified number of member channels"""
        self.active = member_count > 0
        if not self.active:
            self.member_channels = []
            return
            
        if self.is_lower_zone:
            # Channels 2-N for lower zone
            self.member_channels = list(range(1, 1 + member_count))
        else:
            # Channels N-15 for upper zone
            self.member_channels = list(range(15 - member_count + 1, 16))

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

class MPEVoiceManager:
    """Manages MPE voice allocation and tracking"""
    def __init__(self):
        # Zone management
        self.lower_zone = MPEZone(is_lower_zone=True)
        self.upper_zone = MPEZone(is_lower_zone=False)
        
        # Default to lower zone only with all available channels
        self.lower_zone.configure(Constants.DEFAULT_ZONE_MEMBER_COUNT)
        
        # Voice tracking
        self.active_voices = {}  # (channel, note): MPEVoiceState
        self.channel_notes = {}  # channel: set of active notes
        
        # Controller state tracking for each member channel
        self.channel_states = {}  # channel: dict of controller states
        
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

    def allocate_channel(self, note, zone=None):
        """Get next available channel for a new note"""
        if zone is None:
            zone = self.lower_zone if self.lower_zone.active else self.upper_zone
            
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
        
        # Initialize with current channel controller states
        if channel in self.channel_states:
            states = self.channel_states[channel]
            voice.pitch_bend = states.get('pitch_bend', 8192)
            voice.pressure = states.get('pressure', 0)
            voice.timbre = states.get('timbre', 64)
        
        # Track the voice
        self.active_voices[(channel, note)] = voice
        
        # Track notes per channel
        if channel not in self.channel_notes:
            self.channel_notes[channel] = set()
        self.channel_notes[channel].add(note)
        
        return voice

    def release_voice(self, channel, note):
        """Release voice and clean up tracking"""
        voice_key = (channel, note)
        if voice_key in self.active_voices:
            # Remove from voice tracking
            del self.active_voices[voice_key]
            
            # Remove from channel note tracking
            if channel in self.channel_notes:
                self.channel_notes[channel].discard(note)
                
            return True
        return False

    def get_voice(self, channel, note):
        """Get voice state for channel and note"""
        return self.active_voices.get((channel, note))

    def update_controller(self, channel, controller_type, value):
        """Update controller state for a channel"""
        if channel not in self.channel_states:
            self.channel_states[channel] = {}
            
        # Update channel state
        self.channel_states[channel][controller_type] = value
        
        # Get the zone for combining manager controls
        zone = self.get_zone_for_channel(channel)
        if not zone:
            return
            
        # If this is a manager channel, update zone manager state
        if channel == zone.manager_channel:
            if controller_type == 'pitch_bend':
                zone.manager_pitch_bend = value
            elif controller_type == 'pressure':
                zone.manager_pressure = value
            elif controller_type == 'timbre':
                zone.manager_timbre = value

    def handle_mpe_config(self, channel, member_count):
        """Handle MPE Configuration Message"""
        if channel == Constants.LOWER_ZONE_MANAGER:
            self.lower_zone.configure(member_count)
            if Constants.DEBUG:
                print(f"Configured Lower Zone with {member_count} members")
        elif channel == Constants.UPPER_ZONE_MANAGER:
            self.upper_zone.configure(member_count)
            if Constants.DEBUG:
                print(f"Configured Upper Zone with {member_count} members")

    def reset_zone(self, zone):
        """Reset all state for a zone"""
        for channel in zone.member_channels:
            if channel in self.channel_states:
                del self.channel_states[channel]
                
        # Clear any voices in the zone
        for (chan, note) in list(self.active_voices.keys()):
            if chan in zone.member_channels:
                self.release_voice(chan, note)

class MidiLogic:
    def __init__(self, midi_tx, midi_rx, text_callback):
        """Initialize MIDI and text communication"""
        print("Initializing MIDI Transport")
        self.text_callback = text_callback
        self.voice_manager = MPEVoiceManager()
        
        # Communication state
        self.uart = busio.UART(
            tx=midi_tx,
            rx=midi_rx,
            baudrate=Constants.BAUDRATE,
            timeout=Constants.UART_TIMEOUT
        )
        self.last_status = None
        self.last_status_time = 0
        self.message_buffer = []
        print("UART initialized")

    def check_for_messages(self):
        """Check for both MIDI and text messages"""
        events = []
        try:
            while self.uart.in_waiting:
                byte = self.uart.read(1)[0]
                
                # Check for text message
                if byte == ord('\n'):
                    if self.message_buffer:
                        try:
                            text = bytes(self.message_buffer).decode('utf-8')
                            self.message_buffer = []
                            if self.text_callback:
                                self.text_callback(text)
                            return True
                        except UnicodeDecodeError:
                            self.message_buffer = []
                    continue

                current_time = time.monotonic()
                
                # Status byte
                if byte & 0x80:
                    if self.message_buffer and not self._is_midi_message(self.message_buffer):
                        try:
                            text = bytes(self.message_buffer).decode('utf-8')
                            if self.text_callback:
                                self.text_callback(text)
                        except UnicodeDecodeError:
                            pass
                    
                    self.last_status = byte
                    self.last_status_time = current_time
                    self.message_buffer = [byte]
                
                # Data byte
                else:
                    if (self.last_status and 
                        current_time - self.last_status_time < Constants.RUNNING_STATUS_TIMEOUT and
                        self._is_midi_message(self.message_buffer)):
                        if not self.message_buffer:
                            self.message_buffer = [self.last_status]
                    
                    self.message_buffer.append(byte)
                
                # Process complete MIDI message
                if self._is_midi_message(self.message_buffer):
                    event = self._process_midi_buffer()
                    if event:
                        events.append(event)
                
                # Check for message timeout
                if current_time - self.last_status_time > Constants.MESSAGE_TIMEOUT:
                    self.message_buffer = []

        except Exception as e:
            if str(e):
                print(f"Error reading UART: {str(e)}")
        
        return events if events else False

    def _is_midi_message(self, buffer):
        """Check if buffer contains complete MIDI message"""
        if not buffer:
            return False
        return buffer[0] & 0x80 == 0x80

    def _process_midi_buffer(self):
        """Process complete MIDI message from buffer"""
        if not self.message_buffer:
            return None

        status = self.message_buffer[0]
        message_type = status & 0xF0
        channel = status & 0x0F

        # Get expected message length
        expected_length = 3
        if message_type in (Constants.PROGRAM_CHANGE, Constants.CHANNEL_PRESSURE):
            expected_length = 2
        elif message_type == Constants.SYSTEM_MESSAGE:
            expected_length = 1

        # Process if complete
        if len(self.message_buffer) == expected_length:
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
                    self.voice_manager.add_voice(channel, self.message_buffer[1])
                else:
                    # Note-on with velocity 0 is note-off
                    event['type'] = 'note_off'
                    event['data'] = {
                        'note': self.message_buffer[1],
                        'velocity': 0
                    }
                    self.voice_manager.release_voice(channel, self.message_buffer[1])

            elif message_type == Constants.NOTE_OFF:
                event['type'] = 'note_off'
                event['data'] = {
                    'note': self.message_buffer[1],
                    'velocity': self.message_buffer[2]
                }
                self.voice_manager.release_voice(channel, self.message_buffer[1])

            elif message_type == Constants.CHANNEL_PRESSURE:
                event['type'] = 'pressure'
                value = self.message_buffer[1]
                event['data'] = {'value': value}
                self.voice_manager.update_controller(channel, 'pressure', value)

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
                self.voice_manager.update_controller(channel, 'pitch_bend', value)

            elif message_type == Constants.CONTROL_CHANGE:
                cc_num = self.message_buffer[1]
                value = self.message_buffer[2]
                event['type'] = 'cc'
                event['data'] = {
                    'number': cc_num,
                    'value': value
                }
                
                # Handle MPE-specific CCs
                if cc_num == Constants.CC_TIMBRE:
                    self.voice_manager.update_controller(channel, 'timbre', value)

            self.message_buffer = []
            return event

        return None

    def cleanup(self):
        """Clean shutdown"""
        if self.uart:
            self.uart.deinit()