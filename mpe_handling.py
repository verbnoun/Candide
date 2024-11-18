import time
from fixed_point_math import FixedPoint 

class Route:
    """Single value route with config-defined behavior"""
    def __init__(self, config):
        self.source_id = config.get('source')
        self.target_id = config.get('target')
        self.amount = FixedPoint.from_float(config.get('amount', 1.0))
        self.curve = config.get('curve', 'linear')
        self.min_value = FixedPoint.from_float(config.get('range', {}).get('min', 0.0))
        self.max_value = FixedPoint.from_float(config.get('range', {}).get('max', 1.0))
        
        # State
        self.current_value = FixedPoint.ZERO
        self.last_value = FixedPoint.ZERO
        
        if Constants.DEBUG:
            print(f"[ROUTE] Created route:")
            print(f"      Source: {self.source_id}")
            print(f"      Target: {self.target_id}")
            print(f"      Amount: {FixedPoint.to_float(self.amount):.3f}")
            print(f"      Curve: {self.curve}")
            print(f"      Range: {FixedPoint.to_float(self.min_value):.3f} to {FixedPoint.to_float(self.max_value):.3f}")
            
    def process_value(self, value):
        """Process value through route's curve and scaling"""
        # Store previous
        self.last_value = self.current_value
        
        # Convert to fixed point if needed
        if not isinstance(value, int):
            value = FixedPoint.from_float(value)
            
        # Apply curve
        if self.curve == 'exponential':
            processed = FixedPoint.multiply(value, value)
        elif self.curve == 'logarithmic':
            processed = FixedPoint.ONE - FixedPoint.multiply(
                FixedPoint.ONE - value,
                FixedPoint.ONE - value
            )
        elif self.curve == 's_curve':
            x2 = FixedPoint.multiply(value, value)
            x3 = FixedPoint.multiply(x2, value)
            processed = FixedPoint.multiply(x2, FixedPoint.from_float(3.0)) - \
                       FixedPoint.multiply(x3, FixedPoint.from_float(2.0))
        else:  # linear
            processed = value
            
        # Scale to range
        range_size = self.max_value - self.min_value
        self.current_value = self.min_value + FixedPoint.multiply(processed, range_size)
        
        # Apply amount
        self.current_value = FixedPoint.multiply(self.current_value, self.amount)
        
        if Constants.DEBUG:
            if abs(FixedPoint.to_float(self.current_value - self.last_value)) > 0.01:
                print(f"[ROUTE] Value update:")
                print(f"      Source: {self.source_id}")
                print(f"      Target: {self.target_id}")
                print(f"      Input: {FixedPoint.to_float(value):.3f}")
                print(f"      Output: {FixedPoint.to_float(self.current_value):.3f}")
                
        return self.current_value

class NoteState:
    """Complete note state defined entirely by config"""
    def __init__(self, channel, note, velocity, config):
        self.channel = channel
        self.note = note
        self.active = True
        self.creation_time = time.monotonic()
        self.last_update = self.creation_time
        
        # Parameter storage - all in fixed point
        self.parameter_values = {}
        
        # Store initial values
        self.parameter_values['note'] = FixedPoint.midi_note_to_fixed(note)
        self.parameter_values['velocity'] = FixedPoint.normalize_midi_value(velocity)
        
        # Config validation
        if not self._validate_config(config):
            raise ValueError("Invalid or incomplete instrument config")
            
        # Create routes from config
        self.routes_by_source = {}  # source_id: [Route]
        self.routes_by_target = {}  # target_id: [Route]
        self._create_routes(config)
        
        # Reference to underlying synthio note (created later)
        self.synth_note = None
        
        if Constants.DEBUG:
            print(f"\n[NOTE] Created note state:")
            print(f"      Channel: {channel}")
            print(f"      Note: {note}")
            print(f"      Velocity: {FixedPoint.to_float(self.parameter_values['velocity']):.3f}")
            
    def _validate_config(self, config):
        """Ensure config has required elements"""
        if not config:
            return False
            
        # Must have routes defined
        if 'routes' not in config:
            if Constants.DEBUG:
                print("[NOTE] No routes defined in config")
            return False
            
        # Must have parameter definitions
        if 'parameters' not in config:
            if Constants.DEBUG:
                print("[NOTE] No parameters defined in config")
            return False
            
        return True
        
    def _create_routes(self, config):
        """Create all routes defined in config"""
        for route_config in config['routes']:
            route = Route(route_config)
            
            # Index by source
            if route.source_id not in self.routes_by_source:
                self.routes_by_source[route.source_id] = []
            self.routes_by_source[route.source_id].append(route)
            
            # Index by target
            if route.target_id not in self.routes_by_target:
                self.routes_by_target[route.target_id] = []
            self.routes_by_target[route.target_id].append(route)
            
        if Constants.DEBUG:
            print(f"[NOTE] Created {len(self.routes_by_source)} route sources")
            print(f"      {len(self.routes_by_target)} route targets")
            
    def handle_value_change(self, source_id, value):
        """Process value change through configured routes"""
        if source_id not in self.routes_by_source:
            return
            
        # Store raw value
        self.parameter_values[source_id] = value
        
        # Process through all routes from this source
        for route in self.routes_by_source[source_id]:
            processed = route.process_value(value)
            
            # Store processed value
            target_id = route.target_id
            if target_id not in self.parameter_values:
                self.parameter_values[target_id] = FixedPoint.ZERO
                
            # Combine values based on target's combining rule
            current = self.parameter_values[target_id]
            if target_id in self.config['parameters']:
                combine_rule = self.config['parameters'][target_id].get('combine', 'add')
                if combine_rule == 'multiply':
                    if current == FixedPoint.ZERO:
                        self.parameter_values[target_id] = processed
                    else:
                        self.parameter_values[target_id] = FixedPoint.multiply(current, processed)
                else:  # add
                    self.parameter_values[target_id] += processed
            
        if Constants.DEBUG:
            print(f"[NOTE] Value change processed:")
            print(f"      Source: {source_id}")
            print(f"      Value: {FixedPoint.to_float(value):.3f}")
            print(f"      Affected targets: {[r.target_id for r in self.routes_by_source[source_id]]}")
            
    def get_parameter_value(self, param_id):
        """Get current value for a parameter"""
        return self.parameter_values.get(param_id, FixedPoint.ZERO)
        
    def handle_release(self):
        """Process note release"""
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            
            # Signal release through routes
            self.handle_value_change('gate', FixedPoint.ZERO)
            
            if Constants.DEBUG:
                print(f"[NOTE] Released ch:{self.channel} note:{self.note}")
                print(f"      Active time: {self.release_time - self.creation_time:.3f}s")

