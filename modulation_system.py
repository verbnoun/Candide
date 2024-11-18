import synthio
from fixed_point_math import FixedPoint
from synth_constants import Constants, ModSource, ModTarget

def get_source_name(source):
    """Convert source enum to human-readable name"""
    source_names = {
        ModSource.NONE: "None",
        ModSource.PRESSURE: "Pressure",
        ModSource.PITCH_BEND: "Pitch Bend",
        ModSource.TIMBRE: "Timbre",
        ModSource.LFO1: "LFO 1",
        ModSource.VELOCITY: "Velocity",
        ModSource.NOTE: "Note",
        ModSource.GATE: "Gate"
    }
    return source_names.get(source, f"Unknown Source ({source})")

def get_target_name(target):
    """Convert target enum to human-readable name"""
    target_names = {
        ModTarget.NONE: "None",
        ModTarget.FILTER_CUTOFF: "Filter Cutoff",
        ModTarget.FILTER_RESONANCE: "Filter Resonance",
        ModTarget.OSC_PITCH: "Oscillator Pitch",
        ModTarget.AMPLITUDE: "Amplitude",
        ModTarget.RING_FREQUENCY: "Ring Frequency",
        ModTarget.ENVELOPE_LEVEL: "Envelope Level"
    }
    return target_names.get(target, f"Unknown Target ({target})")

class LFOManager:
    """Config-driven LFO management system"""
    def __init__(self, mod_matrix, voice_manager, parameter_processor, synth):
        self.mod_matrix = mod_matrix
        self.voice_manager = voice_manager
        self.parameter_processor = parameter_processor
        self.synth = synth
        self.active_lfos = {}  # name: LFOConfig
        
        if Constants.DEBUG:
            print("[LFO] Manager initialized")
    
    def configure_from_instrument(self, config, synth):
        """Set up LFOs based on instrument configuration"""
        self.synth = synth
        
        if Constants.DEBUG:
            print("\n[LFO] Configuring from instrument config")
        
        # Clear existing LFOs
        for lfo in list(self.active_lfos.values()):
            if lfo.lfo_block in synth.blocks:
                synth.blocks.remove(lfo.lfo_block)
        self.active_lfos.clear()
        
        # Create new LFOs from config
        lfo_configs = config.get('lfo', {})
        for name, lfo_config in lfo_configs.items():
            if Constants.DEBUG:
                print(f"[LFO] Creating LFO '{name}':")
                print(f"      Rate: {lfo_config['rate']}Hz")
                print(f"      Shape: {lfo_config['shape']}")
                print(f"      Range: {lfo_config['min_value']} to {lfo_config['max_value']}")
            
            lfo = self.create_lfo(name, **lfo_config)
            if lfo and lfo.lfo_block:
                synth.blocks.append(lfo.lfo_block)
    
    def create_lfo(self, name, rate=1.0, shape='triangle', min_value=0.0, max_value=1.0, 
                  sync_to_gate=False):
        """Create new LFO with specified parameters"""
        if name in self.active_lfos:
            if Constants.DEBUG:
                print(f"[LFO] Updating existing LFO '{name}'")
            return self.active_lfos[name]
            
        if Constants.DEBUG:
            print(f"[LFO] Creating new LFO '{name}'")
            
        lfo_config = LFOConfig(name, rate, shape, min_value, max_value, sync_to_gate)
        self.active_lfos[name] = lfo_config
        return lfo_config
    
    def get_lfo(self, name):
        """Get existing LFO by name"""
        return self.active_lfos.get(name)
    
    def handle_gate(self, gate_type, state):
        """Handle gate events for synced LFOs"""
        if Constants.DEBUG:
            print(f"[LFO] Gate event: {gate_type} = {state}")
            
        for name, lfo in self.active_lfos.items():
            if lfo.sync_to_gate and gate_type == 'note_on' and state:
                if Constants.DEBUG:
                    print(f"[LFO] Retriggering '{name}' on gate")
                lfo.retrigger()

