import time
from fixed_point_math import FixedPoint
from synth_constants import Constants, ModSource, ModTarget

class EnvelopeGateState:
    """Tracks gate states and transitions for an MPE voice"""
    def __init__(self, envelope_config):
        self.config = envelope_config
        self.current_stage = 'attack'
        self.stage_start_time = 0
        self.stage_start_level = FixedPoint.ZERO
        self.stage_target_level = FixedPoint.ZERO
        self.control_level = FixedPoint.ZERO
        self._debug_last_level = None
        self._control_objects = {}  # Store control objects for each stage
        
        # Find and store control objects
        self._find_control_objects(envelope_config)
        
    def _find_control_objects(self, config):
        """Recursively find control objects in envelope config"""
        for stage, stage_config in config.items():
            if isinstance(stage_config, dict) and 'control' in stage_config:
                control = stage_config['control']
                if all(k in control for k in ['cc', 'name', 'range']):
                    self._control_objects[stage] = control
        
    def start_stage(self, stage, start_level):
        """Start a new envelope stage"""
        self.current_stage = stage
        self.stage_start_time = time.monotonic()
        self.stage_start_level = FixedPoint.from_float(start_level)
        
        stage_config = self.config.get(stage, {})
        if 'level' in stage_config:
            self.stage_target_level = FixedPoint.from_float(stage_config['level'])
        elif 'level_scale' in stage_config:
            scale = FixedPoint.from_float(stage_config['level_scale'])
            self.stage_target_level = FixedPoint.multiply(self.stage_start_level, scale)
        
        if Constants.DEBUG:
            print(f"[ENV] Starting {stage} stage: start={FixedPoint.to_float(self.stage_start_level):.3f} target={FixedPoint.to_float(self.stage_target_level):.3f}")
    
    def update_control(self, cc_number, value):
        """Update control value for current stage"""
        # Check if current stage has a control object
        if self.current_stage in self._control_objects:
            control = self._control_objects[self.current_stage]
            
            # Check if this CC matches the stage's control
            if control['cc'] == cc_number:
                min_val = control['range']['min']
                max_val = control['range']['max']
                curve = control.get('curve', 'linear')
                
                # Normalize MIDI value to 0-1
                normalized_value = value / 127.0
                
                # Apply curve
                if curve == 'exponential':
                    scaled_value = normalized_value * normalized_value
                elif curve == 'logarithmic':
                    scaled_value = 1 - ((1 - normalized_value) ** 2)
                elif curve == 's_curve':
                    scaled_value = 3 * (normalized_value ** 2) - 2 * (normalized_value ** 3)
                else:  # linear
                    scaled_value = normalized_value
                
                # Scale to parameter range
                param_value = min_val + (scaled_value * (max_val - min_val))
                
                # Update stage parameter
                stage_config = self.config.get(self.current_stage, {})
                if 'time' in stage_config:
                    stage_config['time'] = param_value
                
                if Constants.DEBUG:
                    print(f"[ENV] Control update for {self.current_stage}:")
                    print(f"      CC: {cc_number}")
                    print(f"      Raw Value: {value}")
                    print(f"      Normalized: {normalized_value:.3f}")
                    print(f"      Scaled Value: {param_value:.3f}")
    
    def should_transition(self):
        """Check if current stage should transition"""
        if self.current_stage == 'sustain':
            return False
            
        stage_config = self.config.get(self.current_stage, {})
        if 'time' in stage_config:
            stage_time = stage_config['time']
            elapsed = time.monotonic() - self.stage_start_time
            return elapsed >= stage_time
        return False
    
    def get_next_stage(self):
        """Get next envelope stage based on current"""
        if self.current_stage == 'attack':
            return 'decay'
        elif self.current_stage == 'decay':
            return 'sustain'
        elif self.current_stage == 'sustain':
            return 'release'
        return None

class MPEVoice:
    """Tracks state of an active MPE voice with gate-based envelope"""
    def __init__(self, channel, note, velocity):
        self.channel = channel
        self.note = note
        self.active = True
        self.start_time = time.monotonic()
        self.last_update = self.start_time
        self.envelope_state = None  # Set when config provided
        
        # Initial state capture using fixed point
        self.initial_state = {
            'pressure': FixedPoint.ZERO,
            'timbre': FixedPoint.from_float(0.5),  # Default center
            'bend': FixedPoint.ZERO,
            'velocity': FixedPoint.normalize_midi_value(velocity)
        }
        
        # Current state
        self.pressure = FixedPoint.ZERO
        self.pitch_bend = FixedPoint.ZERO
        self.timbre = FixedPoint.ZERO
        
        # Track last values for change detection
        self.last_values = {
            'pressure': self.pressure,
            'bend': self.pitch_bend,
            'timbre': self.timbre
        }
        
        self.synth_note = None
    
    def configure_envelope(self, envelope_config):
        """Set up envelope gating system"""
        self.envelope_state = EnvelopeGateState(envelope_config)
        self.envelope_state.start_stage('attack', 0.0)
    
    def update_initial_state(self, control_type, value):
        """Update initial state before note starts"""
        if not self.synth_note:
            self.initial_state[control_type] = value
            return True
        return False

