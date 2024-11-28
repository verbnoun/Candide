"""
router.py - MIDI to Route Transformation

Transforms MIDI messages into routes using config paths.
Pure transformation with minimal state for continuous signal filtering.
Builds efficient lookup tables at init for fast message processing.
"""

import sys
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

class Router:
    def __init__(self, paths):
        """Initialize router with a set of paths from config"""
        _log("Building routing tables...")
        
        # Main routing lookup tables
        self.route_info = {
            'note_on': {},      # note_number/velocity -> {route_template, range}
            'note_off': None,   # Just template if supported
            'pitch_bend': {},   # template and range if supported
            'pressure': {},     # template and range if supported
            'cc': {}           # cc_number -> {route_template, range}
        }
        
        # Build fast lookup tables from paths
        for path in paths.strip().split('\n'):
            if not path.strip():
                continue
                
            parts = path.split('/')
            if len(parts) < 4:
                continue
                
            # Get key elements
            source = parts[-1]
            range_str = parts[-2]
            route_template = '/'.join(parts[:-2])
            
            # Sort into appropriate lookup table
            if source in ('note_number', 'velocity', 'note_on'):
                self.route_info['note_on'][source] = {
                    'template': route_template,
                    'range': range_str
                }
            elif source == 'note_off':
                self.route_info['note_off'] = route_template
            elif source == 'pitch_bend':
                self.route_info['pitch_bend'] = {
                    'template': route_template,
                    'range': range_str
                }
            elif source == 'channel_pressure':
                self.route_info['pressure'] = {
                    'template': route_template,
                    'range': range_str
                }
            elif source.startswith('cc'):
                try:
                    cc_num = int(source[2:])
                    self.route_info['cc'][cc_num] = {
                        'template': route_template,
                        'range': range_str
                    }
                except ValueError:
                    continue

        # Initialize ring buffer
        self.message_buffer = RingBuffer(BUFFER_SIZE)
        
        # Minimal state for continuous signal filtering
        self.last_value = {}  # channel -> {pitch_bend, pressure, timbre}
        
        _log("Router initialized")

    def _should_process(self, message):
        """Quick check if message should be processed based on lookup tables"""
        msg_type = message['type']
        
        if msg_type == 'note_on':
            return bool(self.route_info['note_on'])
        elif msg_type == 'note_off':
            return self.route_info['note_off'] is not None
        elif msg_type == 'pitch_bend':
            return bool(self.route_info['pitch_bend'])
        elif msg_type == 'pressure':
            return bool(self.route_info['pressure'])
        elif msg_type == 'cc':
            return message['data']['number'] in self.route_info['cc']
            
        return False

    def _check_continuous(self, message):
        """Check if continuous controller change exceeds threshold"""
        msg_type = message['type']
        channel = message['channel']
        
        # Initialize channel state if needed
        if channel not in self.last_value:
            self.last_value[channel] = {
                'pitch_bend': 8192,  # Center
                'pressure': 0,
                'timbre': 64  # Center
            }
        
        current = None
        threshold = None
        state_key = None
        
        if msg_type == 'pitch_bend':
            current = message['data']['value']
            threshold = PITCH_BEND_THRESHOLD
            state_key = 'pitch_bend'
        elif msg_type == 'pressure':
            current = message['data']['value']
            threshold = PRESSURE_THRESHOLD
            state_key = 'pressure'
        elif msg_type == 'cc' and message['data']['number'] == 74:  # timbre
            current = message['data']['value']
            threshold = TIMBRE_THRESHOLD
            state_key = 'timbre'
            
        if current is not None:
            last = self.last_value[channel][state_key]
            if abs(current - last) < threshold:
                return False
            self.last_value[channel][state_key] = current
            
        return True

    def _normalize(self, value, range_str):
        """Normalize value based on range"""
        if range_str == 'na' or '-' not in range_str:
            return value
            
        try:
            low, high = map(float, range_str.split('-'))
            
            if 0 <= value <= 127:  # Standard MIDI
                return low + (value/127.0) * (high - low)
            elif 0 <= value <= 16383:  # Pitch bend
                return low + ((value-8192)/8192.0) * (high - low)
            
            return value
        except ValueError:
            return value

    def _create_route(self, template, channel, value):
        """Create route from template and value"""
        parts = [template.split('/')[0]]  # Start with signal chain
        parts.append(parts[0])  # Add signal chain again for voice identifier
        
        # Handle per_key vs global paths
        template_parts = template.split('/')
        if 'per_key' in template_parts:
            parts.append('per_key')
            parts.append(str(channel))
            # Add remaining parts excluding signal chain, per_key, and global
            parts.extend([p for p in template_parts[1:] if p not in ('per_key', 'global')])
        else:  # global scope
            parts.append('global')
            # Add remaining parts excluding signal chain, per_key, and global
            parts.extend([p for p in template_parts[1:] if p not in ('per_key', 'global')])
        
        # Add the value
        parts.append(str(value))
        
        return '/'.join(parts)

    def process_message(self, message, voice_manager):
        """Transform MIDI message to route"""
        # Fast check - do we handle this message type?
        if not self._should_process(message):
            _log(f"[REJECTED] Message type not in config: {message['type']}")
            return

        # Check continuous signal threshold
        if message['type'] in ('pitch_bend', 'pressure') or \
           (message['type'] == 'cc' and message['data']['number'] == 74):
            if not self._check_continuous(message):
                _log(f"[REJECTED] Change below threshold: {message['type']}")
                return

        # Add to buffer
        self.message_buffer.append((message, voice_manager))
        _log(f"Message queued. Buffer size: {len(self.message_buffer)}/{BUFFER_SIZE}")
        
        # Process from buffer
        while len(self.message_buffer):
            msg, vm = self.message_buffer.popleft()
            routes = []
            
            if msg['type'] == 'note_on':
                if 'note_number' in self.route_info['note_on']:
                    info = self.route_info['note_on']['note_number']
                    value = self._normalize(msg['data']['note'], info['range'])
                    routes.append(self._create_route(info['template'], msg['channel'], value))
                    
                if 'velocity' in self.route_info['note_on']:
                    info = self.route_info['note_on']['velocity']
                    value = self._normalize(msg['data']['velocity'], info['range'])
                    routes.append(self._create_route(info['template'], msg['channel'], value))
                    
            elif msg['type'] == 'note_off':
                if self.route_info['note_off']:
                    routes.append(self._create_route(self.route_info['note_off'], 
                                                   msg['channel'], 
                                                   msg['data']['note']))
                    
            elif msg['type'] == 'pitch_bend':
                if self.route_info['pitch_bend']:
                    info = self.route_info['pitch_bend']
                    value = self._normalize(msg['data']['value'], info['range'])
                    routes.append(self._create_route(info['template'], msg['channel'], value))
                    
            elif msg['type'] == 'pressure':
                if self.route_info['pressure']:
                    info = self.route_info['pressure']
                    value = self._normalize(msg['data']['value'], info['range'])
                    routes.append(self._create_route(info['template'], msg['channel'], value))
                    
            elif msg['type'] == 'cc':
                cc_num = msg['data']['number']
                if cc_num in self.route_info['cc']:
                    info = self.route_info['cc'][cc_num]
                    value = self._normalize(msg['data']['value'], info['range'])
                    routes.append(self._create_route(info['template'], msg['channel'], value))

            # Send routes to voice manager
            for route in routes:
                _log(f"Sending route: {route}")
                vm.handle_route(route)