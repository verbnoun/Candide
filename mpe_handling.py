import time
from fixed_point_math import FixedPoint
from synth_constants import Constants, ModSource, ModTarget

class MPEConfig:
    """Manages MPE zones and channel assignments"""
    def __init__(self):
        self.zone_manager_channel = 0  # MIDI channel 1
        self.member_channels = range(1, 16)  # MIDI channels 2-16
        self.pitch_bend_range_member = Constants.DEFAULT_MPE_PITCH_BEND_RANGE
        self.pitch_bend_range_manager = 2  # Standard for manager channel
        self.pressure_sensitivity = Constants.DEFAULT_PRESSURE_SENSITIVITY

class MPEVoice:
    """Tracks state of an active MPE voice and its parameters"""
    def __init__(self, channel, note, velocity):
        self.channel = channel
        self.note = note
        self.active = True
        self.start_time = time.monotonic()
        self.last_update = self.start_time
        
        # Initial state capture
        self.initial_state = {
            'pressure': 0,
            'timbre': 64,  # CC74 default center
            'bend': 0,
            'velocity': FixedPoint.normalize_midi_value(velocity)
        }
        
        # Current state
        self.pressure = FixedPoint.ZERO
        self.pitch_bend = FixedPoint.ZERO
        self.timbre = FixedPoint.ZERO
        
        # Track last values to detect significant changes
        self.last_values = {
            'pressure': self.pressure,
            'bend': self.pitch_bend,
            'timbre': self.timbre
        }
        
        self.synth_note = None

    def update_initial_state(self, control_type, value):
        """Update initial state before note starts"""
        if not self.synth_note:  # Only update if note hasn't started
            self.initial_state[control_type] = value
            return True
        return False

class MPEVoiceManager:
    """Manages voice allocation and parameter tracking"""
    def __init__(self):
        self.active_voices = {}  # (channel, note): MPEVoice
        self.channel_voices = {}  # channel: set of active notes
        self.pending_controls = {}  # (channel, key): {control_values}
        
    def store_pending_control(self, channel, key, control_type, value):
        """Store control message that arrives before note-on"""
        pending_key = (channel, key) if key is not None else channel
        if pending_key not in self.pending_controls:
            self.pending_controls[pending_key] = {}
        self.pending_controls[pending_key][control_type] = value
        if Constants.DEBUG:
            print("[MPE] Stored pending {0}: {1} for channel {2}, key {3}".format(
                control_type, value, channel, key))
            
    def get_pending_controls(self, channel, key):
        """Get and clear pending controls for a note"""
        # Try exact match first
        pending_key = (channel, key)
        controls = self.pending_controls.get(pending_key, {})
        
        # Also check channel-only controls
        channel_controls = self.pending_controls.get(channel, {})
        controls.update(channel_controls)  # Channel controls can override note controls
        
        # Clear used controls
        if pending_key in self.pending_controls:
            del self.pending_controls[pending_key]
        if channel in self.pending_controls:
            del self.pending_controls[channel]
            
        return controls
        
    def allocate_voice(self, channel, note, velocity):
        """Allocate new voice with initial control values"""
        if (channel, note) in self.active_voices:
            voice = self.active_voices[(channel, note)]
            voice.initial_state['velocity'] = FixedPoint.normalize_midi_value(velocity)
            return voice
            
        # Create new voice
        voice = MPEVoice(channel, note, velocity)
        
        # Apply any pending control values
        pending = self.get_pending_controls(channel, note)
        for control_type, value in pending.items():
            voice.update_initial_state(control_type, value)
        
        self.active_voices[(channel, note)] = voice
        
        if channel not in self.channel_voices:
            self.channel_voices[channel] = set()
        self.channel_voices[channel].add(note)
        
        if Constants.DEBUG:
            print("[MPE] Voice allocated with initial state: {}".format(voice.initial_state))
        
        return voice

    def get_voice(self, channel, note):
        """Get voice if it exists"""
        return self.active_voices.get((channel, note))

    def release_voice(self, channel, note):
        """Handle note release and cleanup"""
        voice_key = (channel, note)
        if voice_key in self.active_voices:
            voice = self.active_voices[voice_key]
            voice.active = False
            
            if channel in self.channel_voices:
                self.channel_voices[channel].discard(note)
                if not self.channel_voices[channel]:
                    del self.channel_voices[channel]
                    
            return voice
        return None

