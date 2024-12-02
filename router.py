"""
router.py - MIDI to Route Transformation

Transforms MIDI messages into routes using config paths.
Pure transformation with minimal state for continuous signal filtering.
Builds efficient lookup tables at init for fast message processing.
"""

import sys
from constants import ROUTER_DEBUG

def _log(message, module="ROUTER"):
    """Conditional logging function that respects ROUTER_DEBUG flag."""
    if not ROUTER_DEBUG:
        return
        
    RED = "\033[31m"  # For errors
    MAGENTA = "\033[35m"  # For rejected messages
    LIGHT_MAGENTA = "\033[95m"  # For all other messages
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        lines = []
        lines.append(f"Processing {message.get('type', 'unknown')} message:")
        lines.append(f"  channel: {message.get('channel', 'unknown')}")
        lines.append("  data:")
        for k, v in message.get('data', {}).items():
            lines.append(f"    {k}: {v}")
        print(f"\n{LIGHT_MAGENTA}[{module}]\n{''.join(lines)}{RESET}\n", file=sys.stderr)
    else:
        prefix = RED if "[ERROR]" in str(message) else \
                MAGENTA if "[REJECTED]" in str(message) else \
                LIGHT_MAGENTA
        print(f"{prefix}[{module}] {message}{RESET}", file=sys.stderr)

class RingBuffer:
    """Simple ring buffer implementation for CircuitPython"""
    def __init__(self, size):
        _log("Initializing RingBuffer with size: " + str(size))
        self.data = []  # Use a regular list instead of deque
        self.size = size
        
    def append(self, item):
        if len(self.data) >= self.size:
            self.data.pop(0)  # Remove oldest item if at capacity
        self.data.append(item)
        
    def popleft(self):
        if not self.data:
            return None
        return self.data.pop(0)
        
    def __len__(self):
        return len(self.data)

class PathProcessor:
    """Handles path parsing and routing table construction"""
    def __init__(self):
        _log("Initializing PathProcessor")
        self.route_info = {
            'note_on': {'routes': []},
            'note_off': {'routes': []},
            'pitch_bend': {'routes': []},
            'cc': {},
            'pressure': {'routes': []}
        }
        self.accepted_midi = set()

    def process_paths(self, paths):
        """Process path strings into routing tables"""
        _log("Processing paths...")
        if not isinstance(paths, str):
            _log(f"[ERROR] Expected string for paths, got: {type(paths)}")
            return
            
        for path in paths.strip().split('\n'):
            if not path.strip():
                continue
            
            _log(f"Processing path: {path}")
            parts = path.split('/')
            if len(parts) < 4:
                _log(f"[ERROR] Path too short: {path}")
                continue

            # Find scope index
            scope_idx = -1
            for i, part in enumerate(parts):
                if part in ('global', 'per_key'):
                    scope_idx = i
                    break
                    
            if scope_idx == -1:
                _log(f"[ERROR] No scope found in path: {path}")
                continue

            # Split path into sections
            route_parts = parts[:scope_idx]    # Everything before scope
            scope = parts[scope_idx]           # The scope itself
            value_parts = parts[scope_idx+1:-1]  # Everything after scope except MIDI type
            midi_type = parts[-1]              # MIDI type is always last

            # Build template
            template = '/'.join(route_parts) + '/{}'
            if value_parts:
                template += '/' + '/'.join(value_parts)
            _log(f"Built template: {template}")

            try:
                # Store route info
                _log(f"Adding route info - MIDI type: {midi_type}, Template: {template}, Scope: {scope}")
                self._add_route_info(midi_type, template, scope)
            except Exception as e:
                _log(f"[ERROR] Failed to add route info: {str(e)}")
                raise

    def _add_route_info(self, midi_type, template, scope):
        """Store route info with consistent structure"""
        _log(f"Adding route info for MIDI type: {midi_type}")
        _log(f"Creating route_info dict...")
        route_info = {
            'template': template,
            'scope': scope
        }
        _log(f"Created route_info: {route_info}")

        try:
            # Store based on MIDI type
            if midi_type.startswith('cc'):
                _log(f"Processing CC MIDI type: {midi_type}")
                cc_num = int(midi_type[2:])
                _log(f"Extracted CC number: {cc_num}")
                if cc_num not in self.route_info['cc']:
                    _log(f"Creating new CC entry for number {cc_num}")
                    self.route_info['cc'][cc_num] = {'routes': []}
                _log(f"Appending route info for CC {cc_num}")
                self.route_info['cc'][cc_num]['routes'].append(route_info)
                # Add both specific CC type and generic 'cc' type to accepted_midi
                self.accepted_midi.add(midi_type)  # e.g. 'cc70'
                self.accepted_midi.add('cc')       # generic 'cc' type
            else:
                _log(f"Processing non-CC MIDI type: {midi_type}")
                msg_type = None
                if midi_type == 'note_on':
                    msg_type = 'note_on'
                elif midi_type == 'note_off':
                    msg_type = 'note_off'
                elif midi_type == 'pitch_bend':
                    msg_type = 'pitch_bend'
                elif midi_type == 'pressure':
                    msg_type = 'pressure'
                elif midi_type == 'velocity':
                    msg_type = 'note_on'  # velocity comes with note_on
                elif midi_type == 'note_number':
                    msg_type = 'note_on'  # note_number comes with note_on
                
                _log(f"Determined message type: {msg_type}")
                if msg_type:
                    _log(f"Appending route info for {msg_type}")
                    self.route_info[msg_type]['routes'].append(route_info)
                    self.accepted_midi.add(msg_type)

            _log(f"Successfully added route info for {midi_type}")
            
        except Exception as e:
            _log(f"[ERROR] Exception in _add_route_info: {str(e)}")
            raise

