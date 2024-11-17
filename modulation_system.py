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
        ModSource.NOTE: "Note"
    }
    if source in source_names:
        return source_names[source]
    return "Unknown Source ({})".format(source)

def get_target_name(target):
    """Convert target enum to human-readable name"""
    target_names = {
        ModTarget.NONE: "None",
        ModTarget.FILTER_CUTOFF: "Filter Cutoff",
        ModTarget.FILTER_RESONANCE: "Filter Resonance",
        ModTarget.OSC_PITCH: "Oscillator Pitch",
        ModTarget.AMPLITUDE: "Amplitude",
        ModTarget.RING_FREQUENCY: "Ring Frequency"
    }
    if target in target_names:
        return target_names[target]
    return "Unknown Target ({})".format(target)

class ModulationMatrix:
    """Modulation routing and processing system for MPE synthesis.
    
    Handles:
    - Base values (note, velocity) 
    - Control values (pressure, timbre, bend)
    - LFO modulation
    - Proper value persistence
    - Per-channel modulation
    - Multi-source modulation combining
    
    Signal flow:
    1. Base values set via set_source_value()
    2. Control values update via set_source_value()
    3. Routes process values through get_target_value()
    4. Values combined according to target type
    """
    def __init__(self):
        self.routes = {}  # (source, target, channel): ModulationRoute
        self.source_values = {}  # source: {channel: value}
        self.blocks = []  # Active synth blocks (LFOs etc)
        self.base_values = {}  # (source, channel): value - For persistent values like note freq
        self._debug_last_values = {}  # For detecting significant changes in debug logging
        
    def add_route(self, source, target, amount=1.0, channel=None):
        """Add a modulation route with optional per-channel routing"""
        key = (source, target, channel)
        if key not in self.routes:
            route = ModulationRoute(source, target, amount, channel)
            self.routes[key] = route
            
            # Create math block if needed
            if route.needs_math_block():
                route.create_math_block()
                self.blocks.append(route.math_block)
            
            if Constants.DEBUG:
                print("[MOD] Added Route: {} -> {} (ch={}, amt={:.3f})".format(
                    get_source_name(source),
                    get_target_name(target),
                    channel if channel is not None else 'all',
                    amount
                ))
                
    def remove_route(self, source, target, channel=None):
        """Remove a modulation route"""
        key = (source, target, channel)
        if key in self.routes:
            route = self.routes[key]
            if route.math_block and route.math_block in self.blocks:
                self.blocks.remove(route.math_block)
            del self.routes[key]
            
            if Constants.DEBUG:
                print("[MOD] Removed Route: {} -> {} (ch={})".format(
                    get_source_name(source),
                    get_target_name(target),
                    channel if channel is not None else 'all'
                ))
    
    def set_source_value(self, source, channel, value):
        """Set value for a modulation source.
        
        Handles both persistent base values (NOTE, VELOCITY)
        and continuous control values (PRESSURE, TIMBRE, PITCH_BEND)
        """
        # Store value
        if source not in self.source_values:
            self.source_values[source] = {}
        self.source_values[source][channel] = value
        
        # Store base values separately for persistence
        if source in (ModSource.NOTE, ModSource.VELOCITY):
            self.base_values[(source, channel)] = value
        
        # Debug logging with change detection
        if Constants.DEBUG:
            last_value = self._debug_last_values.get((source, channel))
            if last_value is None or abs(value - last_value) > 0.001:
                print("\n[MOD] Source Value Updated: {}".format(get_source_name(source)))
                print("[MOD]   Channel: {}, Value: {:.6f}".format(channel, value))
                if source == ModSource.VELOCITY:
                    print("[DEBUG] Velocity value for channel {}: {:.6f}".format(channel, value))
                self._debug_last_values[(source, channel)] = value
        
        # Process routes for control sources
        if source not in (ModSource.NOTE, ModSource.VELOCITY):
            self._update_control_routes(source, channel)
            
    def get_target_value(self, target, channel):
        """Get current value for a modulation target.
        
        Combines values based on target type:
        - OSC_PITCH: Base note + pitch bend
        - AMPLITUDE: Base velocity * pressure
        - FILTER_*/Others: Sum of modulations
        """
        if Constants.DEBUG:
            print("\n[MOD] Getting Target: {} (ch={})".format(
                get_target_name(target), channel))
        
        # Get base value first
        base_value = 0.0
        if target == ModTarget.OSC_PITCH:
            base_value = self.base_values.get((ModSource.NOTE, channel), 0.0)
        elif target == ModTarget.AMPLITUDE:
            base_value = self.base_values.get((ModSource.VELOCITY, channel), 1.0)
            
        # Initialize accumulators for different combination types
        multiplicative_mod = 1.0  # For multiplication (e.g. amplitude)
        additive_mod = 0.0  # For addition (e.g. pitch bend)
        greatest_mod = 0.0  # For maximum value (e.g. filter)
        
        # Process all routes targeting this parameter
        for key, route in self.routes.items():
            source, route_target, route_channel = key
            
            # Skip if not matching target or channel
            if route_target != target:
                continue
            if route_channel is not None and route_channel != channel:
                continue
                
            # Get source value for this route
            source_value = self._get_source_value(source, channel)
            if source_value == 0.0:
                continue
                
            # Process value through route
            mod_value = route.process(source_value, context="get_target_value")
            
            # Combine based on target type
            if target == ModTarget.AMPLITUDE:
                multiplicative_mod *= (1.0 + mod_value)  # Pressure increases amplitude
            elif target == ModTarget.OSC_PITCH:
                additive_mod += mod_value  # Pitch bend adds to base
            else:  # FILTER_CUTOFF, FILTER_RESONANCE, etc
                greatest_mod = max(greatest_mod, mod_value)
                
            if Constants.DEBUG:
                print("[MOD]   Route {} -> {}: {:.6f}".format(
                    get_source_name(source),
                    get_target_name(target),
                    mod_value
                ))
        
        # Combine base and modulation
        final_value = base_value
        if target == ModTarget.AMPLITUDE:
            final_value *= multiplicative_mod
        elif target == ModTarget.OSC_PITCH:
            final_value += additive_mod
        else:
            final_value = greatest_mod
            
        if Constants.DEBUG:
            print("[MOD]   Final Value: {:.6f} (base={:.6f})".format(final_value, base_value))
            
        return final_value
        
    def _get_source_value(self, source, channel):
        """Get current value for a source, including base values"""
        # Check base values first for persistent sources
        if (source, channel) in self.base_values:
            return self.base_values[(source, channel)]
            
        # Otherwise get from source values
        return self.source_values.get(source, {}).get(channel, 0.0)
        
    def _update_control_routes(self, source, channel):
        """Update routes for control sources (pressure, timbre, pitch bend, LFOs)"""
        source_value = self.source_values[source][channel]
        
        for key, route in list(self.routes.items()):
            route_source, _, route_channel = key
            
            # Only process matching source and channel
            if route_source != source:
                continue
            if route_channel is not None and route_channel != channel:
                continue
                
            if Constants.DEBUG:
                print("[MOD] Updating Control Route:")
                print("[MOD]   {} -> {} (ch={})".format(
                    get_source_name(source),
                    get_target_name(route.target),
                    channel
                ))
                
            try:
                route.process(source_value, context="_update_control_routes")
            except Exception as e:
                print(f"[ERROR] Route processing failed: {e}")
                print(f"Source: {source}, Channel: {channel}, Value: {source_value}")
                
    def cleanup(self):
        """Remove all routes and clear state"""
        self.routes.clear()
        self.source_values.clear()
        self.base_values.clear()
        self.blocks.clear()
        self._debug_last_values.clear()

