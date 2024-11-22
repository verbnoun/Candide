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
        self.routes = {
            'controls': {},  # Routes for continuous controls
            'triggers': {}   # Routes for trigger events
        }
        
    def add_control_route(self, source_type, source_id, route_info):
        """Add a continuous control route mapping"""
        key = f"{source_type}.{source_id}"
        self.routes['controls'][key] = route_info
        _log(f"Added control route: {key} -> {route_info}")
        
    def add_trigger_route(self, source_type, source_id, route_info):
        """Add a trigger route mapping"""
        key = f"{source_type}.{source_id}"
        self.routes['triggers'][key] = route_info
        _log(f"Added trigger route: {key} -> {route_info}")
        
    def get_control_route(self, source_type, source_id):
        """Get control route info if it exists"""
        key = f"{source_type}.{source_id}"
        route = self.routes['controls'].get(key)
        if route:
            _log(f"Found control route for {key}")
        return route
        
    def get_trigger_route(self, source_type, source_id):
        """Get trigger route info if it exists"""
        key = f"{source_type}.{source_id}"
        route = self.routes['triggers'].get(key)
        if route:
            _log(f"Found trigger route for {key}")
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

class Router:
    """Routes MIDI messages to voice parameters based on config"""
    def __init__(self):
        self.route_cache = RouteCache()
        self.channel_buffers = {}
        
    def _get_channel_buffer(self, channel):
        """Get or create buffer for a channel"""
        if channel not in self.channel_buffers:
            self.channel_buffers[channel] = ChannelBuffer()
        return self.channel_buffers[channel]
        
    def compile_routes(self, config):
        """Extract and compile routes from config"""
        if not config:
            _log("[WARNING] No config provided")
            return
            
        _log("Compiling routes")
        
        # Store whitelist
        self.route_cache.set_whitelist(config.get('midi_whitelist', {}))
        
        # Traverse config to compile routes
        for module_name, module_config in config.items():
            if isinstance(module_config, dict):
                self._compile_module_routes(module_name, module_config)
        
        _log("Route compilation complete")
        
    def _compile_module_routes(self, module_name, config, path=''):
        """Compile routes for a module"""
        # Process triggers at this level
        if 'triggers' in config:
            triggers = config['triggers']
            if isinstance(triggers, dict):
                for trigger_type, trigger_config in triggers.items():
                    if 'sources' in trigger_config:
                        for source in trigger_config['sources']:
                            if source.get('type') != 'null':  # Skip null triggers
                                trigger_path = f"{path}.{trigger_type}" if path else trigger_type
                                self._create_trigger_route(module_name, source, trigger_path)
                                
        # Process controls at this level
        if 'sources' in config and 'controls' in config['sources']:
            for control in config['sources']['controls']:
                self._create_control_route(module_name, control, path, config)
                
        # Recurse into other dictionaries
        for key, value in config.items():
            if isinstance(value, dict) and key not in ['sources', 'triggers']:
                new_path = f"{path}.{key}" if path else key
                self._compile_module_routes(module_name, value, new_path)
                
    def _create_trigger_route(self, module_name, source, trigger_path):
        """Create a trigger route from source config"""
        route_info = {
            'module': module_name,
            'path': trigger_path,
            'type': 'trigger'
        }
        self.route_cache.add_trigger_route(source['type'], source['event'], route_info)
        
    def _create_control_route(self, module_name, source, param_path, param_config):
        """Create a control route from source config"""
        route_info = {
            'module': module_name,
            'path': param_path,
            'type': 'control',
            'midi_range': source.get('midi_range', {'min': 0, 'max': 127}),
            'output_range': param_config.get('output_range', {'min': 0, 'max': 1}),
            'curve': param_config.get('curve', 'linear'),
            'transform': source.get('transform')
        }
        self.route_cache.add_control_route(source['type'], source['event'], route_info)
        
    def transform_value(self, value, route_info):
        """Transform value based on route configuration"""
        if not isinstance(value, (int, float)):
            return 0
            
        midi_range = route_info.get('midi_range', {'min': 0, 'max': 127})
        output_range = route_info.get('output_range', {'min': 0, 'max': 1})
        
        # Normalize to 0-1 range based on input range
        normalized = (value - midi_range['min']) / (midi_range['max'] - midi_range['min'])
        normalized = max(0, min(1, normalized))  # Clamp to 0-1
        
        # Scale to output range
        out_min = output_range['min']
        out_max = output_range['max']
        value = out_min + (normalized * (out_max - out_min))
        
        return value
        
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
                
        # Handle CC messages (continuous controls)
        if msg_type == 'cc':
            cc_num = data.get('number')
            if not self.route_cache.is_whitelisted('cc', cc_num):
                _log(f"[REJECTED] CC {cc_num} not in whitelist")
                return None
                
            route = self.route_cache.get_control_route('cc', cc_num)
            if route:
                value = self.transform_value(data.get('value', 0), route)
                result = {
                    'channel': None,  # Global parameter
                    'target': {
                        'module': route['module'],
                        'path': route['path'],
                        'type': route['type']
                    },
                    'value': value
                }
                _log(f"Routed CC message: {result}")
                return result
                
        # Handle note messages
        elif msg_type in ['note_on', 'note_off']:
            results = []
            
            # Handle trigger events
            route = self.route_cache.get_trigger_route('per_key', 'note_' + msg_type.split('_')[1])
            if route:
                stream = {
                    'channel': channel,
                    'target': {
                        'module': route['module'],
                        'path': route['path'],
                        'type': route['type']
                    },
                    'value': 1 if msg_type == 'note_on' else 0
                }
                results.append(stream)
                
            # Handle continuous controls
            for control in ['note', 'velocity']:
                if msg_type == 'note_on' or (msg_type == 'note_off' and control == 'note'):
                    route = self.route_cache.get_control_route('per_key', control)
                    if route and control in data:
                        value = self.transform_value(data[control], route)
                        stream = {
                            'channel': channel,
                            'target': {
                                'module': route['module'],
                                'path': route['path'],
                                'type': route['type']
                            },
                            'value': value
                        }
                        results.append(stream)
            
            # For note on, send buffered MPE messages
            if msg_type == 'note_on':
                channel_buffer = self._get_channel_buffer(channel)
                for msg_type, data in channel_buffer.buffer:
                    if msg_type == 'pitch_bend':
                        route = self.route_cache.get_control_route('per_key', 'pitch_bend')
                    elif msg_type == 'channel_pressure':
                        route = self.route_cache.get_control_route('per_key', 'pressure')
                    elif msg_type == 'cc' and data.get('number') == 74:
                        route = self.route_cache.get_control_route('per_key', 'timbre')
                    else:
                        continue
                        
                    if route:
                        value = self.transform_value(data.get('value', 0), route)
                        stream = {
                            'channel': channel,
                            'target': {
                                'module': route['module'],
                                'path': route['path'],
                                'type': route['type']
                            },
                            'value': value
                        }
                        results.append(stream)
                        
                channel_buffer.clear()
                
            if results:
                _log(f"Sending {len(results)} parameter streams")
                return results
                
        return None