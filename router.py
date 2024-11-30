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
            'note_on': {
                'note_number_routes': [],
                'velocity_routes': [],
                'trigger_routes': [],
                'waveform_routes': []
            },
            'note_off': {
                'trigger_routes': []
            },
            'cc': {},
            'pitch_bend': {'routes': []},
            'pressure': {'routes': []}
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

    def _store_route_info(self, msg_type, route_type, template, **kwargs):
        """Helper to store route info with consistent structure"""
        route_info = {
            'template': template,
            'range': kwargs.get('range', 'na')
        }
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key != 'range':
                route_info[key] = value
                
        # Initialize container if needed
        if msg_type == 'cc':
            cc_num = kwargs.get('cc_num')
            if cc_num not in self.route_info['cc']:
                self.route_info['cc'][cc_num] = {'routes': []}
            self.route_info['cc'][cc_num]['routes'].append(route_info)
        else:
            if route_type not in self.route_info[msg_type]:
                self.route_info[msg_type][route_type] = []
            self.route_info[msg_type][route_type].append(route_info)
            
        self.accepted_midi.add(msg_type)
        
    def _build_routing_tables(self, paths):
        """Build lookup tables from config paths"""
        # Initialize routing tables
        self.accepted_midi = set()
        self.route_info = {
            'note_on': {
                'note_number_routes': [],
                'velocity_routes': [],
                'trigger_routes': [],
                'waveform_routes': []
            },
            'note_off': {
                'trigger_routes': []
            },
            'cc': {},
            'pitch_bend': {'routes': []},
            'pressure': {'routes': []}
        }
        
        # Process each path
        for path in paths.strip().split('\n'):
            if not path.strip():
                continue
                
            parts = path.split('/')
            if len(parts) < 4:
                _log("[ERROR] Path too short (min 4 segments): {}".format(path))
                continue
                
            category = parts[0]
            if category == 'oscillator':
                _log("Processing oscillator path: {}".format(path))
                self._process_oscillator_path(path, parts)
            elif category == 'filter':
                _log("Processing filter path: {}".format(path))
                self._process_filter_path(path, parts)
            elif category == 'amplifier':
                _log("Processing amplifier path: {}".format(path))
                self._process_amplifier_path(path, parts)

    def _process_oscillator_path(self, path, parts):
        """Process oscillator category paths"""
        if 'frequency' in parts and 'note_number' in parts:
            _log("Adding note number frequency route")
            self._store_route_info(
                'note_on',
                'note_number_routes',
                path
            )
            
        if 'waveform' in parts:
            wave_idx = parts.index('waveform')
            if wave_idx + 1 < len(parts):
                wave_type = parts[wave_idx + 1]
                _log("Adding waveform route")
                self._store_route_info(
                    'note_on',
                    'waveform_routes',
                    path,
                    wave_type=wave_type
                )

    def _process_filter_path(self, path, parts):
        """Process filter category paths"""
        try:
            if 'frequency' in parts:
                range_str = parts[parts.index('frequency') + 1]
                cc_num = int(parts[-2][2:])
                _log("Adding filter frequency CC route")
                base_path = f"{parts[0]}/{parts[1]}/frequency"
                self._store_route_info(
                    'cc',
                    'routes',
                    base_path,
                    range=range_str,
                    cc_num=cc_num
                )
                
            if 'resonance' in parts:
                range_str = parts[parts.index('resonance') + 1]
                cc_num = int(parts[-2][2:])
                _log("Adding filter resonance CC route")
                base_path = f"{parts[0]}/{parts[1]}/resonance"
                self._store_route_info(
                    'cc',
                    'routes',
                    base_path,
                    range=range_str,
                    cc_num=cc_num
                )
        except (ValueError, IndexError):
            _log("[ERROR] Invalid filter path format: {}".format(path))

    def _process_amplifier_path(self, path, parts):
        """Process amplifier category paths"""
        if 'envelope' not in parts:
            return
            
        env_idx = parts.index('envelope')
        if env_idx + 1 >= len(parts):
            return
            
        # Process CC paths
        if len(parts) >= 6 and parts[-2].startswith('cc'):
            try:
                cc_num = int(parts[-2][2:])
                param_idx = env_idx + 1
                range_idx = param_idx + 1
                
                # Get range from path
                range_str = parts[range_idx] if range_idx < len(parts) else 'na'
                
                _log("Adding envelope CC route")
                # Create base path without range and default value
                base_path = f"{parts[0]}/{parts[1]}/envelope/{parts[param_idx]}"
                self._store_route_info(
                    'cc',
                    'routes',
                    base_path,
                    range=range_str,
                    cc_num=cc_num
                )
            except (ValueError, IndexError):
                _log("[ERROR] Invalid CC format: {}".format(path))
                
        # Process trigger paths
        elif 'trigger' in parts:
            if parts[-1] == 'note_on':
                _log("Adding note_on trigger route")
                self._store_route_info(
                    'note_on',
                    'trigger_routes',
                    path
                )
            elif parts[-1] == 'note_off':
                _log("Adding note_off trigger route")
                self._store_route_info(
                    'note_off',
                    'trigger_routes',
                    path
                )
                
        # Process level paths
        elif 'level' in parts[-3]:
            try:
                range_str = parts[-2]
                if parts[-1] == 'velocity':
                    _log("Adding velocity level route")
                    self._store_route_info(
                        'note_on',
                        'velocity_routes',
                        path,
                        range=range_str,
                        parameter=parts[env_idx + 1]
                    )
            except (ValueError, IndexError):
                _log("[ERROR] Invalid level format: {}".format(path))

    def _log_routing_tables(self):
        """Log the created routing tables"""
        _log("\nRouting Tables Created:")
        for msg_type, routes in self.route_info.items():
            _log(f"  {msg_type}:")
            if isinstance(routes, dict):
                for key, info in routes.items():
                    _log(f"    {key}: {info}")

    def _should_process(self, message):
        """Quick check if message should be processed based on whitelist"""
        return message['type'] in self.accepted_midi

    def _check_continuous(self, message):
        """Check if continuous controller change exceeds threshold"""
        msg_type = message['type']
        channel = message['channel']
        
        if channel not in self.last_value:
            self.last_value[channel] = {
                'pitch_bend': 8192,
                'pressure': 0,
                'timbre': 64
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
        elif msg_type == 'cc' and message['data']['number'] == 74:
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
        """Create route from template and value"""
        parts = template.split('/')
        
        if 'per_key' in parts:
            identifier = f"{channel}.{note}" if note is not None else str(channel)
            new_parts = []
            for part in parts:
                new_parts.append(part)
                if part == 'per_key':
                    new_parts.append(identifier)
            parts = new_parts
        
        if value or str(value).replace('.', '').replace('-', '').isdigit():
            parts.append(str(value))
        
        return '/'.join(parts)

    def process_message(self, message, voice_manager):
        """Transform MIDI message to route"""
        if not self._should_process(message):
            _log(f"[REJECTED] Message type not in config: {message['type']}")
            return

        if message['type'] in ('pitch_bend', 'pressure') or \
        (message['type'] == 'cc' and message['data']['number'] == 74):
            if not self._check_continuous(message):
                _log(f"[REJECTED] Change below threshold: {message['type']}")
                return

        self.message_buffer.append((message, voice_manager))
        _log(f"Message queued. Buffer size: {len(self.message_buffer)}/{BUFFER_SIZE}")
        
        while len(self.message_buffer):
            msg, vm = self.message_buffer.popleft()
            routes = []
            
            note = msg['data'].get('note', None)
            
            if msg['type'] == 'note_on':
                # Handle note number routes
                for info in self.route_info['note_on']['note_number_routes']:
                    routes.append(self._create_route(
                        info['template'],
                        msg['channel'],
                        note,
                        note
                    ))
                
                # Handle velocity routes
                for info in self.route_info['note_on']['velocity_routes']:
                    value = self._normalize(msg['data']['velocity'], info['range'])
                    routes.append(self._create_route(
                        info['template'],
                        msg['channel'],
                        value,
                        note
                    ))
                
                # Handle waveform routes
                for info in self.route_info['note_on']['waveform_routes']:
                    routes.append(self._create_route(
                        info['template'],
                        msg['channel'],
                        info['wave_type'],
                        note
                    ))
                    
                # Handle trigger routes
                for info in self.route_info['note_on']['trigger_routes']:
                    routes.append(self._create_route(
                        info['template'],
                        msg['channel'],
                        '',
                        note
                    ))
                    
            elif msg['type'] == 'note_off':
                # Handle trigger routes
                for info in self.route_info['note_off']['trigger_routes']:
                    routes.append(self._create_route(
                        info['template'],
                        msg['channel'],
                        '',
                        note
                    ))
                    
            elif msg['type'] == 'pitch_bend':
                for info in self.route_info['pitch_bend']['routes']:
                    value = self._normalize(msg['data']['value'], info['range'])
                    routes.append(self._create_route(info['template'], msg['channel'], value))
                    
            elif msg['type'] == 'pressure':
                for info in self.route_info['pressure']['routes']:
                    value = self._normalize(msg['data']['value'], info['range'])
                    routes.append(self._create_route(info['template'], msg['channel'], value))
                    
            elif msg['type'] == 'cc':
                cc_num = msg['data']['number']
                if cc_num in self.route_info['cc']:
                    for info in self.route_info['cc'][cc_num]['routes']:
                        value = self._normalize(msg['data']['value'], info['range'])
                        routes.append(self._create_route(info['template'], msg['channel'], value))

            # Send routes to voice manager
            for route in routes:
                _log(f"Sending route: {route}")
                vm.handle_route(route)
