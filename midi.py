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
        
        # Track initial states received before note-on
        self.received_initial_pitch = False
        self.received_initial_pressure = False
        self.received_initial_timbre = False
    
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

class MPEZone:
    """Represents an MPE Zone (Lower or Upper) with its channel assignments"""
    def __init__(self, is_lower_zone):
        self.is_lower_zone = is_lower_zone
        self.manager_channel = Constants.ZONE_MANAGER if is_lower_zone else Constants.ZONE_END
        self.member_channels = []
        self.active = False
        self.used_channels = set()
        
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
            self.used_channels.clear()
            if Constants.DEBUG:
                print(f"{'Lower' if self.is_lower_zone else 'Upper'} Zone deactivated")
            return
            
        if self.is_lower_zone:
            # Channels 2-N for lower zone
            self.member_channels = list(range(Constants.ZONE_START, Constants.ZONE_START + member_count))
        else:
            # Channels N-15 for upper zone
            self.member_channels = list(range(Constants.ZONE_END - member_count + 1, Constants.ZONE_END + 1))
        
        if Constants.DEBUG:
            print(f"{'Lower' if self.is_lower_zone else 'Upper'} Zone configured with {member_count} members: {self.member_channels}")

    def allocate_channel(self, note):
        """Allocate a member channel for a new note"""
        if not self.active:
            return None
        
        # Find first available member channel
        for channel in self.member_channels:
            if channel not in self.used_channels:
                self.used_channels.add(channel)
                return channel
        
        # If no free channels, reuse the oldest
        oldest_channel = min(self.member_channels)
        if Constants.DEBUG:
            print(f"Dropping oldest channel {oldest_channel} for new note {note}")
        return oldest_channel

    def release_channel(self, channel):
        """Mark a channel as available"""
        self.used_channels.discard(channel)

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
            
        if Constants.DEBUG and channel not in (0, 15):  # Ignore manager channels
            print(f"No zone found for channel {channel}")
        return None

    def allocate_channel_for_note(self, note):
        """Allocate a channel for a new note, preferring lower zone"""
        channel = self.lower_zone.allocate_channel(note)
        if channel is None:
            channel = self.upper_zone.allocate_channel(note)
        return channel

    def release_channel(self, channel):
        """Release a channel back to its zone"""
        zone = self.get_zone_for_channel(channel)
        if zone:
            zone.release_channel(channel)