class ValueProcessor:
    """Handles MIDI value processing and normalization"""
    
    # Filtering thresholds for continuous signals
    PITCH_BEND_THRESHOLD = 64    # For 14-bit values (0-16383)
    PRESSURE_THRESHOLD = 2       # For 7-bit values (0-127)
    TIMBRE_THRESHOLD = 2        # For 7-bit values (0-127)
    
    def __init__(self):
        _log("Initializing ValueProcessor")
        # State tracking for continuous controls
        self.last_value = {}  # channel -> {pitch_bend, pressure, timbre}

    def get_route_value(self, message, template):
        """Process MIDI message into appropriate route value"""
        msg_type = message['type']
        
        # Check if this route should have a value appended
        if template.endswith('/saw') or template.endswith('/triangle'):
            return None
            
        # Handle note_on without value specifier
        if msg_type == 'note_on' and template.endswith('/note_on'):
            return None
            
        # Handle note_number
        if 'note_number' in template:
            return message['data'].get('note')
            
        # Handle velocity with range
        if 'velocity' in template:
            raw_value = message['data'].get('velocity', 127)
            # Extract range from template
            range_parts = [part for part in template.split('/') if '-' in part]
            range_str = range_parts[0] if range_parts else None
            if range_str:
                return self.normalize_value(raw_value, range_str)
            return raw_value
            
        # Get raw value based on message type
        if msg_type == 'note_off':
            return None  # note_off doesn't need a value
        elif msg_type == 'pitch_bend':
            raw_value = message['data'].get('value', 8192)
        elif msg_type == 'pressure':
            raw_value = message['data'].get('value', 0)
        elif msg_type == 'cc':
            raw_value = message['data'].get('value', 0)
        else:
            return None

        # Extract range if present in template
        range_parts = [part for part in template.split('/') if '-' in part]
        range_str = range_parts[0] if range_parts else None

        # Return raw value if no range specified
        if not range_str or range_str == 'na':
            return raw_value

        return self.normalize_value(raw_value, range_str)

    def get_route_scope(self, message, scope):
        """Generate scope value from message using template"""
        if scope == 'global':
            return 'global'
            
        # For per_key scope, build V{note}.{channel} with X for missing data
        try:
            note = message['data'].get('note', 'XX')  # Use XX if note is missing
            channel = message.get('channel', 'X')     # Use X if channel is missing
            return f"V{note}.{channel}"
        except Exception as e:
            _log(f"[ERROR] Error creating per_key scope: {str(e)}")
            return "VXX.X"  # Fallback to completely unknown scope

    def should_process_message(self, message):
        """Check if a continuous controller message exceeds threshold"""
        msg_type = message['type']
        channel = message['channel']
        
        # Initialize channel state if needed
        if channel not in self.last_value:
            self.last_value[channel] = {
                'pitch_bend': 8192,  # Center position
                'pressure': 0,
                'timbre': 64        # Center position
            }
        
        # Get threshold and value based on message type
        if msg_type == 'pitch_bend':
            current = message['data']['value']
            threshold = self.PITCH_BEND_THRESHOLD
            state_key = 'pitch_bend'
        elif msg_type == 'pressure':
            current = message['data']['value']
            threshold = self.PRESSURE_THRESHOLD
            state_key = 'pressure'
        elif msg_type == 'cc' and message['data']['number'] == 74:  # Timbre
            current = message['data']['value']
            threshold = self.TIMBRE_THRESHOLD
            state_key = 'timbre'
        else:
            # Non-continuous messages always process
            return True
            
        # Check if change exceeds threshold
        last = self.last_value[channel][state_key]
        if abs(current - last) < threshold:
            return False
            
        # Update state and process message
        self.last_value[channel][state_key] = current
        return True

    def normalize_value(self, value, range_str):
        """Normalize value to specified range"""
        try:
            low, high = map(float, range_str.split('-'))
            
            # Handle different value ranges
            if 0 <= value <= 127:  # Standard MIDI
                return low + (value/127.0) * (high - low)
            elif 0 <= value <= 16383:  # Pitch bend
                return low + ((value-8192)/8192.0) * (high - low)
            
            return value
            
        except (ValueError, TypeError):
            return value