class ModulationRoute:
    def __init__(self, source, target, amount=1.0, channel=None):
        self.source = source
        self.target = target
        self.amount = amount
        self.channel = channel
        self.math_block = None
        self.last_value = None
        self.needs_update = False
        
    def needs_math_block(self):
        """Determine if this route needs a synthio.Math block"""
        return self.target in (
            ModTarget.FILTER_CUTOFF,
            ModTarget.FILTER_RESONANCE,
            ModTarget.RING_FREQUENCY
        )
    
    def create_math_block(self):
        """Create appropriate synthio.Math block for this route"""
        if self.target == ModTarget.FILTER_CUTOFF:
            # Exponential scaling for filter frequency
            self.math_block = synthio.Math(
                synthio.MathOperation.SCALE_OFFSET,
                0.0,  # will be updated
                self.amount,
                1.0
            )
        elif self.target == ModTarget.FILTER_RESONANCE:
            # Constrained linear scaling for resonance
            self.math_block = synthio.Math(
                synthio.MathOperation.CONSTRAINED_LERP,
                0.0,  # will be updated
                self.amount,
                1.0
            )
        else:
            self.math_block = synthio.Math(
                synthio.MathOperation.PRODUCT,
                0.0,  # will be updated
                self.amount
            )
        
        if Constants.DEBUG:
            source_name = get_source_name(self.source)
            target_name = get_target_name(self.target)
            print("[MOD] Created Math Block: {} -> {}".format(source_name, target_name))
    
    def process(self, value, context="unknown"):
        """Process value through route"""
        if value != self.last_value:
            self.needs_update = True
            self.last_value = value
            
            if self.math_block:
                self.math_block.a = value
                processed_value = self.math_block.value
            else:
                processed_value = value * self.amount
            
            if Constants.DEBUG:
                source_name = get_source_name(self.source)
                target_name = get_target_name(self.target)
                print("[MOD] Route Processing:")
                print("[MOD]   {} -> {}".format(source_name, target_name))
                print("[MOD]   Input Value: {}".format(value))
                print("[MOD]   Processed Value: {}".format(processed_value))
                print("[DEBUG] Applied by process method in ModulationRoute class, called from {}".format(context))
            
            return processed_value
        
        # If value hasn't changed, return last processed value
        return self.last_value * self.amount if not self.math_block else self.math_block.value

