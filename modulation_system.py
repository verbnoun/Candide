import synthio
from fixed_point_math import FixedPoint
from synth_constants import Constants, ModSource, ModTarget

class ModulationMatrix:
    """Routes modulation sources to targets using synthio.Math blocks"""
    def __init__(self):
        self.routes = {}  # (source, target): ModulationRoute
        self.source_values = {}  # source: {channel: value}
        self.blocks = []  # Active synthio.Math blocks
        
    def add_route(self, source, target, amount=1.0, channel=None):
        """Add a modulation route with optional per-channel routing"""
        key = (source, target, channel)
        if key not in self.routes:
            route = ModulationRoute(source, target, amount, channel)
            self.routes[key] = route
            # Create synthio.Math block if needed
            if route.needs_math_block():
                route.create_math_block()
                self.blocks.append(route.math_block)
    
    def remove_route(self, source, target, channel=None):
        """Remove a modulation route"""
        key = (source, target, channel)
        if key in self.routes:
            route = self.routes[key]
            if route.math_block and route.math_block in self.blocks:
                self.blocks.remove(route.math_block)
            del self.routes[key]
    
    def set_source_value(self, source, channel, value):
        """Set value for a modulation source"""
        if source not in self.source_values:
            self.source_values[source] = {}
        self.source_values[source][channel] = value
        
        # Update all routes using this source
        self._update_routes(source, channel)
    
    def get_target_value(self, target, channel=None):
        """Get current value for a modulation target"""
        total = 0.0
        for key, route in self.routes.items():
            if key[1] == target and (channel is None or key[2] == channel):
                source_value = self.source_values.get(key[0], {}).get(channel, 0.0)
                total += route.process(source_value)
        return total
    
    def _update_routes(self, source, channel):
        """Update all routes for a given source/channel combination"""
        for key, route in self.routes.items():
            if key[0] == source and (key[2] is None or key[2] == channel):
                source_value = self.source_values[source][channel]
                route.update(source_value)

class ModulationRoute:
    """Handles individual modulation routing with synthio.Math support"""
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
    
    def process(self, value):
        """Process value through route"""
        if value != self.last_value:
            self.needs_update = True
            
        if self.math_block:
            self.math_block.a = value
            return self.math_block.value
        return value * self.amount
    
    def update(self, value):
        """Update route with new value"""
        if value != self.last_value:
            self.last_value = value
            if self.math_block:
                self.math_block.a = value
            self.needs_update = False

class LFOManager:
    """Manages LFO creation and routing"""
    def __init__(self, mod_matrix):
        self.mod_matrix = mod_matrix
        self.lfos = {}  # name: LFOConfig
        self.global_lfos = []  # LFOs that should always run
        
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
    """Configuration and state for a single LFO"""
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