class MPEVoiceManager:
    """Manages voice allocation and parameter tracking"""
    def __init__(self):
        self.active_voices = {}  # (channel, note): MPEVoice
        self.channel_voices = {}  # channel: set of active notes
        self.pending_controls = {}  # (channel, key): {control_values}
        self.current_config = None
        
    def set_instrument_config(self, config):
        """Update current instrument configuration"""
        self.current_config = config
        
    def store_pending_control(self, channel, key, control_type, value):
        """Store control message that arrives before note-on"""
        pending_key = (channel, key) if key is not None else channel
        if pending_key not in self.pending_controls:
            self.pending_controls[pending_key] = {}
        self.pending_controls[pending_key][control_type] = value
            
    def get_pending_controls(self, channel, key):
        """Get and clear pending controls for a note"""
        # Try exact match first
        pending_key = (channel, key)
        controls = self.pending_controls.get(pending_key, {})
        
        # Also check channel-only controls
        channel_controls = self.pending_controls.get(channel, {})
        controls.update(channel_controls)
        
        # Clear used controls
        if pending_key in self.pending_controls:
            del self.pending_controls[pending_key]
        if channel in self.pending_controls:
            del self.pending_controls[channel]
            
        return controls
        
    def allocate_voice(self, channel, note, velocity):
        """Allocate new voice with initial control values"""
        if not self.current_config:
            return None
            
        if (channel, note) in self.active_voices:
            voice = self.active_voices[(channel, note)]
            voice.initial_state['velocity'] = FixedPoint.normalize_midi_value(velocity)
            return voice
            
        # Create new voice with envelope config
        voice = MPEVoice(channel, note, velocity)
        voice.configure_envelope(self.current_config['envelope'])
        
        # Apply any pending control values
        pending = self.get_pending_controls(channel, note)
        for control_type, value in pending.items():
            voice.update_initial_state(control_type, value)
        
        self.active_voices[(channel, note)] = voice
        
        if channel not in self.channel_voices:
            self.channel_voices[channel] = set()
        self.channel_voices[channel].add(note)
        
        if Constants.DEBUG:
            print(f"[VOICE] Allocated: ch={channel} note={note} vel={velocity}")
        
        return voice
    
    def get_voice(self, channel, note):
        """Get voice if it exists"""
        return self.active_voices.get((channel, note))
    
    def release_voice(self, channel, note):
        """Handle voice release and cleanup"""
        voice_key = (channel, note)
        if voice_key in self.active_voices:
            voice = self.active_voices[voice_key]
            voice.active = False
            if voice.envelope_state:
                voice.envelope_state.start_stage('release', 
                    FixedPoint.to_float(voice.initial_state['velocity']))
            
            if channel in self.channel_voices:
                self.channel_voices[channel].discard(note)
                if not self.channel_voices[channel]:
                    del self.channel_voices[channel]
            
            if Constants.DEBUG:
                print(f"[VOICE] Released: ch={channel} note={note}")
                    
            return voice
        return None
    
    def update_voices(self):
        """Update envelope states for all voices"""
        for voice in list(self.active_voices.values()):
            if not voice.envelope_state:
                continue
                
            # Check for stage transitions
            if voice.envelope_state.should_transition():
                next_stage = voice.envelope_state.get_next_stage()
                if next_stage:
                    current_level = voice.initial_state['velocity']  # TODO: Get actual current level
                    voice.envelope_state.start_stage(next_stage, 
                        FixedPoint.to_float(current_level))

