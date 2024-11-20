"""
Advanced Voice Management System for Synthesizer

Handles voice lifecycle, parameter routing, and sound generation.
"""

import time
import sys
from fixed_point_math import FixedPoint
from constants import ModSource, ModTarget, VOICES_DEBUG

def _log(message):
    """
    Conditional logging function that respects VOICES_DEBUG flag.
    
    Args:
        message (str): Message to log
    """
    if VOICES_DEBUG:
        print(f"[VOICES] {message}", file=sys.stderr)

class Route:
    """
    Handles parameter routing with advanced processing capabilities.
    Supports various curve transformations and scaling.
    """
    def __init__(self, config):
        _log(f"Creating Route with config: {config}")
        self.source_id = config.get('source')
        self.target_id = config.get('target')
        self.amount = FixedPoint.from_float(config.get('amount', 1.0))
        self.curve = config.get('curve', 'linear')
        self.min_value = FixedPoint.from_float(config.get('range', {}).get('min', 0.0))
        self.max_value = FixedPoint.from_float(config.get('range', {}).get('max', 1.0))
        
        # State tracking
        self.current_value = FixedPoint.ZERO
        self.last_value = FixedPoint.ZERO
    
    def process_value(self, value):
        """
        Process input value through configured transformations.
        
        Args:
            value (float/int): Input value to process
        
        Returns:
            FixedPoint: Processed and scaled value
        """
        _log(f"Processing route value: source={self.source_id}, target={self.target_id}, input={value}")
        
        # Convert to fixed point
        if not isinstance(value, FixedPoint):
            value = FixedPoint.from_float(value)
        
        # Store previous value
        self.last_value = self.current_value
        
        # Apply curve transformations
        if self.curve == 'exponential':
            processed = self._exponential_curve(value)
            _log(f"Applied exponential curve transformation")
        elif self.curve == 'logarithmic':
            processed = self._logarithmic_curve(value)
            _log(f"Applied logarithmic curve transformation")
        elif self.curve == 's_curve':
            processed = self._s_curve(value)
            _log(f"Applied S-curve transformation")
        else:
            processed = value
            _log(f"Using linear transformation")
        
        # Scale to configured range
        range_size = self.max_value - self.min_value
        scaled_value = self.min_value + FixedPoint.multiply(processed, range_size)
        
        # Apply modulation amount
        self.current_value = FixedPoint.multiply(scaled_value, self.amount)
        
        _log(f"Route processed: last_value={self.last_value}, current_value={self.current_value}")
        
        return self.current_value
    
    def _exponential_curve(self, value):
        """Exponential curve transformation"""
        _log(f"Computing exponential curve for value: {value}")
        exp_scale = FixedPoint.from_float(5.0)
        scaled = FixedPoint.multiply(value, exp_scale)
        x2 = FixedPoint.multiply(scaled, scaled)
        x3 = FixedPoint.multiply(x2, scaled)
        processed = (FixedPoint.ONE + scaled + 
                     FixedPoint.multiply(x2, FixedPoint.from_float(0.5)) + 
                     FixedPoint.multiply(x3, FixedPoint.from_float(0.166)))
        result = FixedPoint.multiply(processed, FixedPoint.from_float(0.0084))
        _log(f"Exponential curve result: {result}")
        return result
    
    def _logarithmic_curve(self, value):
        """Logarithmic curve transformation"""
        _log(f"Computing logarithmic curve for value: {value}")
        result = FixedPoint.ONE - FixedPoint.multiply(
            FixedPoint.ONE - value,
            FixedPoint.ONE - value
        )
        _log(f"Logarithmic curve result: {result}")
        return result
    
    def _s_curve(self, value):
        """S-curve transformation"""
        _log(f"Computing S-curve for value: {value}")
        x2 = FixedPoint.multiply(value, value)
        x3 = FixedPoint.multiply(x2, value)
        result = FixedPoint.multiply(x2, FixedPoint.from_float(3.0)) - \
                 FixedPoint.multiply(x3, FixedPoint.from_float(2.0))
        _log(f"S-curve result: {result}")
        return result

