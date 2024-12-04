"""
paths.py - Path Processing and Value Transformation

Handles path parsing, validation, and value processing.
Pure transformation with minimal state.
Builds efficient lookup tables for router.
"""

import sys
from constants import ROUTER_DEBUG

def _log(message, module="PATHS"):
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

class RouteTemplate:
    """Pre-computed template for route generation"""
    def __init__(self, template, scope, needs_value=False, value_type=None):
        self.template = template
        self.scope = scope
        self.needs_value = needs_value
        self.value_type = value_type
        
        # Pre-compute parts that don't need message data
        parts = template.split('/')
        self.prefix = '/'.join(p for p in parts if '-' not in p and p not in ('velocity', 'note_number'))
        
        # Pre-compute if this is a special route type
        self.is_waveform = template.endswith('/saw') or template.endswith('/triangle')
        self.is_note_number = 'note_number' in template
        self.is_velocity = 'velocity' in template
        
        # Extract range if present
        self.range_str = None
        for part in parts:
            if '-' in part:
                self.range_str = part
                break

class RouteBundle:
    """Pre-computed bundle of routes that share common MIDI data"""
    def __init__(self):
        self.templates = []  # List of RouteTemplates in original order
        
    def add_route(self, template, scope):
        """Add route template while preserving original order"""
        # Determine if route needs a value and what type
        needs_value = False
        value_type = None
        
        if 'note_number' in template:
            needs_value = True
            value_type = 'note'
        elif 'velocity' in template:
            needs_value = True
            value_type = 'velocity'
        elif not (template.endswith('/saw') or template.endswith('/triangle')):
            for part in template.split('/'):
                if '-' in part:  # Has a range, needs value
                    needs_value = True
                    break
        
        route_template = RouteTemplate(template, scope, needs_value, value_type)
        self.templates.append(route_template)

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
        
        # New: Route bundles for optimized processing
        self.note_on_bundle = RouteBundle()
        self.note_off_bundle = RouteBundle()

    def process_paths(self, paths):
        """Process path strings into routing tables and bundles"""
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
                # Store route info and update bundles
                _log(f"Adding route info - MIDI type: {midi_type}, Template: {template}, Scope: {scope}")
                self._add_route_info(midi_type, template, scope)
            except Exception as e:
                _log(f"[ERROR] Failed to add route info: {str(e)}")
                raise

    def _add_route_info(self, midi_type, template, scope):
        """Store route info and update route bundles"""
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
                    # Add to note_on bundle
                    self.note_on_bundle.add_route(template, scope)
                elif midi_type == 'note_off':
                    msg_type = 'note_off'
                    # Add to note_off bundle
                    self.note_off_bundle.add_route(template, scope)
                elif midi_type == 'pitch_bend':
                    msg_type = 'pitch_bend'
                elif midi_type == 'pressure':
                    msg_type = 'pressure'
                elif midi_type == 'velocity':
                    msg_type = 'note_on'  # velocity comes with note_on
                    # Add to note_on bundle's velocity routes
                    self.note_on_bundle.add_route(template, scope)
                elif midi_type == 'note_number':
                    msg_type = 'note_on'  # note_number comes with note_on
                    # Add to note_on bundle's note_number routes
                    self.note_on_bundle.add_route(template, scope)
                
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
        
        # Extract range if present in template
        range_parts = [part for part in template.split('/') if '-' in part]
        range_str = range_parts[0] if range_parts else None
            
        # Check if this route should have a value appended
        if template.endswith('/saw') or template.endswith('/triangle'):
            return None
            
        # Handle note_on without value specifier
        if msg_type == 'note_on' and template.endswith('/note_on'):
            return None
            
        # Handle note_number
        if 'note_number' in template:
            return message['data'].get('note')
            
        # Get raw value based on message type
        if msg_type == 'note_off':
            return None
        elif msg_type == 'pitch_bend':
            raw_value = message['data'].get('value', 8192)
            _log(f"[NORMALIZE] Input: value={raw_value}, range={range_str}, type={msg_type}")
            if range_str:
                normalized = self.normalize_value(raw_value, range_str, msg_type)
                _log(f"[NORMALIZE] Normalized value: {normalized}")
                return normalized
            return raw_value
        elif msg_type == 'pressure':
            raw_value = message['data'].get('value', 0)
            if range_str:
                return self.normalize_value(raw_value, range_str, msg_type)
            return raw_value
        elif msg_type == 'cc':
            raw_value = message['data'].get('value', 0)
            if range_str:
                return self.normalize_value(raw_value, range_str, msg_type)
            return raw_value
        elif 'velocity' in template:
            raw_value = message['data'].get('velocity', 127)
            if range_str:
                return self.normalize_value(raw_value, range_str, msg_type)
            return raw_value

        return None

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

    def normalize_value(self, value, range_str, msg_type):
        """Normalize value to specified range based on message type"""
        try:
            _log(f"[NORMALIZE] Input: value={value}, range={range_str}, type={msg_type}")
            
            # Special handling for negative ranges (e.g., -12-12, -1-1)
            range_parts = range_str.split('-')
            if len(range_parts) == 3:  # Case for negative ranges like -12-12
                low = float(f"-{range_parts[1]}")  # Convert -12 properly
                high = float(range_parts[2])       # Convert 12 properly
            else:  # Standard case like 0-127
                low = float(range_parts[0])
                high = float(range_parts[1])
                
            _log(f"[NORMALIZE] Range decoded: low={low}, high={high}")
            
            if msg_type == 'pitch_bend':
                # Normalize from 0-16383 to -1 to 1 range
                normalized_pos = (value - 8192) / 8192.0
                _log(f"[NORMALIZE] Normalized position (-1 to 1): {normalized_pos}")
                
                # Scale normalized position to target range
                result = low + ((normalized_pos + 1) / 2.0) * (high - low)
                _log(f"[NORMALIZE] Final result: {result}")
                return result
            else:
                # Standard MIDI values 0-127
                result = low + (value/127.0) * (high - low)
                _log(f"[NORMALIZE] Standard MIDI result: {result}")
                return result
            
        except (ValueError, TypeError) as e:
            _log(f"[NORMALIZE] Error: {str(e)}")
            return value