class LFOManager:
    def __init__(self, mod_matrix):
        self.mod_matrix = mod_matrix
        self.lfos = {}
        self.global_lfos = []
        
    def create_lfo(self, name, rate=1.0, shape='triangle', min_value=0.0, max_value=1.0):
        """Create new LFO with given parameters"""
        if name in self.lfos:
            return self.lfos[name]
            
        lfo_config = LFOConfig(name, rate, shape, min_value, max_value)
        self.lfos[name] = lfo_config
        return lfo_config
    
    def create_global_lfo(self, **kwargs):
        """Create LFO that will always run"""
        lfo = self.create_lfo(**kwargs)
        self.global_lfos.append(lfo)
        return lfo
    
    def get_lfo(self, name):
        """Get existing LFO config"""
        return self.lfos.get(name)
        
    def attach_to_synth(self, synth):
        """Attach all global LFOs to synth"""
        for lfo in self.global_lfos:
            if lfo.lfo_block not in synth.blocks:
                synth.blocks.append(lfo.lfo_block)

class LFOConfig:
    def __init__(self, name, rate, shape, min_value, max_value):
        self.name = name
        self.rate = rate
        self.shape = shape
        self.min_value = min_value
        self.max_value = max_value
        self.lfo_block = None
        self._create_lfo()
    
    def _create_lfo(self):
        """Create synthio.LFO block with current config"""
        import array
        from math import sin, pi
        
        # Create waveform based on shape
        if self.shape == 'triangle':
            # Use default synthio triangle
            waveform = None
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
    
    @property
    def value(self):
        """Get current LFO value"""
        return self.lfo_block.value if self.lfo_block else 0.0
    
    def retrigger(self):
        """Retrigger LFO from start"""
        if self.lfo_block:
            self.lfo_block.retrigger()
