"""
Router Module

Two main functions:
1. Filter incoming MIDI using whitelist (only accept MIDI used in config)
2. Route filtered MIDI to parameters using precomputed paths
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
            if isinstance(v, dict):
                formatted += "  " + str(k) + ":\n"
                for sub_k, sub_v in v.items():
                    formatted += "    " + str(sub_k) + ": " + str(sub_v) + "\n"
            else:
                formatted += "  " + str(k) + ": " + str(v) + "\n"
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

def _format_route_info(route_info):
    """Format route info for logging with proper indentation"""
    formatted = "\n"
    formatted += "  path: " + str(route_info.get('path', 'None')) + "\n"
    formatted += "  type: " + str(route_info.get('type', 'None')) + "\n"
    
    # Format ranges if present
    if route_info.get('midi_range'):
        formatted += "  midi_range:\n"
        formatted += "    min: " + str(route_info['midi_range'].get('min', 'None')) + "\n"
        formatted += "    max: " + str(route_info['midi_range'].get('max', 'None')) + "\n"
        
    if route_info.get('output_range'):
        formatted += "  output_range:\n"
        formatted += "    min: " + str(route_info['output_range'].get('min', 'None')) + "\n"
        formatted += "    max: " + str(route_info['output_range'].get('max', 'None')) + "\n"
        
    if route_info.get('curve'):
        formatted += "  curve: " + str(route_info['curve']) + "\n"
        
    if route_info.get('transform'):
        formatted += "  transform: " + str(route_info['transform']) + "\n"
        
    return formatted

class MPEBuffer:
    """Buffers MPE control messages until voices are created by note_on"""
    def __init__(self):
        self.messages = {}
        
    def store(self, msg_type, channel, data):
        """Store MPE control data for a channel"""
        if channel not in self.messages:
            self.messages[channel] = {}
        self.messages[channel][msg_type] = data
        _log(f"Buffered MPE {msg_type} for channel {channel}")
        _log(f"Data: {data}")
        
    def get_messages(self, channel):
        """Get buffered MPE messages for channel"""
        return self.messages.get(channel, {})
        
    def clear_channel(self, channel):
        """Clear MPE buffer after note_on creates voice"""
        if channel in self.messages:
            _log(f"Clearing MPE buffer for channel {channel}")
            del self.messages[channel]

class MIDIFilter:
    """Filters incoming MIDI using whitelist from config"""
    def __init__(self):
        self.whitelist = {
            'cc': set(),
            'note_on': set(),
            'note_off': set()
        }
        
    def set_whitelist(self, whitelist):
        """Set MIDI message whitelist"""
        self.whitelist = whitelist
        _log("MIDI Whitelist:")
        for msg_type, attrs in whitelist.items():
            _log(f"  {msg_type}: {attrs}")
            
    def is_whitelisted(self, msg_type, attribute=None):
        """Check if message type and attribute are whitelisted"""
        if msg_type not in self.whitelist:
            return False
        if attribute is None:
            return True
        return attribute in self.whitelist[msg_type]

class Router:
    """Routes MIDI messages to voice parameters based on config paths"""
    def __init__(self):
        self.midi_filter = MIDIFilter()
        self.mpe_buffer = MPEBuffer()
        self.routes = {
            'controls': {},  # Routes for continuous controls
            'triggers': {}   # Routes for trigger events
        }
        
    def compile_routes(self, config):
        """Extract routes from config"""
        if not config:
            _log("[WARNING] No config provided")
            return
            
        _log("Compiling routes")
        
        # Set up MIDI filter
        self.midi_filter.set_whitelist(config.get('midi_whitelist', {}))
        
        # Find all routes in config
        self._find_routes(config)
                
        _log("Route compilation complete")
        
    def _add_control_route(self, source_type, source_id, route_info):
        """Add a continuous control route mapping"""
        key = f"{source_type}.{source_id}"
        self.routes['controls'][key] = route_info
        _log("Added control route:")
        _log(f"  MIDI -> Path: {key} -> {route_info['path']}")
        _log(f"  Details:{_format_route_info(route_info)}")
        
    def _add_trigger_route(self, source_type, source_id, route_info):
        """Add a trigger route mapping"""
        key = f"{source_type}.{source_id}"
        self.routes['triggers'][key] = route_info
        _log("Added trigger route:")
        _log(f"  MIDI -> Path: {key} -> {route_info['path']}")
        _log(f"  Details:{_format_route_info(route_info)}")
        
    def _find_routes(self, config, path=''):
        """Find all routes in config preserving full paths"""
        if not isinstance(config, dict):
            return
            
        _log(f"Traversing path: {path}")
            
        # Handle sources if present - these control the parameter at current path
        if 'sources' in config:
            _log(f"Found sources controlling: {path}")
            if 'controls' in config['sources']:
                _log("Processing control sources:")
                for control in config['sources']['controls']:
                    _log(f"  Control source: {control}")
                    route_info = {
                        'path': path,
                        'type': 'control',
                        'midi_range': control.get('midi_range'),
                        'output_range': config.get('output_range'),
                        'curve': config.get('curve'),
                        'transform': control.get('transform')
                    }
                    self._add_control_route(
                        control['type'],
                        control['event'],
                        route_info
                    )
                    
        # Handle triggers if present - these are trigger sources
        if 'triggers' in config:
            _log(f"Found trigger sources at: {path}")
            for trigger_name, trigger_config in config['triggers'].items():
                _log(f"  Processing trigger source: {trigger_name}")
                if isinstance(trigger_config, dict) and 'sources' in trigger_config:
                    # Include triggers in path - tells voices this is a trigger source
                    trigger_path = f"{path}.triggers.{trigger_name}" if path else f"triggers.{trigger_name}"
                    _log(f"  Trigger path: {trigger_path}")
                    for source in trigger_config['sources']:
                        _log(f"    Trigger source: {source}")
                        if source.get('type') != 'null':
                            route_info = {
                                'path': trigger_path,
                                'type': 'trigger'
                            }
                            self._add_trigger_route(
                                source['type'],
                                source['event'],
                                route_info
                            )
                            
        # Recurse into all dictionary values except internal config
        for key, value in config.items():
            if isinstance(value, dict):
                # Skip internal config keys
                if key in ['midi_whitelist', 'output_range']:
                    continue
                    
                new_path = f"{path}.{key}" if path else key
                _log(f"Recursing into: {new_path}")
                self._find_routes(value, new_path)
                
    def _get_control_route(self, source_type, source_id):
        """Get control route info if it exists"""
        key = f"{source_type}.{source_id}"
        return self.routes['controls'].get(key)
        
    def _get_trigger_routes(self, source_type, event_type):
        """Get all trigger routes matching source type and event"""
        key = f"{source_type}.{event_type}"
        matching_routes = []
        for route_key, route in self.routes['triggers'].items():
            if route_key == key:
                matching_routes.append(route)
        return matching_routes
                
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
                'path': route['path'],
                'type': route['type']
            },
            'value': value
        }
        _log("Created parameter stream:")
        _log(stream)
        return stream
        
    def process_message(self, message, voice_manager):
        """Transform MIDI message into parameter stream"""
        msg_type = message.get('type')
        channel = message.get('channel')
        data = message.get('data', {})
        
        _log(f"Processing {msg_type} message on channel {channel}")
        _log(f"Data: {data}")
        
        # Check whitelist first
        if not self.midi_filter.is_whitelisted(msg_type):
            _log(f"[REJECTED] {msg_type} not in whitelist")
            return None
            
        # Buffer MPE control messages until note_on
        if msg_type in ['pitch_bend', 'channel_pressure'] or (msg_type == 'cc' and data.get('number') == 74):
            self.mpe_buffer.store(msg_type, channel, data)
            return None
        
        # Process message based on type
        if msg_type == 'cc':
            return self._process_cc_message(channel, data)
        elif msg_type in ['note_on', 'note_off']:
            return self._process_note_message(msg_type, channel, data)
            
        return None
        
    def _process_cc_message(self, channel, data):
        """Process CC message"""
        cc_num = data.get('number')
        if not self.midi_filter.is_whitelisted('cc', cc_num):
            _log(f"[REJECTED] CC {cc_num} not in whitelist")
            return None
            
        route = self._get_control_route('cc', cc_num)
        if route:
            value = self.transform_value(data.get('value', 0), route)
            return self._create_parameter_stream(None, route, value)
            
        return None
        
    def _process_note_message(self, msg_type, channel, data):
        """Process note message"""
        results = []
        
        # Get all trigger routes for this event type
        trigger_routes = self._get_trigger_routes('per_key', msg_type)
        for route in trigger_routes:
            stream = self._create_parameter_stream(
                channel, route, 1 if msg_type == 'note_on' else 0
            )
            results.append(stream)
            
        # Handle note controls
        for control in ['note', 'velocity']:
            if msg_type == 'note_on' or (msg_type == 'note_off' and control == 'note'):
                route = self._get_control_route('per_key', control)
                if route and control in data:
                    value = self.transform_value(data[control], route)
                    stream = self._create_parameter_stream(channel, route, value)
                    results.append(stream)
                    
        # On note_on, send any buffered MPE messages for this channel
        if msg_type == 'note_on':
            buffered = self.mpe_buffer.get_messages(channel)
            for msg_type, data in buffered.items():
                if msg_type == 'pitch_bend':
                    route = self._get_control_route('per_key', 'pitch_bend')
                elif msg_type == 'channel_pressure':
                    route = self._get_control_route('per_key', 'pressure')
                elif msg_type == 'cc' and data.get('number') == 74:
                    route = self._get_control_route('per_key', 'timbre')
                else:
                    continue
                    
                if route:
                    value = self.transform_value(data.get('value', 0), route)
                    stream = self._create_parameter_stream(channel, route, value)
                    results.append(stream)
                    
            # Clear buffer after sending
            self.mpe_buffer.clear_channel(channel)
            
        return results if results else None