class LFOConfig:
    """LFO configuration with gate sync support"""
    def __init__(self, name, rate, shape, min_value, max_value, sync_to_gate=False):
        self.name = name
        self.rate = rate
        self.shape = shape
        self.min_value = min_value
        self.max_value = max_value
        self.sync_to_gate = sync_to_gate
        self.lfo_block = None
        self._create_lfo()
        
        if Constants.DEBUG:
            print(f"[LFO] Configured '{name}':")
            print(f"      Rate: {rate}Hz")
            print(f"      Shape: {shape}")
            print(f"      Range: {min_value} to {max_value}")
            print(f"      Gate Sync: {sync_to_gate}")
    
    def _create_lfo(self):
        """Create synthio.LFO block with current config"""
        import array
        from math import sin, pi
        
        if Constants.DEBUG:
            print(f"[LFO] Creating waveform for '{self.name}'")
        
        # Create waveform based on shape
        if self.shape == 'triangle':
            waveform = None  # Use synthio default
        elif self.shape == 'sine':
            # Create sine waveform
            samples = array.array('h', [0] * 256)
            for i in range(256):
                value = sin(2 * pi * i / 256)
                samples[i] = int(value * 32767)
            waveform = samples
        else:
            waveform = None  # Default to triangle
        
        scale = (self.max_value - self.min_value) / 2
        offset = self.min_value + scale
        
        self.lfo_block = synthio.LFO(
            waveform=waveform,
            rate=self.rate,
            scale=scale,
            offset=offset,
            phase_offset=0,
            once=False
        )
        
        if Constants.DEBUG:
            print(f"[LFO] Created LFO block for '{self.name}'")
    
    @property
    def value(self):
        """Get current LFO value"""
        return self.lfo_block.value if self.lfo_block else 0.0
    
    def retrigger(self):
        """Retrigger LFO from start"""
        if self.lfo_block:
            if Constants.DEBUG:
                print(f"[LFO] Retriggering '{self.name}'")
            self.lfo_block.retrigger()