class RouteBuilder:
    """Builds routes from processed paths and MIDI values"""
    
    def __init__(self):
        _log("Initializing RouteBuilder")
    
    def create_route(self, template, scope_value, value=None):
        """
        Create route string from template and values
        template: module/interface parts from path
        scope_value: 'global' or 'V{note}.{channel}'
        value: final value or LFO name to be applied
        """
        try:
            _log(f"Creating route with template: {template}, scope_value: {scope_value}, value: {value}")
            
            # Format the template with the scope value
            formatted_path = template.format(scope_value)
            _log(f"Formatted path: {formatted_path}")
            
            # Split into parts and remove any range or value type specifiers
            parts = []
            for part in formatted_path.split('/'):
                if '-' not in part and part not in ('velocity', 'note_number'):
                    parts.append(part)
            
            # Add value if provided
            if value is not None:
                if isinstance(value, float):
                    # Format floats to reasonable precision
                    parts.append(f"{value:.3f}")
                else:
                    parts.append(str(value))
            
            # Join all parts with forward slashes
            result = '/'.join(parts)
            _log(f"Created route: {result}")
            return result
            
        except Exception as e:
            _log(f"[ERROR] Failed to create route: {str(e)}")
            raise

    def create_routes_for_message(self, message, path_info, value_processor):
        """
        Generate all routes for a given MIDI message using processed path info
        Returns list of route strings
        """
        routes = []
        msg_type = message['type']
        
        # Get relevant route information based on message type
        if msg_type.startswith('cc'):
            cc_num = message['data']['number']
            route_infos = path_info['cc'].get(cc_num, {}).get('routes', [])
        else:
            route_infos = path_info[msg_type].get('routes', [])
            
        # Process each matching route
        for route_info in route_infos:
            try:
                # Get scope value (global or voice-specific)
                scope_value = value_processor.get_route_scope(message, route_info['scope'])
                
                # Get value based on route template
                value = value_processor.get_route_value(message, route_info['template'])
                    
                # Create and add route
                route = self.create_route(route_info['template'], scope_value, value)
                routes.append(route)
            except Exception as e:
                _log(f"[ERROR] Failed to create route: {str(e)}")
                continue
            
        return routes

