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
        
        # Accepted MIDI types set
        self.accepted_midi = set()
        
        # Main routing lookup tables
        self.route_info = {
            'note_on': {},
            'note_off': None
        }
        
        # Initialize ring buffer
        self.message_buffer = RingBuffer(BUFFER_SIZE)
        
        # Minimal state for continuous signal filtering
        self.last_value = {}  # channel -> {pitch_bend, pressure, timbre}
        
        # Build routing tables
        self._build_routing_tables(paths)
        
        # Log created tables
        self._log_routing_tables()
        
        _log("Router initialized")
        
    def _build_routing_tables(self, paths):
        """Build lookup tables from config paths"""
        for path in paths.strip().split('\n'):
            if not path.strip() or len(path.split('/')) < 4:
                continue
                
            # Work backwards through parts
            parts_iter = reversed(path.split('/'))
            
            # Check last value for default
            last = next(parts_iter)
            try:
                default = float(last)
                source = next(parts_iter)
            except ValueError:
                default = None
                source = last
                
            # Get range and check for special cases
            range_str = next(parts_iter)
            has_trigger = 'trigger' in range_str
                
            # Build template from remaining parts
            template_parts = []
            
            # Only add non-numeric range_str to template if it's not a waveform type
            if not range_str.replace('.', '').replace('-', '').isdigit() and \
            not has_trigger and \
            'waveform' not in path:
                template_parts.append(range_str)
            
            template_parts.extend(reversed(list(parts_iter)))
            route_template = '/'.join(template_parts)
            
            # Sort into appropriate lookup table
            if source == 'note_number':
                self.route_info['note_on']['note_number'] = {
                    'template': route_template,
                    'range': 'na'
                }
                self.accepted_midi.add('note_on')
            elif source == 'velocity':
                self.route_info['note_on']['velocity'] = {
                    'template': route_template,
                    'range': range_str
                }
                self.accepted_midi.add('note_on')
            elif source == 'note_on':
                key = 'trigger' if has_trigger else 'waveform'
                if has_trigger:
                    self.route_info['note_on'][key] = {
                        'template': route_template,
                        'range': 'na'
                    }
                else:
                    # For waveform, store wave type but don't add to template
                    self.route_info['note_on'][key] = {
                        'template': route_template,
                        'wave_type': range_str,
                        'range': 'na'
                    }
                self.accepted_midi.add('note_on')
            elif source == 'note_off':
                if has_trigger:
                    self.route_info['note_off'] = {
                        'trigger': {
                            'template': route_template,
                            'range': 'na'
                        }
                    }
                    self.accepted_midi.add('note_off')
            elif source == 'pitch_bend':
                if 'pitch_bend' not in self.route_info:
                    self.route_info['pitch_bend'] = {}
                self.route_info['pitch_bend'] = {
                    'template': route_template,
                    'range': range_str
                }
                self.accepted_midi.add('pitch_bend')
            elif source == 'channel_pressure':
                if 'pressure' not in self.route_info:
                    self.route_info['pressure'] = {}
                self.route_info['pressure'] = {
                    'template': route_template,
                    'range': range_str
                }
                self.accepted_midi.add('pressure')
            elif source.startswith('cc'):
                try:
                    if 'cc' not in self.route_info:
                        self.route_info['cc'] = {}
                    cc_num = int(source[2:])
                    self.route_info['cc'][cc_num] = {
                        'template': route_template,
                        'range': range_str
                    }
                    self.accepted_midi.add('cc')
                    _log(f"Added CC route for cc{cc_num}: template={route_template}, range={range_str}")
                except ValueError:
                    continue
                    
    def _log_routing_tables(self):
        """Log the created routing tables"""
        _log("\nRouting Tables Created:")
        for msg_type, routes in self.route_info.items():
            _log(f"  {msg_type}:")
            if isinstance(routes, dict):
                for key, info in routes.items():
                    _log(f"    {key}: {info}")
            else:
                _log(f"    {routes}")

    def _should_process(self, message):
        """Quick check if message should be processed based on whitelist"""
        return message['type'] in self.accepted_midi

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

    def _create_route(self, template, channel, value, note=None):
        """Create route from template and value
        
        For per_key routes, includes channel.note in identifier if note available
        Template already contains full path including signal chain and scope
        """
        parts = template.split('/')
        
        if 'per_key' in parts:
            # For per_key routes, inject identifier after per_key
            identifier = f"{channel}.{note}" if note is not None else str(channel)
            new_parts = []
            for part in parts:
                new_parts.append(part)
                if part == 'per_key':
                    new_parts.append(identifier)
            parts = new_parts
        
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
            
            # Get note number if available in message
            note = msg['data'].get('note', None)
            
            if msg['type'] == 'note_on':
                if 'note_number' in self.route_info['note_on']:
                    info = self.route_info['note_on']['note_number']
                    routes.append(self._create_route(
                        info['template'], 
                        msg['channel'], 
                        note,  # Note number as value
                        note   # Note number for identifier
                    ))
                    
                if 'velocity' in self.route_info['note_on']:
                    info = self.route_info['note_on']['velocity']
                    value = self._normalize(msg['data']['velocity'], info['range'])
                    routes.append(self._create_route(
                        info['template'], 
                        msg['channel'], 
                        value, 
                        note
                    ))
                
                if 'waveform' in self.route_info['note_on']:
                    info = self.route_info['note_on']['waveform']
                    routes.append(self._create_route(
                        info['template'],
                        msg['channel'],
                        info['wave_type'],  # Use stored wave type
                        note
                    ))
                    
                if 'trigger' in self.route_info['note_on']:
                    info = self.route_info['note_on']['trigger']
                    routes.append(self._create_route(
                        info['template'],
                        msg['channel'],
                        note,  # Note number as value
                        note   # Note number for identifier
                    ))
                    
            elif msg['type'] == 'note_off':
                if self.route_info['note_off'] and 'trigger' in self.route_info['note_off']:
                    info = self.route_info['note_off']['trigger']
                    note = msg['data'].get('note', None)
                    routes.append(self._create_route(
                        info['template'],     # 'amplifier/per_key/envelope/release' 
                        msg['channel'],       # For identifier construction
                        'trigger',            # Value from rightmost path element
                        note                  # For per_key identifier
                    ))
                    
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