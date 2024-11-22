"""
Router Module

Transforms MIDI messages into data streams based on instrument configuration.
Each route defined in config creates a mapping from MIDI input to module parameter.
No knowledge of voice implementation - just creates normalized parameter streams.
"""

import sys
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
        elif "[ROUTE]" in str(message):
            color = GREEN
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
        return self.routes['controls'].get(key)
        
    def get_trigger_route(self, source_type, source_id):
        """Get trigger route info if it exists"""
        key = f"{source_type}.{source_id}"
        return self.routes['triggers'].get(key)
        
    def get_all_trigger_routes(self, source_type, event_type):
        """Get all trigger routes matching source type and event"""
        matching_routes = []
        for key, route in self.routes['triggers'].items():
            if key == f"{source_type}.{event_type}":
                matching_routes.append(route)
        return matching_routes
        
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
    """Buffer for channel-specific messages"""
    def __init__(self):
        self.messages = {}
        
    def store(self, msg_type, channel, data):
        """Store message data for a channel"""
        if channel not in self.messages:
            self.messages[channel] = {}
        self.messages[channel][msg_type] = data
        
    def get_messages(self, channel):
        """Get all stored messages for a channel"""
        return self.messages.get(channel, {})
        
    def clear_channel(self, channel):
        """Clear stored messages for a channel"""
        if channel in self.messages:
            del self.messages[channel]

class Router:
    """Routes MIDI messages to voice parameters based on config"""
    def __init__(self):
        self.route_cache = RouteCache()
        self.channel_buffer = ChannelBuffer()
        
    def compile_routes(self, config):
        """Extract and compile routes from config"""
        if not config:
            _log("[WARNING] No config provided")
            return
            
        _log("Compiling routes")
        
        # Store whitelist
        self.route_cache.set_whitelist(config.get('midi_whitelist', {}))
        
        # Traverse config to compile routes
        self._traverse_config(config)
                
        _log("Route compilation complete")
        
    def _traverse_config(self, config, path=''):
        """Traverse config and extract all routes preserving full paths"""
        if not isinstance(config, dict):
            return
            
        # Handle sources if present
        if 'sources' in config:
            if 'controls' in config['sources']:
                for control in config['sources']['controls']:
                    route_info = {
                        'module': path.split('.')[0] if path else None,
                        'path': path,
                        'type': 'control',
                        'midi_range': control.get('midi_range'),
                        'output_range': config.get('output_range'),
                        'curve': config.get('curve'),
                        'transform': control.get('transform')
                    }
                    self.route_cache.add_control_route(
                        control['type'],
                        control['event'],
                        route_info
                    )
                    
        # Handle triggers if present
        if 'triggers' in config:
            for trigger_name, trigger_config in config['triggers'].items():
                if isinstance(trigger_config, dict) and 'sources' in trigger_config:
                    trigger_path = f"{path}.{trigger_name}" if path else trigger_name
                    for source in trigger_config['sources']:
                        if source.get('type') != 'null':
                            route_info = {
                                'module': trigger_path.split('.')[0],
                                'path': trigger_path,
                                'type': 'trigger'
                            }
                            self.route_cache.add_trigger_route(
                                source['type'],
                                source['event'],
                                route_info
                            )
                            
        # Recurse into all dictionary values
        for key, value in config.items():
            if isinstance(value, dict):
                new_path = f"{path}.{key}" if path else key
                self._traverse_config(value, new_path)
                
    def transform_value(self, value, route_info):
        """Transform value based on route configuration"""
        if not isinstance(value, (int, float)):
            return 0
            
        if not route_info.get('midi_range') or not route_info.get('output_range'):
            return value
            
        midi_range = route_info['midi_range']
        output_range = route_info['output_range']
        
        # Normalize to 0-1 range
        normalized = (value - midi_range['min']) / (midi_range['max'] - midi_range['min'])
        normalized = max(0, min(1, normalized))
        
        # Scale to output range
        out_min = output_range['min']
        out_max = output_range['max']
        value = out_min + (normalized * (out_max - out_min))
        
        return value
        
    def _create_parameter_stream(self, channel, route, value):
        """Create parameter stream for voice manager"""
        stream = {
            'channel': channel,
            'target': {
                'module': route['module'],
                'path': route['path'],
                'type': route['type']
            },
            'value': value
        }
        _log(f"[ROUTE] Created parameter stream: {stream}")
        return stream
        
    def process_message(self, message, voice_manager):
        """Transform MIDI message into parameter stream"""
        msg_type = message.get('type')
        channel = message.get('channel')
        data = message.get('data', {})
        
        _log(f"Processing {msg_type} message on channel {channel}: {data}")
        
        # Buffer channel-specific messages
        if msg_type in self.route_cache.midi_whitelist:
            if msg_type in ['pitch_bend', 'channel_pressure'] or (msg_type == 'cc' and data.get('number') == 74):
                self.channel_buffer.store(msg_type, channel, data)
                _log(f"Buffered {msg_type} for channel {channel}")
                
        # Process message based on type
        if msg_type == 'cc':
            return self._process_cc_message(channel, data)
        elif msg_type in ['note_on', 'note_off']:
            return self._process_note_message(msg_type, channel, data)
            
        return None
        
    def _process_cc_message(self, channel, data):
        """Process CC message"""
        cc_num = data.get('number')
        if not self.route_cache.is_whitelisted('cc', cc_num):
            _log(f"[REJECTED] CC {cc_num} not in whitelist")
            return None
            
        route = self.route_cache.get_control_route('cc', cc_num)
        if route:
            value = self.transform_value(data.get('value', 0), route)
            return self._create_parameter_stream(None, route, value)
            
        return None
        
    def _process_note_message(self, msg_type, channel, data):
        """Process note message"""
        results = []
        
        # Get all trigger routes for this event type
        trigger_routes = self.route_cache.get_all_trigger_routes('per_key', msg_type)
        for route in trigger_routes:
            stream = self._create_parameter_stream(
                channel, route, 1 if msg_type == 'note_on' else 0
            )
            results.append(stream)
            
        # Handle note controls
        for control in ['note', 'velocity']:
            if msg_type == 'note_on' or (msg_type == 'note_off' and control == 'note'):
                route = self.route_cache.get_control_route('per_key', control)
                if route and control in data:
                    value = self.transform_value(data[control], route)
                    stream = self._create_parameter_stream(channel, route, value)
                    results.append(stream)
                    
        # Process buffered messages on note_on
        if msg_type == 'note_on':
            buffered = self.channel_buffer.get_messages(channel)
            for msg_type, data in buffered.items():
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
                    stream = self._create_parameter_stream(channel, route, value)
                    results.append(stream)
                    
            self.channel_buffer.clear_channel(channel)
            
        return results if results else None
