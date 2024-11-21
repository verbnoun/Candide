"""
Router Module

Transforms MIDI messages into data streams based on instrument configuration.
Each route defined in config creates a mapping from MIDI input to module parameter.
No knowledge of voice implementation - just creates normalized parameter streams.
"""

import sys
from fixed_point_math import FixedPoint
from constants import ROUTER_DEBUG

def _log(message, module="ROUTER"):
    """Conditional logging function that respects ROUTER_DEBUG flag."""
    if not ROUTER_DEBUG:
        return
        
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    GRAY = "\033[90m"
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        # Format dict output for readability
        formatted = "\n"
        for k, v in message.items():
            formatted += f"  {k}: {v}\n"
        print(f"{BLUE}[{module}]{formatted}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message):
            color = RED
        elif "[SUCCESS]" in str(message):
            color = GREEN
        elif "[WARNING]" in str(message):
            color = YELLOW
        elif "rejected" in str(message).lower():
            color = GRAY
        else:
            color = BLUE
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class RouteCache:
    """Stores compiled routes from config"""
    def __init__(self):
        self.midi_whitelist = {}
        self.routes = {}
        
    def add_route(self, source_type, source_id, route_info):
        """Add a route mapping"""
        key = f"{source_type}.{source_id}"
        self.routes[key] = route_info
        _log(f"Added route: {key} -> {route_info}")
        
    def get_route(self, source_type, source_id):
        """Get route info if it exists"""
        key = f"{source_type}.{source_id}"
        route = self.routes.get(key)
        if route:
            _log(f"Found route for {key}")
        return route
        
    def set_whitelist(self, whitelist):
        """Set MIDI message whitelist"""
        self.midi_whitelist = whitelist
        _log(f"Set MIDI whitelist: {whitelist}")

    def is_whitelisted(self, msg_type, attribute=None):
        """Check if message type and attribute are whitelisted"""
        if msg_type not in self.midi_whitelist:
            return False
        if attribute is None:
            return True
        return attribute in self.midi_whitelist[msg_type]

class ModuleRouter:
    """Base router class"""
    def __init__(self):
        self.module_name = None
        self.route_cache = RouteCache()
        
    def compile_routes(self, config):
        """Extract and compile routes from config"""
        if not config:
            _log(f"[WARNING] No config provided for {self.module_name}")
            return
            
        _log(f"Compiling routes for {self.module_name}")
        
        # Store whitelist
        self.route_cache.set_whitelist(config.get('midi_whitelist', {}))
        
        # Get module config
        module_config = config.get(self.module_name, {})
        if not module_config or 'parameters' not in module_config:
            _log(f"[WARNING] No valid config found for {self.module_name}")
            return
            
        # Compile routes for each parameter
        for param_name, param_config in module_config['parameters'].items():
            if 'sources' not in param_config:
                continue
                
            for source in param_config['sources']:
                source_type = source.get('type')
                if source_type == 'per_key':
                    self._compile_per_key_route(source, param_name, param_config)
                elif source_type == 'cc':
                    self._compile_cc_route(source, param_name, param_config)
                    
        _log(f"Route compilation complete for {self.module_name}")
        
    def _compile_per_key_route(self, source, param_name, param_config):
        """Compile per-key route"""
        route_info = {
            'module': self.module_name,
            'parameter': param_name,
            'per_key': True,
            'transform': source.get('transform'),
            'range': param_config.get('range', {}),
            'curve': param_config.get('curve', 'linear')
        }
        self.route_cache.add_route('per_key', source['attribute'], route_info)
        
    def _compile_cc_route(self, source, param_name, param_config):
        """Compile CC route"""
        route_info = {
            'module': self.module_name,
            'parameter': param_name,
            'per_key': False,
            'range': param_config.get('range', {}),
            'curve': param_config.get('curve', 'linear')
        }
        self.route_cache.add_route('cc', source['number'], route_info)
        
    def transform_value(self, value, route_info):
        """Transform value based on route configuration"""
        if not isinstance(value, FixedPoint):
            value = FixedPoint.from_float(float(value))
            
        if 'transform' in route_info:
            if route_info['transform'] == 'midi_to_frequency':
                return value  # Pass through for voice to handle
                
        if 'range' in route_info:
            r = route_info['range']
            value = self._apply_range_transform(value, r)
            
        if 'curve' in route_info:
            value = self._apply_curve_transform(value, route_info['curve'])
            
        return value
        
    def _apply_range_transform(self, value, range_config):
        """Apply range mapping"""
        in_min = range_config.get('in_min', 0)
        in_max = range_config.get('in_max', 127)
        out_min = FixedPoint.from_float(range_config.get('out_min', 0.0))
        out_max = FixedPoint.from_float(range_config.get('out_max', 1.0))
        
        if in_max != in_min:
            value = FixedPoint.from_float(
                (float(value) - in_min) / (in_max - in_min)
            )
            
        range_size = out_max - out_min
        return out_min + FixedPoint.multiply(value, range_size)
        
    def _apply_curve_transform(self, value, curve_type):
        """Apply curve transformation"""
        if curve_type == 'exponential':
            return FixedPoint.multiply(value, value)
        elif curve_type == 'logarithmic':
            return FixedPoint.ONE - FixedPoint.multiply(
                FixedPoint.ONE - value,
                FixedPoint.ONE - value
            )
        elif curve_type == 's_curve':
            x2 = FixedPoint.multiply(value, value)
            x3 = FixedPoint.multiply(x2, value)
            return FixedPoint.multiply(x2, FixedPoint.from_float(3.0)) - \
                   FixedPoint.multiply(x3, FixedPoint.from_float(2.0))
        return value
        
    def process_message(self, message, voice_manager):
        """Transform MIDI message into parameter stream"""
        msg_type = message.get('type')
        channel = message.get('channel')
        data = message.get('data', {})
        
        _log(f"Processing {msg_type} message on channel {channel}: {data}")
        
        # Check whitelist first
        if msg_type == 'cc':
            if not self.route_cache.is_whitelisted('cc', data.get('number')):
                _log(f"Message rejected: CC {data.get('number')} not in whitelist")
                return None
        elif msg_type in ['note_on', 'note_off']:
            attribute = data.get('attribute')
            if not self.route_cache.is_whitelisted(msg_type, attribute):
                _log(f"Message rejected: {msg_type} attribute '{attribute}' not in whitelist")
                return None
        else:
            _log(f"Message rejected: message type '{msg_type}' not in whitelist")
            return None
        
        # Get route for this message
        if msg_type == 'cc':
            route = self.route_cache.get_route('cc', data.get('number'))
            if route:
                value = self.transform_value(data.get('value', 0), route)
                result = {
                    'channel': None,  # Global parameter
                    'target': {
                        'module': route['module'],
                        'parameter': route['parameter']
                    },
                    'value': value
                }
                _log(f"Routed CC message: {result}")
                return result
            else:
                _log(f"Message rejected: no route found for CC number {data.get('number')}")
                
        elif msg_type in ['note_on', 'note_off']:
            route = self.route_cache.get_route('per_key', data.get('attribute'))
            if route:
                value = self.transform_value(data.get('value', 0), route)
                result = {
                    'channel': channel,  # Per-key requires channel
                    'target': {
                        'module': route['module'],
                        'parameter': route['parameter']
                    },
                    'value': value
                }
                _log(f"Routed {msg_type} message: {result}")
                return result
            else:
                _log(f"Message rejected: no route found for {msg_type} attribute {data.get('attribute')}")
                
        return None

class OscillatorRouter(ModuleRouter):
    """Routes messages to oscillator parameters"""
    def __init__(self):
        super().__init__()
        self.module_name = "oscillator"

class FilterRouter(ModuleRouter):
    """Routes messages to filter parameters"""
    def __init__(self):
        super().__init__()
        self.module_name = "filter"

class AmplifierRouter(ModuleRouter):
    """Routes messages to amplifier parameters"""
    def __init__(self):
        super().__init__()
        self.module_name = "amplifier"
