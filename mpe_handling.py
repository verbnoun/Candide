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
    """Tracks state of an active MPE voice and its parameters
    
    MPE Signal Flow:
    1. Each voice represents a note with its own channel for independent control
    2. Core MPE parameters (pressure, pitch bend, timbre) are tracked per-voice
    3. These parameters feed into the modulation matrix to affect synthesis
    """
    def __init__(self, channel, note, velocity):
        self.channel = channel
        self.note = note
        self.active = True
        self.start_time = time.monotonic()
        self.last_update = self.start_time
        
        # Core MPE parameters that feed into synthesis engine
        self.velocity = FixedPoint.normalize_midi_value(velocity)  # Initial note velocity -> amplitude
        self.pressure = FixedPoint.ZERO  # Channel pressure -> typically mapped to amplitude/filter
        self.pitch_bend = FixedPoint.ZERO  # Per-note pitch bend -> frequency modulation
        self.timbre = FixedPoint.ZERO  # CC74 timbre control -> typically mapped to filter cutoff
        
        # Parameter history for significance tracking
        self.last_pressure = self.pressure
        self.last_pitch_bend = self.pitch_bend
        self.last_timbre = self.timbre
        
        # Reference to the actual synthio note being controlled
        self.synth_note = None

class MPEVoiceManager:
    """Manages voice allocation and parameter tracking
    
    MPE Signal Flow:
    1. Allocates/tracks voices for incoming MPE messages
    2. Each voice gets its own channel for independent parameter control
    3. Maintains mapping between MIDI channels and active voices
    """
    def __init__(self):
        self.active_voices = {}  # (channel, note): MPEVoice
        self.channel_voices = {}  # channel: set of active notes
        self.voice_history = {}  # For parameter change tracking
        
    def allocate_voice(self, channel, note, velocity):
        """Allocate new voice or recycle existing one"""
        if (channel, note) in self.active_voices:
            voice = self.active_voices[(channel, note)]
            voice.velocity = FixedPoint.normalize_midi_value(velocity)
            return voice
            
        voice = MPEVoice(channel, note, velocity)
        self.active_voices[(channel, note)] = voice
        
        if channel not in self.channel_voices:
            self.channel_voices[channel] = set()
        self.channel_voices[channel].add(note)
        
        return voice
        
    def release_voice(self, channel, note):
        """Handle note release and parameter cleanup"""
        if (channel, note) not in self.active_voices:
            return None
            
        voice = self.active_voices[(channel, note)]
        voice.active = False
        
        if channel in self.channel_voices:
            self.channel_voices[channel].discard(note)
            if not self.channel_voices[channel]:
                del self.channel_voices[channel]
                
        return voice

    def get_voice(self, channel, note):
        """Get voice if it exists"""
        return self.active_voices.get((channel, note))

class MPEParameterProcessor:
    """Processes and normalizes MPE control messages
    
    MPE Signal Flow:
    1. Receives raw MPE messages (pressure, pitch bend, timbre)
    2. Normalizes values and applies sensitivity/scaling
    3. Updates voice parameters and feeds into modulation matrix
    4. Modulation matrix then routes these to synthesis parameters
    """
    def __init__(self, voice_manager, mod_matrix):
        self.voice_manager = voice_manager
        self.mod_matrix = mod_matrix
        self.config = MPEConfig()
        
    def handle_pressure(self, channel, value, voice=None):
        """Process pressure message -> routes to modulation matrix"""
        normalized = FixedPoint.normalize_midi_value(value)
        if voice and voice.active:
            if self._is_significant_change(voice.pressure, normalized):
                voice.pressure = normalized
                self.mod_matrix.set_source_value(ModSource.PRESSURE, voice.channel, 
                    FixedPoint.to_float(normalized))
                return True
        return False
        
    def handle_pitch_bend(self, channel, value, voice=None):
        """Process pitch bend message -> routes to modulation matrix"""
        normalized = FixedPoint.normalize_pitch_bend(value)
        if voice and voice.active:
            if self._is_significant_change(voice.pitch_bend, normalized):
                voice.pitch_bend = normalized
                self.mod_matrix.set_source_value(ModSource.PITCH_BEND, voice.channel,
                    FixedPoint.to_float(normalized))
                return True
        return False
        
    def handle_timbre(self, channel, value, voice=None):
        """Process timbre (CC74) message -> routes to modulation matrix"""
        normalized = FixedPoint.normalize_midi_value(value)
        if voice and voice.active:
            if self._is_significant_change(voice.timbre, normalized):
                voice.timbre = normalized
                self.mod_matrix.set_source_value(ModSource.TIMBRE, voice.channel,
                    FixedPoint.to_float(normalized))
                return True
        return False
        
    def _is_significant_change(self, old_value, new_value):
        """Determine if parameter change is significant enough to process"""
        return abs(FixedPoint.to_float(new_value - old_value)) > 0.001

class MPEMessageRouter:
    """Routes MPE messages to appropriate handlers
    
    MPE Signal Flow:
    1. Entry point for all incoming MPE MIDI messages
    2. Routes note on/off to voice manager for allocation/release
    3. Routes continuous controllers to parameter processor
    4. Parameter processor updates modulation matrix
    5. Modulation matrix affects synthesis engine parameters
    """
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
        
        if msg_type == 'note_on':
            note = data.get('note')
            velocity = data.get('velocity', 127)
            voice = self.voice_manager.allocate_voice(channel, note, velocity)
            
            # Set note frequency as source for oscillator pitch
            note_freq = FixedPoint.midi_note_to_fixed(note)
            self.parameter_processor.mod_matrix.set_source_value(
                ModSource.NOTE, 
                channel, 
                FixedPoint.to_float(note_freq)
            )
            
            # Set velocity as source for amplitude modulation
            self.parameter_processor.mod_matrix.set_source_value(
                ModSource.VELOCITY,
                channel,
                FixedPoint.to_float(voice.velocity)
            )
            
            return {'type': 'voice_allocated', 'voice': voice}
            
        elif msg_type == 'note_off':
            note = data.get('note')
            voice = self.voice_manager.release_voice(channel, note)
            return {'type': 'voice_released', 'voice': voice}
            
        elif msg_type in ('pressure', 'pitch_bend', 'cc'):
            voice = None
            if channel in self.voice_manager.channel_voices:
                # Find most recent voice on this channel
                for note in self.voice_manager.channel_voices[channel]:
                    voice = self.voice_manager.get_voice(channel, note)
                    if voice and voice.active:
                        break
            
            if msg_type == 'pressure':
                self.parameter_processor.handle_pressure(channel, data.get('value', 0), voice)
            elif msg_type == 'pitch_bend':
                self.parameter_processor.handle_pitch_bend(channel, data.get('value', 8192), voice)
            elif msg_type == 'cc' and data.get('number') == 74:  # Timbre
                self.parameter_processor.handle_timbre(channel, data.get('value', 0), voice)
