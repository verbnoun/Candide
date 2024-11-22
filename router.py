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
        
    RED = "\033[31m"  # Keep red for errors
    DARK_BLUE = "\033[34m"  # Darkest blue for rejected messages
    MEDIUM_BLUE = "\033[94m"  # Medium blue for route messages
    LIGHT_BLUE = "\033[96m"  # Light blue for general messages
    RESET = "\033[0m"
    
    def format_dict(d, indent=0):
        """Format dictionary with simple indentation."""
        lines = []
        spaces = " " * indent
        for k, v in d.items():
            if isinstance(v, dict):
                lines.append(f"{spaces}{k}:")
                lines.extend(format_dict(v, indent + 2))
            else:
                lines.append(f"{spaces}{k}: {v}")
        return lines
    
    def format_parameter_stream(stream):
        """Format parameter stream with nice indentation."""
        lines = []
        lines.append("Parameter stream:")
        lines.append(f"  channel: {stream['channel']}")
        lines.append("  target:")
        target = stream['target']
        lines.append(f"    type: {target['type']}")
        lines.append(f"    path: {target['path']}")
        lines.append(f"    module: {target['module']}")
        lines.append(f"  value: {stream['value']}")
        return "\n".join(lines)

    def format_midi_message(msg_type, channel, data):
        """Format MIDI message with nice indentation."""
        lines = []
        lines.append(f"Processing {msg_type} message:")
        lines.append(f"  channel: {channel}")
        lines.append("  data:")
        for k, v in data.items():
            lines.append(f"    {k}: {v}")
        return "\n".join(lines)

    def format_transform_value(value, output_range):
        """Format value transformation with nice indentation."""
        lines = []
        lines.append("Transformed value:")
        lines.append(f"  result: {value}")
        lines.append("  output range:")
        lines.append(f"    min: {output_range['min']}")
        lines.append(f"    max: {output_range['max']}")
        return "\n".join(lines)
    
    if isinstance(message, dict):
        # Format dictionary with simple indentation
        formatted = "\n".join(format_dict(message, 2))
        print(f"\n{LIGHT_BLUE}[{module}]\n{formatted}{RESET}\n", file=sys.stderr)
    else:
        # Format string messages with appropriate colors
        if "[ERROR]" in str(message):
            color = RED
        elif "[REJECTED]" in str(message):
            color = DARK_BLUE
        elif "[ROUTE]" in str(message):
            color = MEDIUM_BLUE
        else:
            color = LIGHT_BLUE
            
        # Special formatting for whitelist and route messages
        if "whitelist" in str(message):
            parts = str(message).split(": ", 1)
            if len(parts) == 2:
                try:
                    whitelist_str = parts[1].replace("'", "").replace("{", "").replace("}", "")
                    print(f"\n{color}[{module}] {parts[0]}:", file=sys.stderr)
                    for item in whitelist_str.split(","):
                        print(f"{color}  {item.strip()}{RESET}", file=sys.stderr)
                    print("", file=sys.stderr)
                    return
                except:
                    pass
                    
        if "route" in str(message).lower() and " -> " in str(message):
            route_parts = str(message).split(" -> ")
            if len(route_parts) == 2:
                try:
                    route_dict = eval(route_parts[1])
                    print(f"\n{color}[{module}] Added route: {route_parts[0]} ->", file=sys.stderr)
                    for k, v in route_dict.items():
                        print(f"{color}  {k}: {v}{RESET}", file=sys.stderr)
                    print("", file=sys.stderr)
                    return
                except:
                    pass

        # Format MIDI message processing
        if isinstance(message, str) and "Processing" in message and "message on channel" in message:
            try:
                parts = message.split("message on channel")
                msg_type = parts[0].split("Processing ")[1].strip()
                channel = parts[1].split(":")[0].strip()
                data = eval(parts[1].split(":", 1)[1].strip())
                formatted = format_midi_message(msg_type, channel, data)
                print(f"\n{color}[{module}]\n{color}{formatted}{RESET}\n", file=sys.stderr)
                return
            except:
                pass

        # Format value transformation
        if isinstance(message, str) and "Transformed value" in message and "using range" in message:
            try:
                parts = message.split("using range")
                value = float(parts[0].split("value")[1].strip())
                output_range = eval(parts[1].strip())
                formatted = format_transform_value(value, output_range)
                print(f"\n{color}[{module}]\n{color}{formatted}{RESET}\n", file=sys.stderr)
                return
            except:
                pass
                    
        # Format parameter stream messages
        if isinstance(message, str) and "Parameter stream:" in message:
            try:
                stream_dict = eval(message.split(": ", 1)[1])
                formatted = format_parameter_stream(stream_dict)
                print(f"\n{color}[{module}]\n{color}{formatted}{RESET}\n", file=sys.stderr)
                return
            except:
                pass
                    
        # Default formatting for other messages
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class RouteCache:
    """Stores compiled routes from config"""
    def __init__(self):
        self.midi_whitelist = {}
        self.routes = {
            'controls': {},  # Routes for continuous controls
            'triggers': {}   # Routes for trigger events
        }
        
    def add_control_route(self, route_info):
        if route_info['source_type'] == 'cc':
            key = f"cc.{route_info['source_event']}"  # Use CC number as event
        else:
            key = f"{route_info['source_type']}.{route_info['source_event']}"
        self.routes['controls'][key] = route_info
        _log(f"Added control route: {key} -> {route_info}")
        
    def add_trigger_route(self, route_info):
        """Add a trigger route mapping"""
        key = f"{route_info.get('source_type')}.{route_info.get('source_event')}"
        self.routes['triggers'][key] = route_info
        _log(f"Added trigger route: {key} -> {route_info}")
        
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