class ModulationMatrix:
    """Modulation routing and processing system with gate support"""
    def __init__(self, voice_manager, parameter_processor, lfo_manager, synth, audio_output):
        self.voice_manager = voice_manager
        self.parameter_processor = parameter_processor
        self.lfo_manager = lfo_manager
        self.synth = synth
        self.audio_output = audio_output
        self.routes = {}  # (source, target, channel): ModulationRoute
        self.cc_routes = {}  # cc_number: ModulationRoute
        self.source_values = {}  # source: {channel: value}
        self.blocks = []  # Active synthio blocks (LFOs etc)
        self.gate_states = {}  # For tracking envelope gate states
        self.control_metadata = {}  # Store control object metadata
        
        if Constants.DEBUG:
            print("[MOD] Modulation matrix initialized")
    
    def _find_control_objects(self, config, path=''):
        """Recursively find all control objects in config"""
        controls = []
        
        if isinstance(config, dict):
            for key, value in config.items():
                new_path = f"{path}.{key}" if path else key
                
                if key == 'control' and isinstance(value, dict):
                    if all(k in value for k in ['cc', 'name', 'range']):
                        value['path'] = path  # Store path to parent
                        controls.append(value)
                else:
                    controls.extend(self._find_control_objects(value, new_path))
                    
        elif isinstance(config, list):
            for i, item in enumerate(config):
                new_path = f"{path}[{i}]"
                controls.extend(self._find_control_objects(item, new_path))
                
        return controls

    def configure_from_instrument(self, config):
        """Configure all modulation based on instrument config"""
        if Constants.DEBUG:
            print("\n[MOD] Configuring modulation matrix from instrument config")
            
        # Clear existing routes and metadata
        self.routes.clear()
        self.cc_routes.clear()
        self.blocks.clear()
        self.control_metadata.clear()
        
        # Find all control objects in config
        controls = self._find_control_objects(config)
        
        # Set up CC routes for control objects
        for control in controls:
            cc = control['cc']
            name = control['name']
            value_range = control['range']
            curve = control.get('curve', 'linear')
            path = control['path']
            
            if Constants.DEBUG:
                print(f"[MOD] Adding flexible CC route:")
                print(f"      CC: {cc}")
                print(f"      Name: {name}")
                print(f"      Path: {path}")
                print(f"      Range: {value_range['min']} to {value_range['max']}")
                print(f"      Curve: {curve}")
            
            # Store metadata for value scaling
            self.control_metadata[cc] = {
                'name': name,
                'path': path,
                'range': value_range,
                'curve': curve
            }
            
            # Create route with appropriate curve
            self.add_cc_route(cc, ModTarget.NONE, 1.0, curve)
        
        # Add standard modulation routes from config
        for route in config.get('modulation', []):
            source = route['source']
            target = route['target']
            amount = route.get('amount', 1.0)
            curve = route.get('curve', 'linear')
            
            if Constants.DEBUG:
                print(f"[MOD] Adding route: {get_source_name(source)} -> {get_target_name(target)}")
                print(f"      Amount: {amount:.3f}, Curve: {curve}")
                
            self.add_route(source, target, amount, curve=curve)
            
        # Add legacy CC routes from config
        for cc_number, route_config in config.get('cc_routing', {}).items():
            target = route_config['target']
            amount = route_config.get('amount', 1.0)
            curve = route_config.get('curve', 'linear')
            description = route_config.get('description', '')
            
            if Constants.DEBUG:
                print(f"[MOD] Adding legacy CC route: CC {cc_number} -> {get_target_name(target)}")
                print(f"      Amount: {amount:.3f}, Curve: {curve}")
                if description:
                    print(f"      Description: {description}")
                
            self.add_cc_route(int(cc_number), target, amount, curve)
    
    def scale_cc_value(self, value, control):
        """Scale normalized CC value using control's range and curve"""
        if not control or 'range' not in control:
            return value
            
        value_range = control['range']
        min_val = value_range['min']
        max_val = value_range['max']
        curve = control.get('curve', 'linear')
        
        # Get route to use its curve processing
        route = ModulationRoute(ModSource.NONE, ModTarget.NONE, max_val - min_val, curve)
        
        # Process through curve
        scaled = route.process(value)
        
        # Scale to range
        return min_val + (FixedPoint.to_float(scaled) * (max_val - min_val))
    
    def add_route(self, source, target, amount=1.0, channel=None, curve='linear'):
        """Add a modulation route with optional per-channel routing"""
        key = (source, target, channel)
        if key not in self.routes:
            route = ModulationRoute(source, target, amount, curve)
            self.routes[key] = route
            
            if route.math_block:
                self.blocks.append(route.math_block)
                
            if Constants.DEBUG:
                print(f"[MOD] Route added:")
                print(f"      Source: {get_source_name(source)}")
                print(f"      Target: {get_target_name(target)}")
                print(f"      Channel: {channel if channel is not None else 'all'}")
                print(f"      Amount: {amount:.3f}")
    
    def add_cc_route(self, cc_number, target, amount=1.0, curve='linear'):
        """Add a CC-specific modulation route"""
        route = ModulationRoute(ModSource.NONE, target, amount, curve)
        self.cc_routes[cc_number] = route
        
        if route.math_block:
            self.blocks.append(route.math_block)
            
        if Constants.DEBUG:
            print(f"[MOD] CC route added:")
            print(f"      CC: {cc_number}")
            print(f"      Target: {get_target_name(target)}")
            print(f"      Amount: {amount:.3f}")
            print(f"      Curve: {curve}")
    
    def process_cc(self, cc_number, value, channel):
        """Process CC value if it has a configured route"""
        if cc_number not in self.cc_routes:
            if Constants.DEBUG:
                print(f"[MOD] Ignoring unrouted CC {cc_number}")
            return  # Ignore CCs that aren't configured
            
        route = self.cc_routes[cc_number]
        normalized_value = value / 127.0  # Convert MIDI CC range to 0-1
        
        if Constants.DEBUG:
            print(f"[MOD] Processing CC {cc_number}:")
            print(f"      Value: {value}")
        
        # Check if this CC has control metadata
        if cc_number in self.control_metadata:
            control = self.control_metadata[cc_number]
            scaled_value = self.scale_cc_value(normalized_value, control)
            
            if Constants.DEBUG:
                print(f"      Name: {control['name']}")
                print(f"      Path: {control['path']}")
                print(f"      Scaled: {scaled_value:.3f}")
                
            return scaled_value
        
        # Legacy CC processing
        if route.target != ModTarget.NONE:
            if Constants.DEBUG:
                print(f"      Target: {get_target_name(route.target)}")
            
            # Process through route and update target
            processed = route.process(normalized_value)
            self.set_target_value(route.target, channel, processed)
            return processed
            
    def remove_route(self, source, target, channel=None):
        """Remove a modulation route"""
        key = (source, target, channel)
        if key in self.routes:
            route = self.routes[key]
            if route.math_block in self.blocks:
                self.blocks.remove(route.math_block)
            del self.routes[key]
            
            if Constants.DEBUG:
                print(f"[MOD] Route removed: {get_source_name(source)} -> {get_target_name(target)}")
    
    def set_gate_state(self, channel, gate_type, state):
        """Set envelope gate state"""
        if Constants.DEBUG:
            print(f"[MOD] Gate state change - Ch:{channel} {gate_type}={state}")
            
        if channel not in self.gate_states:
            self.gate_states[channel] = {}
        self.gate_states[channel][gate_type] = state
        
        # Update gate source value
        self.set_source_value(ModSource.GATE, channel, 1.0 if state else 0.0)
    
    def set_source_value(self, source, channel, value):
        """Set value for a modulation source"""
        if source not in self.source_values:
            self.source_values[source] = {}
            
        # Convert to fixed point
        fixed_value = FixedPoint.from_float(value)
        self.source_values[source][channel] = fixed_value
        
        if Constants.DEBUG:
            last_value = getattr(self, '_last_logged_values', {}).get((source, channel))
            current_value = FixedPoint.to_float(fixed_value)
            if last_value is None or abs(current_value - last_value) > 0.01:
                print(f"[MOD] Source value updated:")
                print(f"      Source: {get_source_name(source)}")
                print(f"      Channel: {channel}")
                print(f"      Value: {current_value:.3f}")
                if not hasattr(self, '_last_logged_values'):
                    self._last_logged_values = {}
                self._last_logged_values[(source, channel)] = current_value
    
    def get_target_value(self, target, channel):
        """Get current value for a modulation target"""
        if Constants.DEBUG:
            print(f"[MOD] Getting target value:")
            print(f"      Target: {get_target_name(target)}")
            print(f"      Channel: {channel}")
        
        result = FixedPoint.ZERO
        
        for key, route in self.routes.items():
            source, route_target, route_channel = key
            
            # Skip if not matching target or channel
            if route_target != target:
                continue
            if route_channel is not None and route_channel != channel:
                continue
                
            # Get source value
            source_value = self.source_values.get(source, {}).get(channel, FixedPoint.ZERO)
            if source_value == FixedPoint.ZERO:
                continue
                
            # Process value through route
            processed = route.process(FixedPoint.to_float(source_value))
            
            # Combine based on target type
            if target == ModTarget.AMPLITUDE:
                # Multiplicative combining for amplitude
                if result == FixedPoint.ZERO:
                    result = processed
                else:
                    result = FixedPoint.multiply(result, processed)
            else:
                # Additive combining for other targets
                result += processed
            
            if Constants.DEBUG:
                print(f"[MOD]       {get_source_name(source)}: {FixedPoint.to_float(processed):.3f}")
        
        if Constants.DEBUG:
            print(f"[MOD]       Final: {FixedPoint.to_float(result):.3f}")
        
        return result

