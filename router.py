"""
router.py - MIDI to Route Transformation

Transforms MIDI messages into routes using config paths.
Uses paths.py for path processing and value handling.
Maintains efficient message processing with minimal state.
"""

import sys
import time
from constants import ROUTER_DEBUG
from timing import timing_stats, TimingContext
from paths import PathProcessor, ValueProcessor

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
        _log(f"Buffer size: {len(self.data)}/{self.size}")
        
    def popleft(self):
        if not self.data:
            return None
        item = self.data.pop(0)
        _log(f"Buffer size: {len(self.data)}/{self.size}")
        return item
        
    def pop_all(self):
        """Remove and return all messages in buffer"""
        if not self.data:
            return []
        messages = self.data[:]
        count = len(messages)
        self.data.clear()
        _log(f"Processed {count} messages from buffer")
        return messages
        
    def __len__(self):
        return len(self.data)

    def get_buffer_state(self):
        """Get a summary of current buffer contents"""
        if not self.data:
            return "empty"
        
        counts = {}
        for msg, _ in self.data:
            msg_type = msg['type']
            counts[msg_type] = counts.get(msg_type, 0) + 1
            
        state = []
        for msg_type, count in counts.items():
            state.append(f"{msg_type}:{count}")
        return f"{len(self.data)}/{self.size} [{', '.join(state)}]"

class RouteBuilder:
    """Builds routes from processed paths and MIDI values"""
    
    def __init__(self):
        _log("Initializing RouteBuilder")
    
    def create_route(self, template, scope_value, value=None, timing_id=None):
        """
        Create route string from template and values
        template: module/interface parts from path
        scope_value: 'global' or 'V{note}.{channel}'
        value: final value or LFO name to be applied
        timing_id: optional timing ID to track through the chain
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
            
            # For CircuitPython compatibility, return route and timing_id separately
            return (result, timing_id)
            
        except Exception as e:
            _log(f"[ERROR] Failed to create route: {str(e)}")
            raise

    def process_note_bundle(self, message, bundle, value_processor, timing_id):
        """Process a note message using pre-computed route templates"""
        routes = []
        
        # Get common data once
        channel = message.get('channel', 'X')
        note = message['data'].get('note', 'XX')
        
        # Process templates in original order
        for template in bundle.templates:
            try:
                # Get scope value
                scope_value = 'global' if template.scope == 'global' else f"V{note}.{channel}"
                
                # Get value if needed
                value = None
                if template.needs_value:
                    if template.is_note_number:
                        value = note
                    elif template.is_velocity and message['type'] == 'note_on':
                        value = message['data'].get('velocity', 127)
                        if template.range_str:  # Normalize if range specified
                            value = value_processor.normalize_value(value, template.range_str, message['type'])
                
                # Create route using pre-computed parts
                if value is not None:
                    route = f"{template.prefix.format(scope_value)}/{value}"
                else:
                    route = template.prefix.format(scope_value)
                
                routes.append((route, timing_id))
                
            except Exception as e:
                _log(f"[ERROR] Failed to create route: {str(e)}")
                continue
                
        return routes

    def create_routes_for_message(self, message, path_info, value_processor):
        """
        Generate all routes for a given MIDI message using processed path info
        Returns list of (route, timing_id) tuples
        """
        routes = []
        msg_type = message['type']
        timing_id = message.get('timing_id')
        
        # Use optimized bundle processing for note messages
        if msg_type == 'note_on':
            return self.process_note_bundle(message, path_info.note_on_bundle, value_processor, timing_id)
        elif msg_type == 'note_off':
            return self.process_note_bundle(message, path_info.note_off_bundle, value_processor, timing_id)
        
        # Use standard processing for other messages
        if msg_type.startswith('cc'):
            cc_num = message['data']['number']
            route_infos = path_info.route_info['cc'].get(cc_num, {}).get('routes', [])
        else:
            route_infos = path_info.route_info[msg_type].get('routes', [])
            
        # Process each matching route
        for route_info in route_infos:
            try:
                # Get scope value (global or voice-specific)
                scope_value = value_processor.get_route_scope(message, route_info['scope'])
                
                # Get value based on route template
                value = value_processor.get_route_value(message, route_info['template'])
                    
                # Create and add route
                route_tuple = self.create_route(route_info['template'], scope_value, value, timing_id)
                routes.append(route_tuple)
            except Exception as e:
                _log(f"[ERROR] Failed to create route: {str(e)}")
                continue
            
        return routes

class Router:
    """MIDI to Route Transformation System"""
    BUFFER_SIZE = 64  # Ring buffer size - adjust based on expected message rate and processing time
    BATCH_PROCESS_INTERVAL = 0.01  # Process buffer every 10ms

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
            
            # Initialize batch processing state
            self.last_process_time = time.monotonic()
            
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

    def process_message(self, message, voice_manager=None, high_priority=False):
        """Transform MIDI message to routes"""
        # Start timing as soon as we receive the message
        with TimingContext(timing_stats, "router", message.get('timing_id')):
            try:
                msg_type = message['type']
                channel = message.get('channel')
                _log(f"Processing {msg_type} message from channel {channel}")

                # First validate the message
                if not self._should_process_message(message):
                    return

                # Handle note_on, note_off and associated messages immediately
                if msg_type in ('note_on', 'note_off') or high_priority:
                    buffer_state = self.message_buffer.get_buffer_state()
                    _log(f"BUFFER SKIP: {msg_type} ch:{channel} (Buffer: {buffer_state})")
                    self._process_single_message(message, voice_manager)
                    return

                # Queue other valid messages
                buffer_state = self.message_buffer.get_buffer_state()
                _log(f"BUFFER ADD: {msg_type} ch:{channel} (Buffer: {buffer_state})")
                self.message_buffer.append((message, voice_manager))
                
                # Check if it's time to process the buffer
                current_time = time.monotonic()
                if current_time - self.last_process_time >= self.BATCH_PROCESS_INTERVAL:
                    batch_start = time.monotonic()
                    self._process_buffer(voice_manager)
                    batch_time = (time.monotonic() - batch_start) * 1000
                    _log(f"Batch processing took {batch_time:.3f}ms")
                    self.last_process_time = current_time

            except Exception as e:
                _log(f"[ERROR] Message processing failed: {str(e)}")

    def _process_buffer(self, voice_manager):
        """Process all messages in buffer"""
        messages = self.message_buffer.pop_all()
        if not messages:
            return
            
        _log(f"Processing batch of {len(messages)} messages:")
        for msg, _ in messages:
            _log(f"- {msg['type']} from channel {msg.get('channel')}")
        
        for msg, vm in messages:
            self._process_single_message(msg, vm or voice_manager)

    def _process_single_message(self, message, voice_manager):
        """Process a single message and generate routes"""
        try:
            # Generate routes from message
            route_tuples = self.route_builder.create_routes_for_message(
                message,
                self.path_processor,  # Pass entire processor to access bundles
                self.value_processor
            )
            
            # Send routes to voice manager
            if voice_manager is not None:
                for route, timing_id in route_tuples:
                    _log(f"Sending route: {route}")
                    voice_manager.handle_route(route, timing_id)
            
        except Exception as e:
            _log(f"[ERROR] Failed to process message: {str(e)}")