class VoiceManager:
    """Manages MPE voice allocation and tracking"""
    def __init__(self):
        self.active_voices = {}  # (channel, note): MPEVoiceState
        self.channel_notes = {}  # channel: set of active notes
        self.channel_history = {}  # channel: last_use_time
        self.note_to_channel = {}  # note: channel mapping for MPE

    def allocate_channel(self, note, zone):
        """Get next available channel for a new note"""
        if not zone.active:
            if Constants.DEBUG:
                print(f"Cannot allocate channel: Zone not active")
            return None
            
        current_time = time.monotonic()
        
        # First try to find a completely free channel
        for channel in zone.member_channels:
            if channel not in self.channel_notes or not self.channel_notes[channel]:
                self.channel_history[channel] = current_time
                if Constants.DEBUG:
                    print(f"Allocated free channel {channel} for note {note}")
                return channel
        
        # Then try to find a channel with notes in release phase
        for channel in zone.member_channels:
            if channel in self.channel_notes:
                all_released = True
                for note_key in list(self.active_voices.keys()):
                    if note_key[0] == channel:
                        voice = self.active_voices[note_key]
                        if voice.active:
                            all_released = False
                            break
                if all_released:
                    if Constants.DEBUG:
                        print(f"Reclaiming channel {channel} with released notes for note {note}")
                    self.channel_history[channel] = current_time
                    return channel
        
        # If all channels are in use, find the oldest one
        oldest_time = current_time
        oldest_channel = None
        
        for channel in zone.member_channels:
            channel_time = self.channel_history.get(channel, 0)
            if channel_time < oldest_time:
                oldest_time = channel_time
                oldest_channel = channel
        
        if oldest_channel is not None:
            if Constants.DEBUG:
                print(f"Dropping oldest channel {oldest_channel} for new note {note}")
            self.channel_history[oldest_channel] = current_time
            return oldest_channel
                
        return None

    def add_voice(self, channel, note):
        """Add new voice to tracking"""
        voice = MPEVoiceState(channel, note)
        self.active_voices[(channel, note)] = voice
        
        if channel not in self.channel_notes:
            self.channel_notes[channel] = set()
        self.channel_notes[channel].add(note)
        
        # Store note to channel mapping for MPE
        self.note_to_channel[note] = channel
        
        if Constants.DEBUG:
            print(f"Added voice: Channel {channel}, Note {note}")
        
        return voice

    def release_voice(self, channel, note):
        """Release voice and clean up tracking"""
        # If the note came in on channel 0, look up its actual MPE channel
        if channel == Constants.ZONE_MANAGER and note in self.note_to_channel:
            channel = self.note_to_channel[note]
        
        voice_key = (channel, note)
        if voice_key in self.active_voices:
            voice = self.active_voices[voice_key]
            voice.release()  # Mark as released and record timing
            if channel in self.channel_notes:
                self.channel_notes[channel].discard(note)
            
            # Clean up note to channel mapping
            if note in self.note_to_channel:
                del self.note_to_channel[note]
            
            if Constants.DEBUG:
                print(f"Released voice: Channel {channel}, Note {note}")
            
            return True
        
        if Constants.DEBUG:
            print(f"Failed to release voice: Channel {channel}, Note {note} not found")
        
        return False

    def get_voice(self, channel, note):
        """Get voice state for channel and note"""
        # If the note came in on channel 0, look up its actual MPE channel
        if channel == Constants.ZONE_MANAGER and note in self.note_to_channel:
            channel = self.note_to_channel[note]
        return self.active_voices.get((channel, note))

    def get_channel_for_note(self, note):
        """Get the MPE channel assigned to a note"""
        return self.note_to_channel.get(note)

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
        self.channel_states = {}  # channel: dict of controller states
        self.cached_cc_states = {}  # channel: dict of last valid CC values

    def handle_controller_update(self, channel, controller_type, value, zone_manager, voice_manager):
        """Handle controller state update for a channel"""
        current_time = time.monotonic()
        
        # Always update channel state cache
        if channel not in self.cached_cc_states:
            self.cached_cc_states[channel] = {}
        self.cached_cc_states[channel][controller_type] = value
        
        # For channel 0 messages, we need to find the active notes and their channels
        if channel == Constants.ZONE_MANAGER:
            # Update all active voices
            for voice_key in list(voice_manager.active_voices.keys()):
                voice = voice_manager.active_voices[voice_key]
                if voice.can_process_cc():
                    voice.last_cc_time = current_time
                    # Update the controller value for this voice
                    if controller_type == 'pressure':
                        voice.pressure = value
                    elif controller_type == 'pitch_bend':
                        voice.pitch_bend = value
                    elif controller_type == 'timbre':
                        voice.timbre = value
            return
        
        # Check if we should process this CC message
        can_process = False
        for voice_key in voice_manager.active_voices:
            if voice_key[0] == channel:
                voice = voice_manager.active_voices[voice_key]
                if voice.can_process_cc():
                    can_process = True
                    voice.last_cc_time = current_time
                    break
        
        if not can_process:
            if Constants.DEBUG:
                print(f"Dropping {controller_type} message for channel {channel} - no active voice")
            return
            
        # Process the controller update
        if channel not in self.channel_states:
            self.channel_states[channel] = {}
            
        self.channel_states[channel][controller_type] = value
        
        if Constants.DEBUG:
            print(f"Controller Update: Channel {channel}, Type {controller_type}, Value {value}")
        
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
    
    def get_cached_state(self, channel, controller_type):
        """Get last known good value for a controller"""
        return self.cached_cc_states.get(channel, {}).get(controller_type)

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
        self.midi = MIDI(midi_in=self.uart, in_channel=0)
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
        self.zone_manager = ZoneManager()
        self.voice_manager = VoiceManager()
        self.controller_manager = ControllerManager()
        self.config_manager = ConfigurationManager(self.zone_manager)
        
        # Use provided UART and store callback
        self.uart = uart
        self.text_callback = text_callback
        self.midi = MIDI(midi_in=self.uart, in_channel=0)

    def check_for_messages(self):
        """Check for MIDI messages and invoke callbacks"""
        try:
            while True:
                msg = self.midi.receive()
                if not msg:
                    break

                # Handle MIDI message
                current_time = time.monotonic()
                event = self._parse_message(msg, current_time)
                
                if event:
                    # Immediately invoke callback with parsed event
                    if self.text_callback:
                        self.text_callback(event)

                    # Clean up any fully released voices
                    self.voice_manager.cleanup_released_voices()

                    # Update voice manager state based on the event
                    if event['type'] == 'note_on':
                        # For channel 0 (manager channel), allocate a member channel
                        if event['channel'] == Constants.ZONE_MANAGER:
                            channel = self.zone_manager.allocate_channel_for_note(event['data']['note'])
                            if channel is not None:
                                voice = self.voice_manager.add_voice(channel, event['data']['note'])
                                
                                # Apply any cached CC states
                                cached_states = self.controller_manager.cached_cc_states.get(Constants.ZONE_MANAGER, {})
                                if 'pitch_bend' in cached_states:
                                    voice.pitch_bend = cached_states['pitch_bend']
                                if 'pressure' in cached_states:
                                    voice.pressure = cached_states['pressure']
                                if 'timbre' in cached_states:
                                    voice.timbre = cached_states['timbre']
                        else:
                            # Direct member channel note
                            voice = self.voice_manager.add_voice(event['channel'], event['data']['note'])
                    elif event['type'] == 'note_off':
                        # Release note using the original channel (voice manager will handle MPE lookup)
                        self.voice_manager.release_voice(event['channel'], event['data']['note'])
                    elif event['type'] in ('pressure', 'pitch_bend', 'cc'):
                        # Handle controller messages
                        if event['type'] == 'cc' and event['data']['number'] == Constants.CC_TIMBRE:
                            self.controller_manager.handle_controller_update(
                                event['channel'],
                                'timbre',
                                event['data']['value'],
                                self.zone_manager,
                                self.voice_manager
                            )
                        else:
                            self.controller_manager.handle_controller_update(
                                event['channel'],
                                event['type'],
                                event['data']['value'],
                                self.zone_manager,
                                self.voice_manager
                            )

        except Exception as e:
            if str(e):
                print(f"Error reading UART: {str(e)}")

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