class ModulationRoute:
    """Single modulation routing with processing"""
    def __init__(self, source, target, amount=1.0, curve='linear'):
        self.source = source
        self.target = target
        self.amount = FixedPoint.from_float(amount)
        self.curve = curve
        self.math_block = None
        self.last_value = None
        self.needs_update = True
        
        if Constants.DEBUG:
            print(f"[MOD] Creating route:")
            print(f"      Source: {get_source_name(source)}")
            print(f"      Target: {get_target_name(target)}")
            print(f"      Amount: {amount:.3f}")
            print(f"      Curve: {curve}")
        
        if self.needs_math_block():
            self.create_math_block()
            
    def needs_math_block(self):
        """Determine if this route needs a synthio.Math block"""
        return self.target in (
            ModTarget.FILTER_CUTOFF,
            ModTarget.FILTER_RESONANCE,
            ModTarget.RING_FREQUENCY,
            ModTarget.ENVELOPE_LEVEL
        )
    
    def create_math_block(self):
        """Create appropriate synthio.Math block for this route"""
        if Constants.DEBUG:
            print(f"[MOD] Creating math block for {get_source_name(self.source)} -> {get_target_name(self.target)}")
            
        if self.target == ModTarget.FILTER_CUTOFF:
            # Exponential scaling for filter frequency
            self.math_block = synthio.Math(
                synthio.MathOperation.SCALE_OFFSET,
                0.0,  # will be updated
                FixedPoint.to_float(self.amount),
                1.0
            )
        elif self.target == ModTarget.ENVELOPE_LEVEL:
            # Special handling for envelope levels
            self.math_block = synthio.Math(
                synthio.MathOperation.CONSTRAINED_LERP,
                0.0,  # current level
                1.0,  # target level
                FixedPoint.to_float(self.amount)  # interpolation amount
            )
        else:
            self.math_block = synthio.Math(
                synthio.MathOperation.PRODUCT,
                0.0,  # will be updated
                FixedPoint.to_float(self.amount)
            )
    
    def process(self, value):
        """Process value through route with fixed-point math"""
        if value != self.last_value:
            self.needs_update = True
            self.last_value = value
            
            # Convert to fixed point for processing
            fixed_value = FixedPoint.from_float(value)
            
            # Apply curve
            if self.curve == 'exponential':
                processed = self._exp_curve(fixed_value)
            elif self.curve == 'logarithmic':
                processed = self._log_curve(fixed_value)
            elif self.curve == 's_curve':
                processed = self._s_curve(fixed_value)
            else:  # linear
                processed = FixedPoint.multiply(fixed_value, self.amount)
            
            if self.math_block:
                self.math_block.a = FixedPoint.to_float(processed)
                result = FixedPoint.from_float(self.math_block.value)
            else:
                result = processed
                
            if Constants.DEBUG:
                print(f"[MOD] Processing value:")
                print(f"      Route: {get_source_name(self.source)} -> {get_target_name(self.target)}")
                print(f"      Input: {value:.3f}")
                print(f"      Output: {FixedPoint.to_float(result):.3f}")
                
            return result
            
        return self.last_value
        
    def _exp_curve(self, value):
        """Exponential curve with fixed-point math"""
        # x^2 exponential approximation
        scaled = FixedPoint.multiply(value, FixedPoint.from_float(4.0))
        return FixedPoint.multiply(scaled, scaled)
        
    def _log_curve(self, value):
        """Logarithmic curve with fixed-point math"""
        # 1-(1-x)^2 logarithmic approximation
        inv = FixedPoint.ONE - value
        squared = FixedPoint.multiply(inv, inv)
        return FixedPoint.multiply(FixedPoint.ONE - squared, self.amount)
        
    def _s_curve(self, value):
        """S-curve (sigmoid) with fixed-point math"""
        # Smooth step function: 3x^2 - 2x^3
        squared = FixedPoint.multiply(value, value)
        cubed = FixedPoint.multiply(squared, value)
        
        three_squared = FixedPoint.multiply(squared, FixedPoint.from_float(3.0))
        two_cubed = FixedPoint.multiply(cubed, FixedPoint.from_float(2.0))
        
        return FixedPoint.multiply(three_squared - two_cubed, self.amount)
