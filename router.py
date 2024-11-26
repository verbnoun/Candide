"""
Router Module

Transforms MIDI messages into data streams based on instrument configuration.
Each route defined in config creates a mapping from MIDI input to module parameter.
No knowledge of voice implementation - just creates normalized parameter streams and sends to voices.py.
"""

import sys
from constants import ROUTER_DEBUG

def _log(message, module="ROUTER"):
    """Conditional logging function that respects ROUTER_DEBUG flag."""
    if not ROUTER_DEBUG:
        return
        
    RED = "\033[31m"  # Keep red for errors
    MAGENTA = "\033[35m"  # Only for rejected messages
    LIGHT_MAGENTA = "\033[95m"  # For all other messages
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
    
    def format_parameter_stream(stream, stage=""):
        """Format parameter stream with nice indentation."""
        lines = []
        lines.append("Parameter stream:")
        if stage:
            lines.append(f"  stage: {stage}")
        lines.append(f"  value: {stream['value']}")
        lines.append("  target:")
        target = stream['target']
        lines.append(f"    type: {target['type']}")
        lines.append(f"    path: {target['path']}")
        lines.append(f"    module: {target['module']}")
        lines.append(f"  channel: {stream['channel']}")
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
        if 'stage' in message:
            # This is a parameter stream with stage info
            formatted = format_parameter_stream(message, message['stage'])
            print(f"\n[{module}]\n{formatted}\n", file=sys.stderr)
        else:
            # Format dictionary with simple indentation
            formatted = "\n".join(format_dict(message, 2))
            print(f"\n{LIGHT_MAGENTA}[{module}]\n{formatted}{RESET}\n", file=sys.stderr)
    else:
        # Format string messages with appropriate colors
        if "[ERROR]" in str(message):
            color = RED
        elif "[REJECTED]" in str(message):
            color = MAGENTA
        else:
            color = LIGHT_MAGENTA
            
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
                print(f"\n{color}[{module}]\n{formatted}{RESET}\n", file=sys.stderr)
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
                print(f"\n{color}[{module}]\n{formatted}{RESET}\n", file=sys.stderr)
                return
            except:
                pass
                    
        # Format parameter stream messages
        if isinstance(message, str) and "Parameter stream" in message:
            try:
                if ": {" in message:
                    stream_dict = eval(message.split(": ", 1)[1])
                    stage = ""
                    if "created" in message.lower():
                        stage = "created"
                    elif "sending" in message.lower():
                        stage = "sending to voices"
                    formatted = format_parameter_stream(stream_dict, stage)
                    print(f"\n{color}[{module}]\n{formatted}{RESET}\n", file=sys.stderr)
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

    def is_whitelisted(self, msg_type, attribute=None, channel=None):
        """Check if message type and attribute are whitelisted"""
        if msg_type not in self.midi_whitelist:
            return False
            
        if msg_type == 'cc' and attribute is not None:
            # Check if CC is whitelisted for this channel
            if (attribute, channel) in self.midi_whitelist['cc']:
                return True
            # Check if CC is whitelisted for any channel
            if attribute in {cc for cc in self.midi_whitelist['cc'] if not isinstance(cc, tuple)}:
                return True
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
        self.midi_whitelist = config.get('midi_whitelist', {})
        self.route_cache.set_whitelist(self.midi_whitelist)
        
        # Recursively compile routes
        self._compile_routes_recursive(config)
                
        _log("Route compilation complete")
        
    def _compile_routes_recursive(self, config, current_path=''):
        if not isinstance(config, dict):
            return
        
        def normalize_path(path):
            """Normalize paths to ensure consistent comparison"""
            # Handle timer path variants
            if 'timer.time' in path:
                if 'envelope.sources.timer.time' in path:
                    return path.replace('envelope.sources.timer.time', 'envelope.sustain.sources.timer.time')
                if 'envelope.sustain.sources.timer.time' in path:
                    return path
            return path
        
        def route_exists(route_info):
            """Check if route already exists using normalized paths"""
            source_type = route_info['source_type']
            source_event = route_info['source_event']
            normalized_path = normalize_path(route_info['path'])
            route_key = f"{source_type}.{source_event}"
            
            if route_key in self.route_cache.routes['controls']:
                existing_route = self.route_cache.routes['controls'][route_key]
                existing_path = normalize_path(existing_route['path'])
                if existing_path == normalized_path:
                    return True
            return False
        
        for key, value in config.items():
            path = f"{current_path}.{key}" if current_path else key
            
            if isinstance(value, dict):
                # Handle sources structure
                sources = value.get('sources', {})
                
                # Special handling for sustain section that has both value and level
                if current_path.endswith('envelope.sustain'):
                    if key == 'value' or key == 'level':
                        if 'sources' in value and 'controls' in value['sources']:
                            for control in value['sources']['controls']:
                                route_info = {
                                    'source_type': control.get('type'),
                                    'source_event': control.get('event'),
                                    'module': 'amplifier',
                                    'path': normalize_path(f"{current_path}.{key}"),
                                    'type': 'control',
                                    'midi_range': control.get('midi_range'),
                                    'output_range': value.get('output_range'),
                                    'curve': value.get('curve'),
                                    'transform': control.get('transform'),
                                    'value': value.get('value')
                                }
                                
                                if control.get('type') == 'cc':
                                    route_info['source_event'] = str(control.get('number'))
                                
                                if not route_exists(route_info):
                                    self.route_cache.add_control_route(route_info)
                
                # Handle timer structure
                if 'timer' in sources:
                    timer_info = sources['timer']
                    
                    # Add timer time control route if it exists
                    if 'time' in timer_info and 'controls' in timer_info['time'].get('sources', {}):
                        for control in timer_info['time']['sources']['controls']:
                            route_info = {
                                'source_type': control.get('type'),
                                'source_event': control.get('event'),
                                'module': 'amplifier',
                                'path': normalize_path(f"{current_path}.sources.timer.time"),
                                'type': 'control',
                                'midi_range': control.get('midi_range'),
                                'output_range': timer_info['time'].get('output_range'),
                                'curve': timer_info['time'].get('curve'),
                                'transform': control.get('transform'),
                                'value': timer_info['time'].get('value')
                            }
                            
                            if control.get('type') == 'cc':
                                route_info['source_event'] = str(control.get('number'))
                            
                            if not route_exists(route_info):
                                self.route_cache.add_control_route(route_info)
                    
                    # Add timer end trigger route if configured
                    if 'end' in timer_info:
                        route_info = {
                            'source_type': 'timer',
                            'source_event': 'end',
                            'module': 'amplifier',
                            'path': 'amplifier.envelope.release',
                            'type': 'trigger',
                            'midi_range': None,
                            'output_range': None,
                            'curve': None,
                            'transform': None
                        }
                        self.route_cache.add_trigger_route(route_info)
                
                # Handle regular controls
                if 'controls' in sources:
                    for control in sources['controls']:
                        route_info = {
                            'source_type': control.get('type'),
                            'source_event': control.get('event'),
                            'module': current_path.split('.')[0] if current_path else None,
                            'path': normalize_path(path),
                            'type': 'control',
                            'midi_range': control.get('midi_range'),
                            'output_range': value.get('output_range'),
                            'curve': value.get('curve'),
                            'transform': control.get('transform'),
                            'value': value.get('value')
                        }
                        
                        if control.get('type') == 'cc':
                            route_info['source_event'] = str(control.get('number'))
                        
                        if not route_exists(route_info):
                            self.route_cache.add_control_route(route_info)
                
                # Handle regular triggers
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
        """Transform MIDI message into parameter stream and send to voice manager"""
        msg_type = message.get('type')
        channel = message.get('channel')
        data = message.get('data', {})
        
        # Format MIDI message nicely
        _log({
            'type': msg_type,
            'channel': channel,
            'data': data
        })
        
        # Process message based on type
        streams = None
        if msg_type == 'cc':
            streams = self._process_cc_message(channel, data)
        elif msg_type in ['note_on', 'note_off']:
            streams = self._process_note_message(msg_type, channel, data)
        elif msg_type == 'pressure':
            streams = self._process_pressure_message(channel, data)
        else:
            _log(f"[REJECTED] Unsupported message type: {msg_type}")
            
        if streams:
            if isinstance(streams, list):
                _log(f"[ROUTE] Sending {len(streams)} parameter streams to voices")
                for stream in streams:
                    # Use format_parameter_stream for consistent formatting
                    _log({
                        'value': stream['value'],
                        'target': stream['target'],
                        'channel': stream['channel'],
                        'stage': 'sending to voices'
                    })
                    voice_manager.process_parameter_stream(stream)
            else:
                # Use format_parameter_stream for consistent formatting
                _log({
                    'value': streams['value'],
                    'target': streams['target'],
                    'channel': streams['channel'],
                    'stage': 'sending to voices'
                })
                voice_manager.process_parameter_stream(streams)
        else:
            _log(f"[REJECTED] No route found for {msg_type} message")
        
    def _process_cc_message(self, channel, data):
        """Process CC message"""
        cc_num = data.get('number')
        
        # Fast whitelist check first
        if not self.route_cache.is_whitelisted('cc', cc_num, channel):
            _log(f"[REJECTED] CC {cc_num} not in whitelist for channel {channel}")
            return None
            
        _log(f"[ROUTE] Processing CC {cc_num}")
        route = self.route_cache.routes['controls'].get(f'cc.{cc_num}')
        if route:
            value = self._transform_value(data.get('value', 0), route)
            return self._create_parameter_stream(channel, route, value)
            
        _log(f"[REJECTED] No route found for CC {cc_num}")
        return None
        
    def _process_note_message(self, msg_type, channel, data):
        """Process note message"""
        results = []
        
        # Process the trigger (note_on/off)
        trigger_route = self.route_cache.routes['triggers'].get(f'per_key.{msg_type}')
        if trigger_route:
            _log(f"[ROUTE] Processing {msg_type} trigger")
            # For note_off triggers, include the note number since it's per_key
            if msg_type == 'note_off':
                value = {'note': data.get('note')}  # Include note number
            else:
                value = 1 if msg_type == 'note_on' else 0
            stream = self._create_parameter_stream(
                channel, trigger_route, value
            )
            results.append(stream)
        else:
            _log(f"[REJECTED] No trigger route found for {msg_type}")

        # Process note controls
        control_types = ['note_number', 'velocity']
        for control_type in control_types:
            # Only process velocity for note_on
            if control_type == 'velocity' and msg_type != 'note_on':
                continue
                
            # For note_off, only process note_number if there's a specific route for it
            if msg_type == 'note_off' and control_type == 'note_number':
                route = self.route_cache.routes['controls'].get(f'per_key.{control_type}')
                # Check if there's a specific route that handles note_off note_number
                if not any(r.get('source_event') == 'note_off' for r in route.values() if isinstance(r, dict)):
                    continue
                
            _log(f"[ROUTE] Processing {msg_type} {control_type}")
            
            # Explicitly handle note_number extraction
            if control_type == 'note_number':
                control_value = data.get('note')
            else:
                control_value = data.get(control_type)
            
            route = self.route_cache.routes['controls'].get(f'per_key.{control_type}')
            if route and control_value is not None:
                value = self._transform_value(control_value, route)
                stream = self._create_parameter_stream(channel, route, value)
                results.append(stream)
            else:
                _log(f"[REJECTED] No route found for {msg_type} {control_type}")
                
        # For note_on, also send any static values like waveform
        if msg_type == 'note_on':
            for key, route in self.route_cache.routes['controls'].items():
                if (route['source_type'] == 'per_key' and 
                    route['source_event'] == 'note_on' and
                    route.get('value')):
                    _log(f"[ROUTE] Processing static value for {route['path']}")
                    stream = self._create_parameter_stream(channel, route, route['value'])
                    results.append(stream)
            
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
            return value  # Pass through non-numeric values like waveform config
            
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
        
        _log({
            'result': value,
            'output_range': {
                'min': out_min,
                'max': out_max
            }
        })
        return value
        
    def _create_parameter_stream(self, channel, route, value):
        """Create parameter stream for voice manager"""
        # Extract module from path if not explicitly set
        module = route['module']
        if module is None:
            path_parts = route['path'].split('.')
            if path_parts:
                module = path_parts[0]

        stream = {
            'channel': channel,
            'target': {
                'module': module,
                'path': route['path'],
                'type': route['type'],
                'source_type': route['source_type']  # Include source_type for per_key handling
            },
            'value': value
        }
        
        # Use format_parameter_stream for consistent formatting
        _log({
            'value': value,
            'target': {
                'module': module,
                'path': route['path'],
                'type': route['type'],
                'source_type': route['source_type']
            },
            'channel': channel,
            'stage': 'created'
        })
        return stream