class Router:
    """MIDI to Route Transformation System"""
    BUFFER_SIZE = 64  # Ring buffer size - adjust based on expected message rate and processing time

    def __init__(self, paths):
        """Initialize router with paths configuration"""
        _log("Initializing Router...")
        _log(f"Received paths type: {type(paths)}")
        
        try:
            # Initialize components
            _log("Creating PathProcessor...")
            self.path_processor = PathProcessor()
            
            _log("Creating ValueProcessor...")
            self.value_processor = ValueProcessor()
            
            _log("Creating RouteBuilder...")
            self.route_builder = RouteBuilder()
            
            _log("Creating RingBuffer...")
            self.message_buffer = RingBuffer(self.BUFFER_SIZE)
            
            # Process paths
            _log("Processing paths...")
            self.path_processor.process_paths(paths)
            
            _log("Router initialization complete")
            self._log_routing_tables()
            
        except Exception as e:
            _log(f"[ERROR] Router initialization failed: {str(e)}")
            raise

    def _log_routing_tables(self):
        """Log the created routing tables"""
        _log("\nRouting Tables Created:")
        
        # Helper function to format routes
        def format_routes(routes):
            return '\n'.join([f"          {route}" for route in routes])
            
        # Helper function to format CC routes
        def format_cc_routes(cc_info):
            formatted = []
            for cc_num, info in sorted(cc_info.items()):
                routes_str = format_routes(route['template'] + ' (' + route['scope'] + ')' 
                                        for route in info['routes'])
                formatted.append(f"      CC {cc_num}:\n{routes_str}")
            return '\n'.join(formatted)
        
        # Format and log each message type
        for msg_type, info in self.path_processor.route_info.items():
            _log(f"    {msg_type.upper()}:")
            
            if msg_type == 'cc':
                _log(format_cc_routes(info))
            else:
                routes = [route['template'] + ' (' + route['scope'] + ')' 
                         for route in info['routes']]
                if routes:
                    _log(format_routes(routes))
                else:
                    _log("          No routes configured")

    def _should_process_message(self, message):
        """Determine if message should be processed"""
        msg_type = message['type']
        
        # For CC messages, check if we have routes for this CC number
        if msg_type == 'cc':
            cc_num = message['data']['number']
            if cc_num not in self.path_processor.route_info['cc']:
                _log(f"[REJECTED] No routes configured for CC number: {cc_num}")
                return False
            return self.value_processor.should_process_message(message)
            
        # For other message types, check if they're in accepted_midi
        if msg_type not in self.path_processor.accepted_midi:
            _log(f"[REJECTED] Message type not in config: {msg_type}")
            return False

        return self.value_processor.should_process_message(message)

    def process_message(self, message, voice_manager=None):
        """Transform MIDI message to routes"""
        if not self._should_process_message(message):
            return

        # Queue message
        self.message_buffer.append((message, voice_manager))
        _log(f"Message queued. Buffer size: {len(self.message_buffer)}/{self.BUFFER_SIZE}")
        
        # Process all buffered messages
        while len(self.message_buffer):
            msg, vm = self.message_buffer.popleft()
            
            # Generate routes from message
            routes = self.route_builder.create_routes_for_message(
                msg,
                self.path_processor.route_info,
                self.value_processor
            )
            
            # Send routes to voice manager
            if vm is not None:
                for route in routes:
                    _log(f"Sending route: {route}")
                    vm.handle_route(route)