class NoteState:
    """
    Comprehensive note state management with advanced routing capabilities.
    Handles per-note parameter tracking and modulation.
    """
    def __init__(self, channel, note, velocity, config):
        _log(f"Creating NoteState: channel={channel}, note={note}, velocity={velocity}")
        self.channel = channel
        self.note = note
        self.active = True
        self.creation_time = time.monotonic()
        self.last_update = self.creation_time
        self.config = config
        
        # Initialize parameter values
        self.parameter_values = {
            'note': FixedPoint.midi_note_to_fixed(note),
            'velocity': FixedPoint.normalize_midi_value(velocity),
            'frequency': FixedPoint.from_float(
                440.0 * (2 ** ((note - 69) / 12.0))
            ),
            'amplitude': FixedPoint.normalize_midi_value(velocity)
        }
        
        # Initialize module parameters from config
        self._init_module_parameters('oscillator')
        self._init_module_parameters('filter')
        self._init_module_parameters('amplifier')
        
        # Route management
        self.routes_by_source = {}
        self.routes_by_target = {}
        self._create_routes(config)
        
        # Synth note reference (to be set by voice manager)
        self.synth_note = None
        
        _log(f"NoteState initialized with {len(self.routes_by_source)} source routes")
    
    def _init_module_parameters(self, module_name):
        """Initialize parameters for a module from config"""
        _log(f"Initializing parameters for module: {module_name}")
        if module_name not in self.config:
            _log(f"No configuration found for module: {module_name}")
            return
            
        module = self.config[module_name]
        for param_name, param_data in module.items():
            if isinstance(param_data, dict) and 'value' in param_data:
                param_id = f"{module_name}.{param_name}"
                self.parameter_values[param_id] = FixedPoint.from_float(param_data['value'])
                _log(f"Set parameter {param_id} to {self.parameter_values[param_id]}")
    
    def _create_routes(self, config):
        """
        Create routing configuration based on instrument patches.
        
        Args:
            config (dict): Instrument configuration
        """
        _log("Creating routes from instrument configuration")
        patches = config.get('patches', [])
        for patch_config in patches:
            source = patch_config.get('source', {})
            destination = patch_config.get('destination', {})
            processing = patch_config.get('processing', {})
            
            # Get parameter range if defined in module config
            if destination:
                module_id = destination.get('id')
                attribute = destination.get('attribute')
                if module_id and attribute:
                    module = config.get(module_id, {})
                    param = module.get(attribute, {})
                    if isinstance(param, dict) and 'range' in param:
                        processing['range'] = param['range']
            
            # Create route with source transform if needed
            source_id = source.get('id')
            if source_id in config.get('sources', {}):
                source_config = config['sources'][source_id]
                attribute = source.get('attribute')
                if attribute and attribute in source_config.get('attributes', {}):
                    attr_config = source_config['attributes'][attribute]
                    # Apply source-specific transformations
                    if 'transform' in attr_config:
                        if attr_config['transform'] == 'midi_to_frequency':
                            processing['range'] = {
                                'in_min': 0,
                                'in_max': 127,
                                'out_min': 20.0,  # 20 Hz
                                'out_max': 20000.0  # 20 kHz
                            }
            
            route = Route({
                'source': source.get('id'),
                'target': destination.get('id'),
                'amount': processing.get('amount', 1.0),
                'curve': processing.get('curve', 'linear'),
                'range': processing.get('range', {})
            })
            
            # Index routes by source and target
            source_id = route.source_id
            target_id = route.target_id
            
            if source_id not in self.routes_by_source:
                self.routes_by_source[source_id] = []
            self.routes_by_source[source_id].append(route)
            
            if target_id not in self.routes_by_target:
                self.routes_by_target[target_id] = []
            self.routes_by_target[target_id].append(route)
        
        _log(f"Created {len(self.routes_by_source)} source routes and {len(self.routes_by_target)} target routes")
    
    def handle_value_change(self, source_id, value):
        """
        Process value changes through configured routes.
        
        Args:
            source_id (str): Source identifier
            value (float/int): Input value
        """
        _log(f"Handling value change: source={source_id}, value={value}")
        
        if source_id not in self.routes_by_source:
            _log(f"No routes found for source: {source_id}")
            return
        
        # Store source value
        self.parameter_values[source_id] = value
        
        # Process through all routes for this source
        for route in self.routes_by_source[source_id]:
            processed_value = route.process_value(value)
            target_id = route.target_id
            
            # Get module config for target
            module_id = target_id.split('.')[0] if '.' in target_id else target_id
            module = self.config.get(module_id, {})
            
            # Determine combination method from module config
            combine_rule = 'add'  # Default
            if isinstance(module, dict):
                combine_rule = module.get('combine', 'add')
            
            # Apply value according to combination rule
            current_value = self.parameter_values.get(target_id, FixedPoint.ZERO)
            if combine_rule == 'multiply':
                if current_value == FixedPoint.ZERO:
                    self.parameter_values[target_id] = processed_value
                else:
                    self.parameter_values[target_id] = FixedPoint.multiply(current_value, processed_value)
            else:  # add
                self.parameter_values[target_id] += processed_value
            
            _log(f"Route processed: source={source_id}, target={target_id}, processed_value={processed_value}, combine_rule={combine_rule}")
    
    def get_parameter_value(self, param_id):
        """
        Retrieve current value for a specific parameter.
        
        Args:
            param_id (str): Parameter identifier
        
        Returns:
            FixedPoint: Current parameter value
        """
        value = self.parameter_values.get(param_id, FixedPoint.ZERO)
        _log(f"Retrieved parameter value: param_id={param_id}, value={value}")
        return value
    
    def handle_release(self):
        """
        Process note release, updating state and triggering release mechanisms.
        """
        _log(f"Handling note release: channel={self.channel}, note={self.note}")
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            
            # Trigger gate to zero
            self.handle_value_change('gate', FixedPoint.ZERO)
            _log("Note release completed")

