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
        """Build lookup tables from config paths
        
        Examples of supported paths:
        Oscillator:
            oscillator/per_key/frequency/note_number
            oscillator/per_key/waveform/square/note_on
            oscillator/ring/per_key/frequency/20-20000/na/880
        Filter:
            filter/per_key/frequency/20-20000/cc74/1000
            filter/global/frequency/20-20000/cc1/1000
        Amplifier:
            amplifier/per_key/envelope/attack/trigger/note_on
            amplifier/global/envelope/attack_time/0.001-5/cc73/0.001
        """
        
        # Initialize routing tables
        self.accepted_midi = set()
        self.route_info = {
            'note_on': {},
            'note_off': None
        }
        
        # Process each path
        for path in paths.strip().split('\n'):
            if not path.strip():
                _log("[ERROR] Empty path found, skipping")
                continue
                
            parts = path.split('/')
            if len(parts) < 4:
                _log("[ERROR] Path too short (min 4 segments): {}".format(path))
                continue
                
            category = parts[0]
            if category == 'oscillator':
                _log("Processing oscillator path: {}".format(path))
                self._process_oscillator_path(parts)
            elif category == 'filter':
                _log("Processing filter path: {}".format(path))
                self._process_filter_path(parts)
            elif category == 'amplifier':
                _log("Processing amplifier path: {}".format(path))
                self._process_amplifier_path(parts)
            else:
                _log("[ERROR] Invalid category: {}".format(category))

    def _process_oscillator_path(self, parts):
        """Process oscillator category paths
        
        Examples:
        - oscillator/per_key/frequency/trigger/note_number
        """
        if len(parts) < 4:
            _log("[ERROR] Oscillator path too short: {}".format('/'.join(parts)))
            return
            
        template_parts = ['oscillator']
        
        # Level 1: Check for special oscillator types
        level1 = parts[1]
        if level1 == 'ring':
            template_parts.append('ring')
            if len(parts) < 5:
                _log("[ERROR] Ring modulator path too short: {}".format('/'.join(parts)))
                return
            level1 = parts[2]
            _log("Processing ring modulator path")
        # EXTENSION POINT: Add new oscillator types (sub, noise, etc)
        
        # Process scope
        if level1 == 'per_key':
            template_parts.append('per_key')
            _log("Processing per-key oscillator path")
        elif level1 == 'global':
            template_parts.append('global')
            _log("Processing global oscillator path")
        else:
            _log("[ERROR] Invalid oscillator scope: {}".format(level1))
            return
        
        # Process frequency and value type
        if 'frequency' in parts:
            template_parts.append('frequency')
            freq_idx = parts.index('frequency')
            
            # Look for value type (trigger, level, etc)
            if freq_idx + 1 < len(parts):
                value_type = parts[freq_idx + 1]
                template_parts.append(value_type)
                
                # Get MIDI value container
                if freq_idx + 2 < len(parts):
                    midi_value = parts[freq_idx + 2]
                    if midi_value == 'note_number':
                        _log("Adding note number frequency trigger route")
                        self.route_info['note_on']['note_number'] = {
                            'template': '/'.join(template_parts),
                            'range': 'na'
                        }
                        self.accepted_midi.add('note_on')
        
        # Process waveform
        if 'waveform' in parts:
            try:
                wave_idx = parts.index('waveform')
                if wave_idx + 1 < len(parts):
                    wave_type = parts[wave_idx + 1]
                    template_parts.extend(['waveform'])
                    _log("Adding waveform route with type: {}".format(wave_type))
                    self.route_info['note_on']['waveform'] = {
                        'template': '/'.join(template_parts),
                        'wave_type': wave_type,
                        'range': 'na'
                    }
                    self.accepted_midi.add('note_on')
            except ValueError:
                _log("[ERROR] Error processing waveform path: {}".format('/'.join(parts)))

            # EXTENSION POINT: Add handling for new note_on path types

    def _process_filter_path(self, parts):
        """Process filter category paths"""
        if len(parts) < 4:
            _log("[ERROR] Filter path too short: {}".format('/'.join(parts)))
            return
            
        template_parts = ['filter']
        
        # Process scope
        scope = parts[1]
        if scope == 'per_key':
            template_parts.append('per_key')
            _log("Processing per-key filter path")
        elif scope == 'global':
            template_parts.append('global')
            _log("Processing global filter path")
        else:
            _log("[ERROR] Invalid filter scope: {}".format(scope))
            return
        # EXTENSION POINT: Add new filter scopes
        
        # Process filter parameters
        if 'frequency' in parts:
            template_parts.append('frequency')
            try:
                range_str = parts[parts.index('frequency') + 1]
                cc_num = int(parts[-2][2:])  # Extract number from cc74
                _log("Adding filter frequency CC route for cc{}".format(cc_num))
                if 'cc' not in self.route_info:
                    self.route_info['cc'] = {}
                self.route_info['cc'][cc_num] = {
                    'template': '/'.join(template_parts),
                    'range': range_str
                }
                self.accepted_midi.add('cc')
            except (ValueError, IndexError):
                _log("[ERROR] Invalid frequency CC format: {}".format('/'.join(parts)))
        
        if 'resonance' in parts:
            template_parts.append('resonance')
            try:
                range_str = parts[parts.index('resonance') + 1]
                cc_num = int(parts[-2][2:])
                _log("Adding filter resonance CC route for cc{}".format(cc_num))
                if 'cc' not in self.route_info:
                    self.route_info['cc'] = {}
                self.route_info['cc'][cc_num] = {
                    'template': '/'.join(template_parts),
                    'range': range_str
                }
                self.accepted_midi.add('cc')
            except (ValueError, IndexError):
                _log("[ERROR] Invalid resonance CC format: {}".format('/'.join(parts)))
        # EXTENSION POINT: Add new filter parameters (cutoff, bandwidth, etc)

    def _process_amplifier_path(self, parts):
        """Process amplifier category paths
        
        Examples:
        - amplifier/per_key/envelope/attack/trigger/note_on   # Trigger path
        - amplifier/per_key/envelope/release/trigger/note_off # Trigger path
        - amplifier/global/envelope/attack_time/0.001-5/cc73/0.001  # CC path with default
        - amplifier/per_key/envelope/attack_level/0-1/velocity  # Level path
        """
        if len(parts) < 4:
            _log("[ERROR] Amplifier path too short: {}".format('/'.join(parts)))
            return
            
        template_parts = ['amplifier']
        
        # Process scope
        scope = parts[1]
        if scope == 'per_key':
            template_parts.append('per_key')
            _log("Processing per-key amplifier path")
        elif scope == 'global':
            template_parts.append('global')
            _log("Processing global amplifier path")
        else:
            _log("[ERROR] Invalid amplifier scope: {}".format(scope))
            return
        
        # Process envelope parameters
        if 'envelope' in parts:
            template_parts.append('envelope')
            env_idx = parts.index('envelope')
            
            if env_idx + 1 >= len(parts):
                _log("[ERROR] Missing envelope parameter: {}".format('/'.join(parts)))
                return
                
            # Add envelope parameter (attack, release, etc)
            env_param = parts[env_idx + 1]
            template_parts.append(env_param)
            
            # Check for CC paths first as they have a distinct structure
            if len(parts) >= 6 and parts[-2].startswith('cc'):
                try:
                    cc_num = int(parts[-2][2:])
                    range_str = parts[-3]
                    _log("Adding envelope CC route for cc{}".format(cc_num))
                    if 'cc' not in self.route_info:
                        self.route_info['cc'] = {}
                    self.route_info['cc'][cc_num] = {
                        'template': '/'.join(template_parts),
                        'range': range_str
                    }
                    self.accepted_midi.add('cc')
                except (ValueError, IndexError):
                    _log("[ERROR] Invalid CC format: {}".format('/'.join(parts)))
                
            # Process trigger paths
            elif 'trigger' in parts:
                trigger_idx = parts.index('trigger')
                template_parts.append('trigger')
                if parts[-1] == 'note_on':
                    _log("Adding note_on trigger route")
                    self.route_info['note_on']['trigger'] = {
                        'template': '/'.join(template_parts),
                        'range': 'na'
                    }
                    self.accepted_midi.add('note_on')
                elif parts[-1] == 'note_off':
                    _log("Adding note_off trigger route")
                    if not self.route_info['note_off']:
                        self.route_info['note_off'] = {}
                    self.route_info['note_off']['trigger'] = {
                        'template': '/'.join(template_parts),
                        'range': 'na'
                    }
                    self.accepted_midi.add('note_off')
                    
            # Process level paths
            elif 'level' in parts[-3]:  # Check for level in parameter name
                try:
                    range_str = parts[-2]  # Range comes before velocity
                    if parts[-1] == 'velocity':
                        _log("Adding velocity level route")
                        self.route_info['note_on']['velocity'] = {
                            'template': '/'.join(template_parts),
                            'range': range_str
                        }
                        self.accepted_midi.add('note_on')
                except (ValueError, IndexError):
                    _log("[ERROR] Invalid level format: {}".format('/'.join(parts)))
        
        # Check for optional default value
        if len(parts[-1].split('-')) == 1 and parts[-1] not in ['note_on', 'note_off', 'velocity']:
            try:
                default = float(parts[-1])
                _log("Found default value: {}".format(default))
            except ValueError:
                _log("[ERROR] Invalid default value: {}".format(parts[-1]))
                    
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
        
        # Add value if:
        # 1. It's not empty (for triggers)
        # 2. OR it's a numeric value (for CC, velocity, etc)
        if value or str(value).replace('.', '').replace('-', '').isdigit():
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
                        info['template'],     # Already contains '.../trigger'
                        msg['channel'],       
                        '',                   # No value needed for trigger
                        note                  
                    ))
                    
            elif msg['type'] == 'note_off':
                if self.route_info['note_off'] and 'trigger' in self.route_info['note_off']:
                    info = self.route_info['note_off']['trigger']
                    routes.append(self._create_route(
                        info['template'],
                        msg['channel'],
                        '',              # No value needed for trigger
                        note
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