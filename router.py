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
    LIGHT_BLUE = "\033[94m"
    GRAY = "\033[90m"
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        # Format dict output for readability
        formatted = "\n"
        for k, v in message.items():
            formatted += f"  {k}: {v}\n"
        print(f"{LIGHT_BLUE}[{module}]{formatted}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message):
            color = RED
        elif "[REJECTED]" in str(message):
            color = BLUE
        else:
            color = LIGHT_BLUE
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

class ChannelBuffer:
    """Simple buffer for channel messages with max length"""
    def __init__(self, max_len=10):
        self.buffer = []
        self.max_len = max_len
    
    def append(self, item):
        """Add item to buffer, removing oldest if full"""
        if len(self.buffer) >= self.max_len:
            self.buffer.pop(0)
        self.buffer.append(item)
    
    def clear(self):
        """Clear the buffer"""
        self.buffer = []

class ModuleRouter:
    """Base router class"""
    def __init__(self):
        self.module_name = None
        self.route_cache = RouteCache()
        # Buffer for recent MPE messages per channel
        self.channel_buffers = {}
        
    def _get_channel_buffer(self, channel):
        """Get or create buffer for a channel"""
        if channel not in self.channel_buffers:
            self.channel_buffers[channel] = ChannelBuffer()
        return self.channel_buffers[channel]
        
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
            
        # Compile routes by recursively traversing parameter structure
        self._compile_parameter_routes(module_config['parameters'])
                    
        _log(f"Route compilation complete for {self.module_name}")
        
    def _compile_parameter_routes(self, params, param_path=''):
        """Recursively compile routes from nested parameter structure"""
        for param_name, param_config in params.items():
            # Build full parameter path
            full_path = f"{param_path}.{param_name}" if param_path else param_name
            
            if isinstance(param_config, dict):
                # Check for sources at this level
                if 'sources' in param_config:
                    for source in param_config['sources']:
                        source_type = source.get('type')
                        if source_type == 'per_key':
                            self._compile_per_key_route(source, full_path, param_config)
                        elif source_type == 'cc':
                            self._compile_cc_route(source, full_path, param_config)
                            
                # Recurse into nested parameters (like envelope stages)
                if 'parameters' in param_config:
                    self._compile_parameter_routes(param_config['parameters'], full_path)
                    
                # Handle envelope structure
                for key in ['attack', 'decay', 'sustain', 'release']:
                    if key in param_config:
                        stage_path = f"{full_path}.{key}"
                        self._compile_parameter_routes(param_config[key], stage_path)
        
    def _compile_per_key_route(self, source, param_path, param_config):
        """Compile per-key route with full parameter path"""
        route_info = {
            'module': self.module_name,
            'parameter': param_path,
            'per_key': True,
            'transform': source.get('transform'),
            'range': param_config.get('range', {}),
            'curve': param_config.get('curve', 'linear')
        }
        self.route_cache.add_route('per_key', source['attribute'], route_info)
        
    def _compile_cc_route(self, source, param_path, param_config):
        """Compile CC route with full parameter path"""
        route_info = {
            'module': self.module_name,
            'parameter': param_path,
            'per_key': False,
            'range': param_config.get('range', {}),
            'curve': param_config.get('curve', 'linear')
        }
        self.route_cache.add_route('cc', source['number'], route_info)
        
    def transform_value(self, value, route_info):
        """Transform value based on route configuration"""
        if not isinstance(value, (int, float)):
            return 0
            
        # First normalize the input value to 0-1 range
        normalized = FixedPoint.normalize_midi_value(value)
            
        # Apply range mapping if specified
        if 'range' in route_info:
            r = route_info['range']
            if 'min' in r and 'max' in r:
                # Convert range bounds to fixed point
                out_min = FixedPoint.from_float(float(r['min']))
                out_max = FixedPoint.from_float(float(r['max']))
                
                # Calculate range size
                range_size = out_max - out_min
                
                # Scale normalized value to output range
                value = out_min + FixedPoint.multiply(normalized, range_size)
                
                # Convert back to float for final output
                return FixedPoint.to_float(value)
                
        return FixedPoint.to_float(normalized)
        
    def process_message(self, message, voice_manager):
        """Transform MIDI message into parameter stream"""
        msg_type = message.get('type')
        channel = message.get('channel')
        data = message.get('data', {})
        
        _log(f"Processing {msg_type} message on channel {channel}: {data}")
        
        # Store MPE messages in channel buffer
        if msg_type in ['pitch_bend', 'channel_pressure'] or (msg_type == 'cc' and data.get('number') == 74):
            if self.route_cache.is_whitelisted(msg_type):
                channel_buffer = self._get_channel_buffer(channel)
                channel_buffer.append((msg_type, data))
                _log(f"Buffered {msg_type} for channel {channel}")
                
        # Handle CC messages
        if msg_type == 'cc':
            cc_num = data.get('number')
            if not self.route_cache.is_whitelisted('cc', cc_num):
                _log(f"[REJECTED] CC {cc_num} not in whitelist")
                return None
                
            route = self.route_cache.get_route('cc', cc_num)
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
                
        # Handle note messages
        elif msg_type in ['note_on', 'note_off']:
            results = []
            
            # Process note number if whitelisted
            if self.route_cache.is_whitelisted(msg_type, 'note'):
                _log(f"Note {msg_type} attribute 'note' is whitelisted")
                note_route = self.route_cache.get_route('per_key', 'note')
                if note_route:
                    _log(f"Found per_key route for note -> {note_route['module']}.{note_route['parameter']}")
                    if 'note' in data:
                        value = self.transform_value(data['note'], note_route)
                        stream = {
                            'channel': channel,
                            'target': {
                                'module': note_route['module'],
                                'parameter': note_route['parameter']
                            },
                            'value': value
                        }
                        results.append(stream)
                        _log(f"Created note parameter stream: {stream}")
            
            # Process velocity if whitelisted for note_on
            if msg_type == 'note_on' and self.route_cache.is_whitelisted(msg_type, 'velocity'):
                _log("Note on velocity is whitelisted")
                velocity_route = self.route_cache.get_route('per_key', 'velocity')
                if velocity_route:
                    _log(f"Found per_key route for velocity -> {velocity_route['module']}.{velocity_route['parameter']}")
                    if 'velocity' in data:
                        value = self.transform_value(data['velocity'], velocity_route)
                        stream = {
                            'channel': channel,
                            'target': {
                                'module': velocity_route['module'],
                                'parameter': velocity_route['parameter']
                            },
                            'value': value
                        }
                        results.append(stream)
                        _log(f"Created velocity parameter stream: {stream}")
            
            # Process note off trigger if whitelisted
            if msg_type == 'note_off' and self.route_cache.is_whitelisted(msg_type, 'trigger'):
                _log("Note off trigger is whitelisted")
                trigger_route = self.route_cache.get_route('per_key', 'trigger')
                if trigger_route:
                    _log(f"Found per_key route for trigger -> {trigger_route['module']}.{trigger_route['parameter']}")
                    stream = {
                        'channel': channel,
                        'target': {
                            'module': trigger_route['module'],
                            'parameter': trigger_route['parameter']
                        },
                        'value': 0  # Trigger off
                    }
                    results.append(stream)
                    _log(f"Created trigger parameter stream: {stream}")
            
            # For note on, send buffered MPE messages after note
            if msg_type == 'note_on':
                # Send buffered MPE messages in order
                channel_buffer = self._get_channel_buffer(channel)
                for msg_type, data in channel_buffer.buffer:
                    if msg_type == 'pitch_bend':
                        route = self.route_cache.get_route('per_key', 'pitch_bend')
                        if route:
                            value = self.transform_value(data.get('value', 0), route)
                            stream = {
                                'channel': channel,
                                'target': {
                                    'module': route['module'],
                                    'parameter': route['parameter']
                                },
                                'value': value
                            }
                            results.append(stream)
                            _log(f"Sent buffered pitch bend: {stream}")
                            
                    elif msg_type == 'channel_pressure':
                        route = self.route_cache.get_route('per_key', 'pressure')
                        if route:
                            value = self.transform_value(data.get('value', 0), route)
                            stream = {
                                'channel': channel,
                                'target': {
                                    'module': route['module'],
                                    'parameter': route['parameter']
                                },
                                'value': value
                            }
                            results.append(stream)
                            _log(f"Sent buffered pressure: {stream}")
                            
                    elif msg_type == 'cc' and data.get('number') == 74:
                        route = self.route_cache.get_route('per_key', 'timbre')
                        if route:
                            value = self.transform_value(data.get('value', 0), route)
                            stream = {
                                'channel': channel,
                                'target': {
                                    'module': route['module'],
                                    'parameter': route['parameter']
                                },
                                'value': value
                            }
                            results.append(stream)
                            _log(f"Sent buffered timbre: {stream}")
                
                # Clear buffer after sending
                channel_buffer.clear()
            
            if results:
                _log(f"Sending {len(results)} parameter streams to voice manager")
                return results
            else:
                _log("No parameter streams created")
                return None
                
        # All other message types must be explicitly whitelisted
        else:
            if not self.route_cache.is_whitelisted(msg_type):
                _log(f"[REJECTED] Message type '{msg_type}' not in whitelist")
                return None
                
        return None

class MasterRouter(ModuleRouter):
    """Master router that coordinates between module routers"""
    def __init__(self, routers):
        super().__init__()
        self.module_name = "master"
        self.routers = routers
        
    def compile_routes(self, config):
        """Compile routes for all module routers"""
        for router in self.routers.values():
            router.compile_routes(config)
            
    def process_message(self, message, voice_manager):
        """Process message through all module routers"""
        for router in self.routers.values():
            result = router.process_message(message, voice_manager)
            if result:
                if isinstance(result, list):
                    for stream in result:
                        voice_manager.process_parameter_stream(stream)
                else:
                    voice_manager.process_parameter_stream(result)

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