class MPEVoiceManager:
    """
    Manages voice lifecycle, allocation, and global voice state.
    """
    def __init__(self):
        _log("Initializing MPEVoiceManager")
        self.active_notes = {}
        self.pending_values = {}
        self.current_config = None
    
    def set_config(self, config):
        """
        Update current instrument configuration.
        
        Args:
            config (dict): Instrument configuration
        """
        _log(f"Setting instrument configuration: {config}")
        self.current_config = config
    
    def store_pending_value(self, channel, source_id, value, control_name=None):
        """
        Store values that arrive before note-on event.
        
        Args:
            channel (int): MIDI channel
            source_id (str): Source identifier
            value (float/int): Input value
            control_name (str, optional): Control name
        """
        key = (channel, source_id)
        self.pending_values[key] = (value, control_name)
        _log(f"Stored pending value: channel={channel}, source_id={source_id}, value={value}, control_name={control_name}")
    
    def get_pending_values(self, channel):
        """
        Retrieve and clear pending values for a specific channel.
        
        Args:
            channel (int): MIDI channel
        
        Returns:
            dict: Pending values for the channel
        """
        values = {}
        for (c, source_id), (value, control_name) in list(self.pending_values.items()):
            if c == channel:
                values[source_id] = (value, control_name)
                del self.pending_values[(c, source_id)]
        
        _log(f"Retrieved pending values for channel {channel}: {values}")
        return values
    
    def allocate_voice(self, channel, note, velocity):
        """
        Create a new voice for a note.
        
        Args:
            channel (int): MIDI channel
            note (int): MIDI note number
            velocity (int): Note velocity
        
        Returns:
            NoteState: Allocated voice or None
        """
        _log(f"Attempting to allocate voice: channel={channel}, note={note}, velocity={velocity}")
        
        if not self.current_config:
            _log("No current configuration available for voice allocation")
            return None
        
        try:
            # Create note state
            note_state = NoteState(channel, note, velocity, self.current_config)
            
            # Apply any pending values
            pending = self.get_pending_values(channel)
            for source_id, (value, _) in pending.items():
                note_state.handle_value_change(source_id, value)
            
            # Store voice
            self.active_notes[(channel, note)] = note_state
            
            _log(f"Voice allocated successfully: channel={channel}, note={note}")
            return note_state
        
        except Exception as e:
            _log(f"[ERROR] Voice allocation failed: {str(e)}")
            return None
    
    def get_voice(self, channel, note):
        """
        Retrieve an active voice.
        
        Args:
            channel (int): MIDI channel
            note (int): MIDI note number
        
        Returns:
            NoteState: Active voice or None
        """
        voice = self.active_notes.get((channel, note))
        _log(f"Retrieving voice: channel={channel}, note={note}, found={voice is not None}")
        return voice
    
    def release_voice(self, channel, note):
        """
        Handle voice release.
        
        Args:
            channel (int): MIDI channel
            note (int): MIDI note number
        
        Returns:
            NoteState: Released voice or None
        """
        _log(f"Releasing voice: channel={channel}, note={note}")
        voice = self.get_voice(channel, note)
        if voice:
            voice.handle_release()
            _log(f"Voice released successfully: channel={channel}, note={note}")
            return voice
        _log(f"No voice found to release: channel={channel}, note={note}")
        return None
    
    def cleanup_voices(self):
        """
        Remove completed voices after a grace period.
        """

        current_time = time.monotonic()
        for key in list(self.active_notes.keys()):
            note = self.active_notes[key]
            if not note.active and (current_time - note.release_time) > 0.5:
                del self.active_notes[key]
                _log(f"Removed inactive voice: channel={key[0]}, note={key[1]}")
        