class MPEParameterProcessor:
    """Processes and normalizes MPE control messages"""
    def __init__(self, voice_manager, mod_matrix):
        self.voice_manager = voice_manager
        self.mod_matrix = mod_matrix
        self.config = MPEConfig()
        
    def handle_pressure(self, channel, value, key=None):
        """Process pressure message"""
        # Get voice if it exists
        voice = self.voice_manager.get_voice(channel, key) if key is not None else None
        
        if voice is None:
            # Store as pending control
            self.voice_manager.store_pending_control(channel, key, 'pressure', value)
            return True
            
        # Only process if voice is active
        if voice.active:
            normalized = FixedPoint.normalize_midi_value(value)
            if self._is_significant_change(voice.last_values['pressure'], normalized):
                voice.pressure = normalized
                voice.last_values['pressure'] = normalized
                self.mod_matrix.set_source_value(ModSource.PRESSURE, voice.channel, 
                    FixedPoint.to_float(normalized))
                return True
        return False
        
    def handle_pitch_bend(self, channel, value, key=None):
        """Process pitch bend message"""
        voice = self.voice_manager.get_voice(channel, key) if key is not None else None
        
        if voice is None:
            self.voice_manager.store_pending_control(channel, key, 'bend', value)
            return True
            
        if voice.active:
            normalized = FixedPoint.normalize_pitch_bend(value)
            if self._is_significant_change(voice.last_values['bend'], normalized):
                voice.pitch_bend = normalized
                voice.last_values['bend'] = normalized
                self.mod_matrix.set_source_value(ModSource.PITCH_BEND, voice.channel,
                    FixedPoint.to_float(normalized))
                return True
        return False
        
    def handle_timbre(self, channel, value, key=None):
        """Process timbre (CC74) message"""
        voice = self.voice_manager.get_voice(channel, key) if key is not None else None
        
        if voice is None:
            self.voice_manager.store_pending_control(channel, key, 'timbre', value)
            return True
            
        if voice.active:
            normalized = FixedPoint.normalize_midi_value(value)
            if self._is_significant_change(voice.last_values['timbre'], normalized):
                voice.timbre = normalized
                voice.last_values['timbre'] = normalized
                self.mod_matrix.set_source_value(ModSource.TIMBRE, voice.channel,
                    FixedPoint.to_float(normalized))
                return True
        return False
        
    def _is_significant_change(self, old_value, new_value):
        """Determine if parameter change is significant enough to process"""
        if old_value == new_value:  # Quick equality check first
            return False
        return abs(FixedPoint.to_float(new_value - old_value)) > 0.001

class MPEMessageRouter:
    """Routes MPE messages to appropriate handlers"""
    def __init__(self, voice_manager, parameter_processor):
        self.voice_manager = voice_manager
        self.parameter_processor = parameter_processor
        
    def route_message(self, message):
        """Route incoming MPE message to appropriate handler"""
        if not message or 'type' not in message:
            return
            
        msg_type = message['type']
        channel = message['channel']
        data = message.get('data', {})
        
        # Extract key for note-specific messages
        key = data.get('note') if msg_type in ('note_on', 'note_off') else None
        
        # Handle control messages
        if msg_type == 'pressure':
            self.parameter_processor.handle_pressure(channel, data.get('value', 0), key)
        elif msg_type == 'pitch_bend':
            self.parameter_processor.handle_pitch_bend(channel, data.get('value', 8192), key)
        elif msg_type == 'cc' and data.get('number') == 74:  # Timbre
            self.parameter_processor.handle_timbre(channel, data.get('value', 64), key)
            
        # Note events
        elif msg_type == 'note_on':
            note = data.get('note')
            velocity = data.get('velocity', 127)
            voice = self.voice_manager.allocate_voice(channel, note, velocity)
            
            # Set initial modulation values
            self.parameter_processor.mod_matrix.set_source_value(
                ModSource.NOTE, 
                channel, 
                FixedPoint.to_float(FixedPoint.midi_note_to_fixed(note))
            )
            
            self.parameter_processor.mod_matrix.set_source_value(
                ModSource.VELOCITY,
                channel,
                FixedPoint.to_float(voice.initial_state['velocity'])
            )
            
            return {'type': 'voice_allocated', 'voice': voice}
            
        elif msg_type == 'note_off':
            note = data.get('note')
            voice = self.voice_manager.release_voice(channel, note)
            return {'type': 'voice_released', 'voice': voice}