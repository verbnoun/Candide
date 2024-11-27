"""
router.py - MIDI to Route Transformation

Transforms MIDI messages into routes using config paths.
Maintains path schema integrity when creating routes.
Includes message culling, continuous signal filtering, and ring buffer.
Pure transformation with minimal state for filtering.
"""

import sys
from collections import deque
from constants import ROUTER_DEBUG

# Ring buffer size - adjust based on expected message rate and processing time
BUFFER_SIZE = 64  # Conservative size for Pico

# Filtering thresholds for continuous signals
PITCH_BEND_THRESHOLD = 64    # For 14-bit values (0-16383)
PRESSURE_THRESHOLD = 2       # For 7-bit values (0-127)
TIMBRE_THRESHOLD = 2        # For 7-bit values (0-127)

def _log(message, module="ROUTER"):
    """Conditional logging function that respects ROUTER_DEBUG flag."""
    if not ROUTER_DEBUG:
        return
        
    RED = "\033[31m"  # For errors
    MAGENTA = "\033[35m"  # For rejected messages
    LIGHT_MAGENTA = "\033[95m"  # For all other messages
    RESET = "\033[0m"
    
    def format_midi_message(msg_type, channel, data):
        """Format MIDI message with nice indentation."""
        lines = []
        lines.append(f"Processing {msg_type} message:")
        lines.append(f"  channel: {channel}")
        lines.append("  data:")
        for k, v in data.items():
            lines.append(f"    {k}: {v}")
        return "\n".join(lines)

    if isinstance(message, dict):
        formatted = format_midi_message(
            message.get('type', 'unknown'),
            message.get('channel', 'unknown'),
            message.get('data', {})
        )
        print(f"\n{LIGHT_MAGENTA}[{module}]\n{formatted}{RESET}\n", file=sys.stderr)
    elif isinstance(message, str):
        if "[ERROR]" in message:
            color = RED
        elif "[REJECTED]" in message:
            color = MAGENTA
        else:
            color = LIGHT_MAGENTA
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)
    else:
        print(f"{LIGHT_MAGENTA}[{module}] {message}{RESET}", file=sys.stderr)

# Ring buffer size - adjust based on expected message rate and processing time
BUFFER_SIZE = 64  # Conservative size for Pico

class RingBuffer:
    """Simple ring buffer implementation for CircuitPython"""
    def __init__(self, size):
        self.data = []  # Use a regular list instead of deque
        self.size = size
        
    def append(self, item):
        if len(self.data) >= self.size:
            self.data.pop(0)  # Remove oldest item if at capacity
        self.data.append(item)
        
    def popleft(self):
        if not self.data:
            return None
        return self.data.pop(0)  # Remove and return first item
        
    def __len__(self):
        return len(self.data)


