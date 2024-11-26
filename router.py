"""
router.py - MIDI to Route Transformation

Transforms MIDI messages into routes using config paths.
Maintains path schema integrity when creating routes.
Pure transformation - no state, validation, or buffering.
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
    
    def format_midi_message(msg_type, channel, data):
        """Format MIDI message with nice indentation."""
        lines = []
        lines.append(f"Processing {msg_type} message:")
        lines.append(f"  channel: {channel}")
        lines.append("  data:")
        for k, v in data.items():
            lines.append(f"    {k}: {v}")
        return "\n".join(lines)

    # Handle different message types
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

class Router:
    def __init__(self, paths):
        """Initialize router with a set of paths from config"""
        # Split paths and filter out empty lines
        self.paths = [p.strip() for p in paths.strip().split('\n') if p.strip()]
        _log(f"Initialized router with {len(self.paths)} paths")

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
            _log(f"[ERROR] Invalid range format: {range_str}")
            return value

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
            
        route_parts.append(str(value))  # normalized value
        
        route = '/'.join(route_parts)
        _log(f"Created route: {route}")  # Simplified logging
        return route

    def process_message(self, message, voice_manager):
        """Transform MIDI message into routes using path schema"""
        msg_type = message['type']
        channel = message['channel']
        routes = []

        _log(message)  # Log incoming MIDI message

        if msg_type == 'note_on':
            note_num = message['data']['note']
            note_name = f"C{note_num}"  # TODO: proper note name conversion
            velocity = message['data']['velocity']
            
            # Process all paths for this message type
            for path in self.paths:
                parts = path.split('/')
                source = parts[-1]
                range_str = parts[-2]
                
                # Note number paths
                if source == 'note_number':
                    value = self.normalize_value(note_num, range_str)
                    route = self.create_route_from_path(path, channel, value, note_name)
                    if route:
                        routes.append(route)
                        
                # Velocity paths
                elif source == 'velocity':
                    value = self.normalize_value(velocity, range_str)
                    route = self.create_route_from_path(path, channel, value, note_name)
                    if route:
                        routes.append(route)
                        
                # Initial expression states
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
            # Create release route maintaining path structure
            for path in self.paths:
                if 'release' in path:
                    route = self.create_route_from_path(path, channel, 1, note_name)
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