class Router:
    """Routes MIDI messages to voice parameters based on config"""
    def __init__(self):
        self.route_cache = RouteCache()
        
    def compile_routes(self, config):
        """Extract and compile routes from config"""
        if not config:
            _log("[WARNING] No config provided")
            return
            
        _log("Compiling routes")
        
        # Reset route cache
        self.route_cache = RouteCache()
        
        # Set whitelist from config
        self.route_cache.set_whitelist(config.get('midi_whitelist', {}))
        
        # Recursively compile routes
        self._compile_routes_recursive(config)
                
        _log("Route compilation complete")
        
    def _compile_routes_recursive(self, config, current_path=''):
        if not isinstance(config, dict):
            return
        
        for key, value in config.items():
            path = f"{current_path}.{key}" if current_path else key
            
            if isinstance(value, dict):
                # Handle sources structure
                sources = value.get('sources', {})
                
                # Handle controls array
                if 'controls' in sources:
                    for control in sources['controls']:
                        route_info = {
                            'source_type': control.get('type'),
                            'source_event': control.get('event'),
                            'module': current_path.split('.')[0] if current_path else None,
                            'path': path,
                            'type': 'control',
                            'midi_range': control.get('midi_range'),
                            'output_range': value.get('output_range'),
                            'curve': value.get('curve'),
                            'transform': control.get('transform')
                        }
                        
                        # Special handling for CC routes
                        if control.get('type') == 'cc':
                            route_info['source_event'] = str(control.get('number'))
                        
                        self.route_cache.add_control_route(route_info)
                
                # Handle triggers
                if 'triggers' in sources:
                    for trigger_name, trigger in sources['triggers'].items():
                        route_info = {
                            'source_type': trigger.get('type'),
                            'source_event': trigger.get('event'),
                            'module': current_path.split('.')[0] if current_path else None,
                            'path': path,
                            'type': 'trigger',
                            'midi_range': None,
                            'output_range': value.get('output_range'),
                            'curve': value.get('curve'),
                            'transform': None
                        }
                        self.route_cache.add_trigger_route(route_info)
                
                # Continue recursion
                self._compile_routes_recursive(value, path)
        
    def process_message(self, message, voice_manager):
        """Transform MIDI message into parameter stream"""
        msg_type = message.get('type')
        channel = message.get('channel')
        data = message.get('data', {})
        
        _log(f"Processing {msg_type} message on channel {channel}: {data}")
        
        # Process message based on type
        result = None
        if msg_type == 'cc':
            result = self._process_cc_message(channel, data)
        elif msg_type in ['note_on', 'note_off']:
            result = self._process_note_message(msg_type, channel, data)
        elif msg_type == 'pressure':
            result = self._process_pressure_message(channel, data)
        else:
            _log(f"[REJECTED] Unsupported message type: {msg_type}")
            
        if result:
            if isinstance(result, list):
                _log(f"[ROUTE] Sending {len(result)} parameter streams to voices")
                for stream in result:
                    _log(f"Parameter stream: {stream}")
            else:
                _log(f"Parameter stream: {result}")
        else:
            _log(f"[REJECTED] No route found for {msg_type} message")
            
        return result
        
    def _process_cc_message(self, channel, data):
        """Process CC message"""
        cc_num = data.get('number')
        if not self.route_cache.is_whitelisted('cc', cc_num):
            _log(f"[REJECTED] CC {cc_num} not in whitelist")
            return None
            
        _log(f"[ROUTE] Processing CC {cc_num}")
        route = self.route_cache.routes['controls'].get(f'cc.{cc_num}')
        if route:
            value = self._transform_value(data.get('value', 0), route)
            return self._create_parameter_stream(None, route, value)
            
        _log(f"[REJECTED] No route found for CC {cc_num}")
        return None
        
    def _process_note_message(self, msg_type, channel, data):
        """Process note message"""
        results = []
        
        # First process the trigger (note_on/off)
        trigger_route = self.route_cache.routes['triggers'].get(f'per_key.{msg_type}')
        if trigger_route:
            _log(f"[ROUTE] Processing {msg_type} trigger")
            stream = self._create_parameter_stream(
                channel, trigger_route, 1 if msg_type == 'note_on' else 0
            )
            results.append(stream)
        else:
            _log(f"[REJECTED] No trigger route found for {msg_type}")

        # Then process note controls in reverse order (velocity first, then note)
        control_types = ['velocity', 'note']  # Reversed order
        for control_type in control_types:
            if (msg_type == 'note_on' or 
                (msg_type == 'note_off' and control_type == 'note')):
                _log(f"[ROUTE] Processing {msg_type} {control_type}")
                route = self.route_cache.routes['controls'].get(f'per_key.{control_type}')
                if route and control_type in data:
                    value = self._transform_value(data[control_type], route)
                    stream = self._create_parameter_stream(channel, route, value)
                    results.append(stream)
                else:
                    _log(f"[REJECTED] No route found for {msg_type} {control_type}")
            
        return results if results else None

    def _process_pressure_message(self, channel, data):
        """Process channel pressure message"""
        if not self.route_cache.is_whitelisted('pressure'):
            _log("[REJECTED] Pressure messages not in whitelist")
            return None
            
        _log("[ROUTE] Processing channel pressure")
        route = self.route_cache.routes['controls'].get('pressure')
        if route:
            value = self._transform_value(data.get('value', 0), route)
            return self._create_parameter_stream(channel, route, value)
            
        _log("[REJECTED] No route found for channel pressure")
        return None
        
    def _transform_value(self, value, route):
        """Transform value based on route configuration"""
        if not isinstance(value, (int, float)):
            _log(f"[ERROR] Invalid value type: {type(value)}")
            return 0
            
        if not route.get('midi_range') or not route.get('output_range'):
            return value
            
        midi_range = route['midi_range']
        output_range = route['output_range']
        
        # Normalize to 0-1 range
        normalized = (value - midi_range['min']) / (midi_range['max'] - midi_range['min'])
        normalized = max(0, min(1, normalized))
        
        # Scale to output range
        out_min = output_range['min']
        out_max = output_range['max']
        value = out_min + (normalized * (out_max - out_min))
        
        _log(f"[ROUTE] Transformed value {value} using range {output_range}")
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
        _log(f"Parameter stream: {stream}")
        return stream
