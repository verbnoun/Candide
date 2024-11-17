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
    def __init__(self):
        self.routes = {}
        self.source_values = {}
        self.blocks = []
        self.current_key_press = None
        
    def start_key_press(self, note, channel):
        """Start tracking a new key press"""
        self.current_key_press = {
            'note': note,
            'channel': channel,
            'start_time': synthio.get_time_ms()
        }
        if Constants.DEBUG:
            print("\n[KEY PRESS] Started: Note {}, Channel {}".format(note, channel))
    
    def end_key_press(self):
        """End the current key press tracking"""
        if self.current_key_press and Constants.DEBUG:
            duration = synthio.get_time_ms() - self.current_key_press['start_time']
            print("[KEY PRESS] Ended: Note {}, Channel {}, Duration {}ms".format(
                self.current_key_press['note'], 
                self.current_key_press['channel'], 
                duration
            ))
        self.current_key_press = None
    
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
            
            if Constants.DEBUG:
                source_name = get_source_name(source)
                target_name = get_target_name(target)
                print("[MOD] Added Modulation Route: {} -> {}".format(source_name, target_name))
                print("[MOD]   Channel: {}, Amount: {}".format(channel, amount))
                if self.current_key_press:
                    print("[MOD]   Context: Note {}".format(self.current_key_press['note']))
    
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
        
        if Constants.DEBUG:
            source_name = get_source_name(source)
            print("\n[MOD] Source Value Updated: {}".format(source_name))
            print("[MOD]   Channel: {}, Value: {}".format(channel, value))
            if self.current_key_press:
                print("[MOD]   Context: Note {}".format(self.current_key_press['note']))
        
        # Update all routes using this source
        self._update_routes(source, channel)
    
    def get_target_value(self, target, channel=None):
        """Get current value for a modulation target"""
        total = 0.0
        matching_routes = []
        
        if Constants.DEBUG:
            target_name = get_target_name(target)
            print("\n[MOD] Calculating Target Value: {}".format(target_name))
            print("[MOD]   Channel: {}".format(channel))
            if self.current_key_press:
                print("[MOD]   Context: Note {}".format(self.current_key_press['note']))
        
        for key, route in self.routes.items():
            if key[1] == target and (channel is None or key[2] == channel):
                matching_routes.append(key)
                source = key[0]
                source_values = self.source_values.get(source, {})
                
                source_name = get_source_name(source)
                target_name = get_target_name(target)
                
                # Use 0.0 if no source value exists for this channel
                source_value = source_values.get(channel, 0.0)
                
                route_value = route.process(source_value)
                
                if Constants.DEBUG:
                    print("[MOD] Route Analysis:")
                    print("[MOD]   {} -> {}".format(source_name, target_name))
                    print("[MOD]   Source Value: {}".format(source_value))
                    print("[MOD]   Processed Value: {}".format(route_value))
                
                total += route_value
        
        if Constants.DEBUG:
            print("[MOD] Target Value Summary:")
            print("[MOD]   Total Value: {}".format(total))
            print("[MOD]   Matching Routes: {}".format(len(matching_routes)))
        
        return total
    
    def _update_routes(self, source, channel):
        """Update all routes for a given source/channel combination"""
        for key, route in self.routes.items():
            if key[0] == source and (key[2] is None or key[2] == channel):
                source_value = self.source_values[source][channel]
                route.update(source_value)

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
    
    def process(self, value):
        """Process value through route"""
        if value != self.last_value:
            self.needs_update = True
            
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
        
        return processed_value
    
    def update(self, value):
        """Update route with new value"""
        if value != self.last_value:
            self.last_value = value
            if self.math_block:
                self.math_block.a = value
            self.needs_update = False
        
        if Constants.DEBUG:
            source_name = get_source_name(self.source)
            target_name = get_target_name(self.target)
            print("[MOD] Route Updated:")
            print("[MOD]   {} -> {}".format(source_name, target_name))
            print("[MOD]   New Value: {}".format(value))

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