class MPEParameterProcessor:
    """Processes MPE parameters according to instrument config"""
    def __init__(self, voice_manager, mod_matrix):
        self.voice_manager = voice_manager
        self.mod_matrix = mod_matrix
        self.config = None
    
    def set_instrument_config(self, config):
        """Update current instrument configuration"""
        self.config = config
    
    def _is_expression_enabled(self, expr_type):
        """Check if expression type is enabled in config"""
        if not self.config or 'expression' not in self.config:
            return False
        return self.config['expression'].get(expr_type, False)

    def _get_scaling(self, param_type):
        """Get scaling factor for parameter"""
        if not self.config or 'scaling' not in self.config:
            return 1.0
        return self.config['scaling'].get(param_type, 1.0)
    
    def handle_pressure(self, channel, value, key=None):
        """Process pressure value for voice"""
        if not self._is_expression_enabled('pressure'):
            return False
            
        voice = self.voice_manager.get_voice(channel, key) if key is not None else None
        if not voice:
            self.voice_manager.store_pending_control(channel, key, 'pressure', value)
            return True
            
        if voice.active:
            scale = self._get_scaling('pressure')
            normalized = FixedPoint.multiply(
                FixedPoint.normalize_midi_value(value),
                FixedPoint.from_float(scale)
            )
            
            if voice.envelope_state:
                voice.envelope_state.update_control(ModSource.PRESSURE, FixedPoint.to_float(normalized))
            
            voice.pressure = normalized
            voice.last_values['pressure'] = normalized
            
            # Route to mod matrix
            self.mod_matrix.set_source_value(
                ModSource.PRESSURE, 
                voice.channel,
                FixedPoint.to_float(normalized)
            )
            return True
        return False

    def handle_pitch_bend(self, channel, value, key=None):
        """Process pitch bend value for voice"""
        if not self._is_expression_enabled('pitch_bend'):
            return False
            
        voice = self.voice_manager.get_voice(channel, key) if key is not None else None
        if not voice:
            self.voice_manager.store_pending_control(channel, key, 'bend', value)
            return True
            
        if voice.active:
            semitones = self._get_scaling('pitch_bend')
            if semitones > 0:
                normalized = FixedPoint.normalize_pitch_bend(value)
                scaled = FixedPoint.multiply(
                    normalized,
                    FixedPoint.from_float(semitones / 48.0)  # Scale to semitones
                )
                
                voice.pitch_bend = scaled
                voice.last_values['bend'] = scaled
                
                # Route to mod matrix
                self.mod_matrix.set_source_value(
                    ModSource.PITCH_BEND,
                    voice.channel,
                    FixedPoint.to_float(scaled)
                )
                return True
        return False

class MPEMessageRouter:
    """Routes MPE messages to appropriate handlers"""
    def __init__(self, voice_manager, parameter_processor, modulation_matrix):
        self.voice_manager = voice_manager
        self.parameter_processor = parameter_processor
        self.modulation_matrix = modulation_matrix
        self.current_instrument_config = None
        self._control_map = {}  # Map CC numbers to control objects

    def set_instrument_config(self, config):
        """Set the current instrument configuration"""
        self.current_instrument_config = config
        
        # Build CC control map
        self._control_map.clear()
        self._find_control_objects(config)
        
        # Configure modulation matrix
        self.modulation_matrix.configure_from_instrument(config)

    def _find_control_objects(self, config, path=''):
        """Recursively find all control objects in config"""
        if isinstance(config, dict):
            for key, value in config.items():
                new_path = f"{path}.{key}" if path else key
                
                if key == 'control' and isinstance(value, dict):
                    if all(k in value for k in ['cc', 'name', 'range']):
                        self._control_map[value['cc']] = {
                            'path': path,
                            'control': value
                        }
                else:
                    self._find_control_objects(value, new_path)
                    
        elif isinstance(config, list):
            for i, item in enumerate(config):
                new_path = f"{path}[{i}]"
                self._find_control_objects(item, new_path)

    def route_message(self, message):
        """Route incoming MPE message to appropriate handler"""
        if not message or 'type' not in message:
            return
            
        msg_type = message['type']
        channel = message['channel']
        data = message.get('data', {})
        
        # Extract key for note-specific messages
        key = data.get('note') if msg_type in ('note_on', 'note_off') else None
            
        # Handle control messages first to ensure proper initial state
        if msg_type == 'pressure':
            self.parameter_processor.handle_pressure(channel, data.get('value', 0), key)
        elif msg_type == 'pitch_bend':
            self.parameter_processor.handle_pitch_bend(channel, data.get('value', 8192), key)
        elif msg_type == 'cc':
            # Get voice if this is a note-specific CC
            voice = self.voice_manager.get_voice(channel, key) if key is not None else None
            
            cc_number = data.get('number')
            cc_value = data.get('value', 0)
            
            # Check if this CC is mapped to a control
            if cc_number in self._control_map:
                control_info = self._control_map[cc_number]
                
                if voice and voice.envelope_state:
                    # Update envelope stage if applicable
                    voice.envelope_state.update_control(cc_number, cc_value)
                
                if Constants.DEBUG:
                    print(f"[MPE] Flexible CC: ch={channel} cc={cc_number} value={cc_value}")
                    print(f"      Path: {control_info['path']}")
                    print(f"      Name: {control_info['control']['name']}")
            
        # Note events are always processed
        elif msg_type == 'note_on':
            note = data.get('note')
            velocity = data.get('velocity', 127)
            voice = self.voice_manager.allocate_voice(channel, note, velocity)
            
            if Constants.DEBUG:
                print(f"[MPE] Note On: ch={channel} note={note} vel={velocity}")
                
            return {'type': 'voice_allocated', 'voice': voice}
            
        elif msg_type == 'note_off':
            note = data.get('note')
            voice = self.voice_manager.release_voice(channel, note)
            
            if Constants.DEBUG:
                print(f"[MPE] Note Off: ch={channel} note={note}")
                
            return {'type': 'voice_released', 'voice': voice}
    
    def process_updates(self):
        """Process any pending state updates"""
        if self.current_instrument_config:
            self.voice_manager.update_voices()