class MPEVoiceManager:
    """Manages note lifecycle and routing"""
    def __init__(self):
        self.active_notes = {}  # (channel, note): NoteState
        self.pending_values = {}  # (channel, source_id): value
        self.current_config = None
        
    def set_config(self, config):
        """Update current configuration"""
        self.current_config = config
        
    def store_pending_value(self, channel, source_id, value):
        """Store value that arrives before note-on"""
        key = (channel, source_id)
        self.pending_values[key] = value
        
        if Constants.DEBUG:
            print(f"[VOICE] Stored pending value:")
            print(f"      Channel: {channel}")
            print(f"      Source: {source_id}")
            print(f"      Value: {value}")
            
    def get_pending_values(self, channel):
        """Get and clear pending values for a channel"""
        values = {}
        
        # Get all values for this channel
        for (c, source_id), value in list(self.pending_values.items()):
            if c == channel:
                values[source_id] = value
                del self.pending_values[(c, source_id)]
                
        return values
        
    def allocate_voice(self, channel, note, velocity):
        """Create new voice if config allows"""
        if not self.current_config:
            return None
            
        try:
            # Create note state
            note_state = NoteState(channel, note, velocity, self.current_config)
            
            # Apply any pending values
            pending = self.get_pending_values(channel)
            for source_id, value in pending.items():
                note_state.handle_value_change(source_id, value)
            
            # Store note
            self.active_notes[(channel, note)] = note_state
            
            if Constants.DEBUG:
                print(f"[VOICE] Allocated voice:")
                print(f"      Channel: {channel}")
                print(f"      Note: {note}")
                print(f"      Velocity: {FixedPoint.to_float(note_state.parameter_values['velocity']):.3f}")
                if pending:
                    print(f"      Applied pending: {list(pending.keys())}")
            
            return note_state
            
        except Exception as e:
            print(f"[ERROR] Voice allocation failed: {str(e)}")
            return None
            
    def get_voice(self, channel, note):
        """Get voice if it exists"""
        return self.active_notes.get((channel, note))
        
    def release_voice(self, channel, note):
        """Handle voice release"""
        voice = self.get_voice(channel, note)
        if voice:
            voice.handle_release()
            return voice
        return None
        
    def cleanup_voices(self):
        """Remove completed voices"""
        current_time = time.monotonic()
        for key in list(self.active_notes.keys()):
            note = self.active_notes[key]
            if not note.active and (current_time - note.release_time) > 0.5:  # Config should define this
                if Constants.DEBUG:
                    print(f"[VOICE] Cleaning up voice:")
                    print(f"      Channel: {note.channel}")
                    print(f"      Note: {note.note}")
                del self.active_notes[key]

class MPEMessageRouter:
    """Routes messages based on config"""
    def __init__(self, voice_manager):
        self.voice_manager = voice_manager
        self.current_config = None
        
    def set_config(self, config):
        """Set current configuration"""
        self.current_config = config
        self.voice_manager.set_config(config)
        
    def route_message(self, message):
        """Route message according to config"""
        if not message or not self.current_config:
            return None
            
        msg_type = message['type']
        channel = message['channel']
        data = message.get('data', {})
        
        # Look up message routing in config
        if msg_type not in self.current_config.get('message_routes', {}):
            return None
            
        route = self.current_config['message_routes'][msg_type]
        source_id = route.get('source_id')
        
        if not source_id:
            return None
            
        if msg_type == 'note_on':
            note = data.get('note')
            velocity = data.get('velocity', 127)
            voice = self.voice_manager.allocate_voice(channel, note, velocity)
            return {'type': 'voice_allocated', 'voice': voice}
            
        elif msg_type == 'note_off':
            note = data.get('note')
            voice = self.voice_manager.release_voice(channel, note)
            return {'type': 'voice_released', 'voice': voice}
            
        else:
            # Get value according to route
            value = route['value_func'](data) if 'value_func' in route else data.get('value')
            
            # Store for any matching voices
            voice = self.voice_manager.get_voice(channel, data.get('note'))
            if voice:
                voice.handle_value_change(source_id, value)
            else:
                # Store as pending
                self.voice_manager.store_pending_value(channel, source_id, value)
                
        return None
        
    def process_updates(self):
        """Process any pending updates"""
        self.voice_manager.cleanup_voices()