class Router:
    def __init__(self, paths):
        """Initialize router with a set of paths from config"""
        
        _log("Splitting paths ...")
        # Split paths and filter out empty lines
        self.paths = [p.strip() for p in paths.strip().split('\n') if p.strip()]

        _log("Initializing ring buffer ...")
        # Initialize ring buffer for pre-normalized messages
        self.message_buffer = RingBuffer(BUFFER_SIZE)

        _log("Building loopup of accepted message types")
        # Build lookup of accepted message types from paths
        self.accepted_messages = self._build_message_lookup()

        _log("Initializing state tracking...")
        # State tracking for continuous signal filtering
        self.continuous_state = {}
        
        _log(f"Initialized router with {len(self.paths)} paths")

    def _build_message_lookup(self):
        """Build lookup of accepted message types from paths"""
        accepted = {
            'note_on': set(),      # Will contain note sources (velocity, note_number)
            'note_off': False,     # Simple flag
            'pitch_bend': False,   # Simple flag
            'pressure': False,     # Simple flag
            'cc': set()           # Will contain CC numbers
        }
        
        for path in self.paths:
            parts = path.split('/')
            source = parts[-1]
            
            if source in ['velocity', 'note_number', 'note_on']:
                accepted['note_on'].add(source)
            elif source == 'note_off':
                accepted['note_off'] = True
            elif source == 'pitch_bend':
                accepted['pitch_bend'] = True
            elif source == 'channel_pressure':
                accepted['pressure'] = True
            elif source.startswith('cc'):
                try:
                    cc_num = int(source[2:])
                    accepted['cc'].add(cc_num)
                except ValueError:
                    _log(f"[ERROR] Invalid CC number in path: {source}")
                    
        return accepted

    def _should_cull_message(self, message):
        """Check if message should be culled based on config paths"""
        msg_type = message['type']
        
        if msg_type == 'note_on':
            return not self.accepted_messages['note_on']
        elif msg_type == 'note_off':
            return not self.accepted_messages['note_off']
        elif msg_type == 'pitch_bend':
            return not self.accepted_messages['pitch_bend']
        elif msg_type == 'pressure':
            return not self.accepted_messages['pressure']
        elif msg_type == 'cc':
            cc_num = message['data']['number']
            return cc_num not in self.accepted_messages['cc']
                
        return True  # Cull unknown message types

    def _should_filter_continuous(self, message):
        """Check if continuous signal should be filtered based on change threshold"""
        msg_type = message['type']
        channel = message['channel']
        
        # Initialize state tracking for this channel if needed
        if channel not in self.continuous_state:
            self.continuous_state[channel] = {
                'pitch_bend': 8192,  # Center value
                'pressure': 0,
                'cc74': 64,         # Center value for timbre
            }
            
        if msg_type == 'pitch_bend':
            current = message['data']['value']
            prev = self.continuous_state[channel]['pitch_bend']
            if abs(current - prev) < PITCH_BEND_THRESHOLD:
                return True
            self.continuous_state[channel]['pitch_bend'] = current
            
        elif msg_type == 'pressure':
            current = message['data']['value']
            prev = self.continuous_state[channel]['pressure']
            if abs(current - prev) < PRESSURE_THRESHOLD:
                return True
            self.continuous_state[channel]['pressure'] = current
            
        elif msg_type == 'cc' and message['data']['number'] == 74:
            current = message['data']['value']
            prev = self.continuous_state[channel]['cc74']
            if abs(current - prev) < TIMBRE_THRESHOLD:
                return True
            self.continuous_state[channel]['cc74'] = current
            
        return False

    def normalize_value(self, value, range_str):
        """Convert MIDI value to normalized range"""
        if range_str == 'na':
            return value
            
        try:
            low, high = map(float, range_str.split('-'))
            
            # Handle different MIDI value ranges
            if value >= 0 and value <= 127:  # Standard MIDI CC/velocity
                normalized = low + (value/127.0) * (high - low)
            elif value >= 0 and value <= 16383:  # Pitch bend
                normalized = low + ((value-8192)/8192.0) * (high - low)
            else:
                normalized = value
                
            _log(f"Normalized value {value} to {normalized} (range: {range_str})")
            return normalized
            
        except ValueError:
            # Not a range string, might be a waveform type or other value
            return range_str

    def create_route_from_path(self, path, channel, value, note=None):
        """Create route from path, replacing scope with target and range/source with value"""
        parts = path.split('/')
        
        if len(parts) < 4:  # Ensure minimum path structure
            _log(f"[ERROR] Invalid path structure: {path}")
            return None
            
        # Handle global vs per_key scope
        if parts[1] == 'global':
            target = 'global'
        else:
            if note is None:  # Non-note messages still need a note target
                _log("[REJECTED] Missing note for per-key route")
                return None
            target = f"{note}.{channel}"
            
        # Build route parts safely
        route_parts = [parts[0]]  # signal chain
        route_parts.append(target)  # target (replaces scope)
        
        # Add middle parts (if any exist)
        if len(parts) > 4:
            route_parts.extend(parts[2:-2])
            
        # Special handling for waveform
        if parts[2] == 'waveform':
            route_parts.append(parts[2])  # Add 'waveform'
            route_parts.append(parts[3])  # Add waveform type
        else:
            # Use provided value or path default if present
            if value is None and len(parts) > 5:
                value = parts[5]
            route_parts.append(str(value))
        
        route = '/'.join(route_parts)
        _log(f"Created route: {route}")
        return route

    def process_message(self, message, voice_manager):
        """Transform MIDI message into routes using path schema"""
        # Fast path: Validation and filtering
        if self._should_cull_message(message):
            _log(f"[REJECTED] Culled message type: {message['type']}")
            return
            
        if self._should_filter_continuous(message):
            _log(f"[REJECTED] Filtered continuous signal: {message['type']}")
            return
            
        # Add to buffer if passes fast checks
        if len(self.message_buffer) < BUFFER_SIZE:
            self.message_buffer.append((message, voice_manager))
            _log(f"Message queued. Buffer size: {len(self.message_buffer)}/{BUFFER_SIZE}")
        else:
            _log("[REJECTED] Buffer full, dropping message")
            return
            
        # Process a message from the buffer
        self._process_from_buffer()

    def _process_from_buffer(self):
        """Process one message from the buffer - handles normalization and routing"""
        if not self.message_buffer:
            return
            
        message, voice_manager = self.message_buffer.popleft()
        msg_type = message['type']
        channel = message['channel']
        routes = []

        _log(message)  # Log message being processed

        if msg_type == 'note_on':
            note_num = message['data']['note']
            note_name = f"C{note_num}"  # TODO: proper note name conversion
            velocity = message['data']['velocity']
            
            for path in self.paths:
                parts = path.split('/')
                source = parts[-1]
                range_str = parts[-2]
                
                if source == 'note_number':
                    value = self.normalize_value(note_num, range_str)
                    route = self.create_route_from_path(path, channel, value, note_name)
                    if route:
                        routes.append(route)
                        
                elif source == 'velocity':
                    value = self.normalize_value(velocity, range_str)
                    route = self.create_route_from_path(path, channel, value, note_name)
                    if route:
                        routes.append(route)
                        
                elif source == 'note_on':
                    route = self.create_route_from_path(path, channel, None, note_name)
                    if route:
                        routes.append(route)
                        
                elif source == 'pitch_bend':
                    value = self.normalize_value(message['data']['initial_pitch_bend'], range_str)
                    route = self.create_route_from_path(path, channel, value, note_name)
                    if route:
                        routes.append(route)
                        
                elif source == 'channel_pressure':
                    value = self.normalize_value(message['data']['initial_pressure'], range_str)
                    route = self.create_route_from_path(path, channel, value, note_name)
                    if route:
                        routes.append(route)
                        
                elif source == 'cc74':
                    value = self.normalize_value(message['data']['initial_timbre'], range_str)
                    route = self.create_route_from_path(path, channel, value, note_name)
                    if route:
                        routes.append(route)

        elif msg_type == 'note_off':
            note_name = f"C{message['data']['note']}"  # TODO: proper note name conversion
            for path in self.paths:
                parts = path.split('/')
                source = parts[-1]
                if source == 'note_off':
                    route = self.create_route_from_path(path, channel, None, note_name)
                    if route:
                        routes.append(route)

        elif msg_type == 'pitch_bend':
            value = message['data']['value']
            for path in self.paths:
                if 'pitch_bend' in path.split('/')[-1]:
                    parts = path.split('/')
                    range_str = parts[-2]
                    value = self.normalize_value(value, range_str)
                    route = self.create_route_from_path(path, channel, value)
                    if route:
                        routes.append(route)

        elif msg_type == 'pressure':
            value = message['data']['value']
            for path in self.paths:
                if 'channel_pressure' in path.split('/')[-1]:
                    parts = path.split('/')
                    range_str = parts[-2]
                    value = self.normalize_value(value, range_str)
                    route = self.create_route_from_path(path, channel, value)
                    if route:
                        routes.append(route)

        elif msg_type == 'cc':
            cc_num = message['data']['number']
            value = message['data']['value']
            for path in self.paths:
                if f'cc{cc_num}' in path.split('/')[-1]:
                    parts = path.split('/')
                    range_str = parts[-2]
                    value = self.normalize_value(value, range_str)
                    route = self.create_route_from_path(path, channel, value)
                    if route:
                        routes.append(route)

        # Log route generation results
        if routes:
            _log(f"Generated {len(routes)} routes")
        else:
            _log(f"[REJECTED] No routes generated for {msg_type} message")

        # Send each generated route to voice manager
        for route in routes:
            _log(f"Sending route to voice manager: {route}")
            voice_manager.handle_route(route)