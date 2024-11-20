"""
Advanced MPE Message Router for New Instrument Configuration System

Handles complex routing based on the new instrument configuration paradigm.
"""
import sys
from fixed_point_math import FixedPoint
from constants import ROUTER_DEBUG

def _format_log_message(message):
    """
    Format a dictionary message for console logging with specific indentation rules.
    Handles dictionaries, lists, and primitive values.
    
    Args:
        message (dict): Message to format
        
    Returns:
        str: Formatted message string
    """
    def format_value(value, indent_level=0):
        """Recursively format values with proper indentation."""
        base_indent = ' ' * 0
        extra_indent = ' ' * 2
        indent = base_indent + ' ' * (4 * indent_level)
        
        if isinstance(value, dict):
            if not value:  # Handle empty dict
                return '{}'
            lines = ['{']
            for k, v in value.items():
                formatted_v = format_value(v, indent_level + 1)
                lines.append(f"{indent + extra_indent}'{k}': {formatted_v},")
            lines.append(f"{indent}}}")
            return '\n'.join(lines)
        
        elif isinstance(value, list):
            if not value:  # Handle empty list
                return '[]'
            lines = ['[']
            for item in value:
                formatted_item = format_value(item, indent_level + 1)
                lines.append(f"{indent + extra_indent}{formatted_item},")
            lines.append(f"{indent}]")
            return '\n'.join(lines)
        
        elif isinstance(value, str):
            return f"'{value}'"
        else:
            return str(value)
            
    return format_value(message)

def _log(message):
    """
    Conditional logging function that respects ROUTER_DEBUG flag.
    
    Args:
        message (str or dict): Message to log
    """
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[37m"
    DARK_GRAY = "\033[90m"
    RESET = "\033[0m"

    if ROUTER_DEBUG:
        if "rejected" in str(message):
            color = DARK_GRAY
        elif "[ERROR]" in str(message):
            color = RED
        else:
            color = BLUE
        
        # If message is a dictionary, format with custom indentation
        if isinstance(message, dict):
            formatted_message = _format_log_message(message)
            print(f"{color}{formatted_message}{RESET}", file=sys.stderr)
        else:
            print(f"{color}[ROUTER] {message}{RESET}", file=sys.stderr)

class MPEMessageRouter:
    """
    Advanced MIDI message routing system for complex instrument configurations.
    
    Manages sophisticated routing logic, including:
    - Source mapping
    - Parameter transformations
    - Message validation
    - Voice allocation and management
    
    Supports dynamic configuration changes and provides detailed debug logging.
    """
    def __init__(self, voice_manager):
        """
        Initialize the MPE Message Router.
        
        Args:
            voice_manager (MPEVoiceManager): Voice management system for handling note states
        """
        self.voice_manager = voice_manager
        self.current_config = None
        
        _log("Initialized with voice manager")
        
    def set_config(self, config):
        """
        Set the current instrument configuration and propagate to voice manager.
        
        Args:
            config (dict): Instrument configuration dictionary
        """
        self.current_config = config
        self.voice_manager.set_config(config)
        
        _log(f"Configuration set for instrument: {config.get('name', 'Unknown')}")
        _log(config)
    
    def _is_message_allowed(self, message):
        """
        Validate incoming MIDI message against instrument configuration.
        
        Performs sophisticated validation checking:
        - Message type support
        - CC usage
        - Source definitions
        
        Args:
            message (dict): Incoming MIDI message
        
        Returns:
            bool: Whether the message is valid for this instrument
        """
        if not self.current_config or not message:
            _log("Validation failed: No config or message")
            return False
        
        msg_type = message.get('type')
        sources = self.current_config.get('sources', {})
        data = message.get('data', {})
        
        # Check if message type is supported
        if msg_type not in ['note_on', 'note_off', 'cc', 'pitch_bend', 'channel_pressure']:
            _log(f"Unsupported message type: {msg_type}")
            return False
        
        # Note message validation
        if msg_type == 'note_on':
            if 'note_on' not in sources:
                _log("Note On not supported in configuration")
                return False
            _log(f"Note message accepted: {data.get('note')}")
            return True
            
        elif msg_type == 'note_off':
            if 'note_off' not in sources:
                _log("Note Off not supported in configuration")
                return False
            _log(f"Note off accepted: {data.get('note')}")
            return True
            
        # CC validation
        elif msg_type == 'cc':
            cc_number = data.get('number')
            if cc_number is not None:
                # Check CC routing
                cc_routing = self.current_config.get('cc_routing', {})
                if str(cc_number) in cc_routing:
                    _log(f"CC {cc_number} accepted: defined in cc_routing")
                    return True
                    
                # Check module controls
                if self._is_cc_used_in_module('oscillator', cc_number) or \
                   self._is_cc_used_in_module('filter', cc_number) or \
                   self._is_cc_used_in_module('amplifier', cc_number):
                    _log(f"CC {cc_number} accepted: used in module control")
                    return True
                    
                _log(f"CC {cc_number} rejected: not used in configuration")
                return False
        
        # Other control messages
        elif msg_type in ['pitch_bend', 'channel_pressure']:
            source_type = 'pitch_bend' if msg_type == 'pitch_bend' else 'channel_pressure'
            if source_type in sources:
                _log(f"{msg_type} accepted")
                return True
        
        _log(f"Message rejected: {msg_type}")
        return False
    
    def _is_cc_used_in_module(self, module_name, cc_number):
        """
        Check if a CC number is used in a module's controls.
        
        Args:
            module_name (str): Name of the module to check
            cc_number (int): CC number to search for
        
        Returns:
            bool: Whether the CC number is used in the module
        """
        if not self.current_config:
            return False
            
        module = self.current_config.get(module_name, {})
        
        # Check direct parameters
        for param_name, param_data in module.items():
            if isinstance(param_data, dict):
                control = param_data.get('control', {})
                if control.get('cc') == cc_number:
                    return True
                    
        # Check envelope if it exists
        envelope = module.get('envelope', {})
        for stage in ['attack', 'decay', 'sustain', 'release']:
            stage_data = envelope.get(stage, {})
            for param in ['time', 'level']:
                param_data = stage_data.get(param, {})
                control = param_data.get('control', {})
                if control.get('cc') == cc_number:
                    return True
                    
        return False
    
    def _transform_value(self, value, transform_config):
        """
        Transform a value based on configuration.
        
        Args:
            value (float/int): Input value
            transform_config (dict): Transformation configuration
        
        Returns:
            float: Transformed value
        """
        if not transform_config:
            _log("No transformation config, returning original value")
            return value
        
        original_value = value
        
        # Range mapping
        if 'range' in transform_config:
            r = transform_config['range']
            value = (
                (value - r.get('in_min', 0)) / 
                (r.get('in_max', 127) - r.get('in_min', 0))
            ) * (r.get('out_max', 1.0) - r.get('out_min', 0.0)) + r.get('out_min', 0.0)
        
        # Curve transformation
        curve = transform_config.get('curve', 'linear')
        if curve == 'exponential':
            value = value ** 2
        elif curve == 'logarithmic':
            value = 1 - (1 - value) ** 2
        elif curve == 's_curve':
            value = 3 * value ** 2 - 2 * value ** 3
        
        _log("Value transformation:")
        _log(f"  Original value: {original_value}")
        _log(f"  Curve: {curve}")
        _log(f"  Transformed value: {value}")
        
        return value
    
    def route_message(self, message):
        """
        Route a MIDI message through the instrument's configuration.
        
        Args:
            message (dict): Incoming MIDI message
        
        Returns:
            dict: Routing result or None
        """
        _log("Routing message:")
        _log(message)
        
        # First check: Is message allowed
        if not self._is_message_allowed(message):
            return None
        
        msg_type = message.get('type')
        data = message.get('data', {})
        channel = message.get('channel')
        
        # Handle note messages
        if msg_type in ['note_on', 'note_off']:
            note = data.get('note')
            velocity = data.get('velocity', 127) if msg_type == 'note_on' else 0
            
            _log(f"Processing {msg_type}:")
            _log(f"  Channel: {channel}")
            _log(f"  Note: {note}")
            _log(f"  Velocity: {velocity}")
            
            if msg_type == 'note_on':
                voice = self.voice_manager.allocate_voice(channel, note, velocity)
                if not voice:
                    _log("[ERROR] Failed to allocate voice")
                    return None
                _log("Voice allocated")
                return {'type': 'voice_allocated', 'voice': voice}
            else:
                voice = self.voice_manager.release_voice(channel, note)
                if not voice:
                    _log("[ERROR] Failed to release voice")
                    return None
                _log("Voice released")
                return {'type': 'voice_released', 'voice': voice}
        
        # Handle CC messages
        if msg_type == 'cc':
            return self._route_cc_message(message)
        
        # Handle other control messages
        patches = self.current_config.get('patches', [])
        _log(f"Processing patches: {len(patches)} patches")
        
        processed_any_patch = False
        for patch in patches:
            source = patch.get('source', {})
            destination = patch.get('destination', {})
            processing = patch.get('processing', {})
            
            _log("Processing patch:")
            _log(f"  Source: {source}")
            _log(f"  Destination: {destination}")
            _log(f"  Processing: {processing}")
            
            # Determine source value
            source_value = self._get_source_value(source, message)
            
            if source_value is not None:
                processed_any_patch = True
                _log(f"Source value: {source_value}")
                
                # Transform value
                transformed_value = self._transform_value(
                    source_value, 
                    processing
                )
                
                # Apply modulation amount
                amount = processing.get('amount', 1.0)
                modulated_value = transformed_value * amount
                
                _log("Value processing:")
                _log(f"  Transformed value: {transformed_value}")
                _log(f"  Modulation amount: {amount}")
                _log(f"  Modulated value: {modulated_value}")
                
                # Route to destination
                self._route_to_destination(
                    destination, 
                    modulated_value, 
                    message
                )
        
        # If no patches were processed, log an error
        if not processed_any_patch:
            _log("[ERROR] No patches processed for message")
        
        return None
    
    def _route_cc_message(self, message):
        """
        Route a CC (Control Change) message.
        
        Args:
            message (dict): CC message
        
        Returns:
            None
        """
        cc_number = message['data']['number']
        cc_value = message['data']['value']
        channel = message['channel']
        
        _log("Routing CC message:")
        _log(f"  CC Number: {cc_number}")
        _log(f"  CC Value: {cc_value}")
        
        # Check CC routing in configuration
        cc_routing = self.current_config.get('cc_routing', {})
        
        if str(cc_number) in cc_routing:
            route = cc_routing[str(cc_number)]
            _log("CC Route found:")
            _log(f"  Name: {route.get('name')}")
            _log(f"  Target: {route.get('target')}")
            _log(f"  Path: {route.get('path')}")
            
            # Normalize CC value using FixedPoint method
            normalized_value = FixedPoint.normalize_midi_value(cc_value)
            
            # Route to destination
            destination = {
                'id': route.get('target'),
                'attribute': route.get('path', '').split('.')[-1]
            }
            
            self._route_to_destination(
                destination, 
                normalized_value, 
                message
            )
        else:
            _log("[ERROR] CC route not found despite passing initial validation")
        
        return None
    
    def _get_source_value(self, source, message):
        """
        Extract source value from a MIDI message.
        
        Args:
            source (dict): Source configuration
            message (dict): MIDI message
        
        Returns:
            float/int/None: Extracted source value
        """
        msg_type = message.get('type')
        data = message.get('data', {})
        
        source_id = source.get('id')
        attribute = source.get('attribute')
        
        _log("Extracting source value:")
        _log(f"  Source ID: {source_id}")
        _log(f"  Attribute: {attribute}")
        _log(f"  Message Type: {msg_type}")
        _log(f"  Message Data: {data}")
        
        # Direct mapping for specific message types
        if msg_type == 'note_on' and source_id == 'note_on':
            if attribute == 'velocity':
                return data.get('velocity', 0)
            if attribute == 'note':
                return data.get('note', 0)
        
        if msg_type == 'note_off' and source_id == 'note_off':
            return 0  # Trigger value
        
        if msg_type == 'pitch_bend' and source_id == 'pitch_bend':
            return data.get('value', 0)
        
        if msg_type == 'channel_pressure' and source_id == 'channel_pressure':
            return data.get('value', 0)
        
        _log("[ERROR] No source value found for specified source")
        
        return None
    
    def _route_to_destination(self, destination, value, message):
        """
        Route a transformed value to its destination.
        
        Args:
            destination (dict): Destination configuration
            value (float): Transformed value
            message (dict): Original MIDI message
        """
        dest_id = destination.get('id')
        attribute = destination.get('attribute')
        
        _log("Routing to destination:")
        _log(f"  Destination ID: {dest_id}")
        _log(f"  Attribute: {attribute}")
        _log(f"  Value: {value}")
        
        # Find the corresponding voice
        channel = message.get('channel')
        note = message.get('data', {}).get('note')
        voice = self.voice_manager.get_voice(channel, note)
        
        if not voice:
            _log("[ERROR] No voice found for routing")
            return
        
        _log("Voice found for routing")
        
        # Route to specific module/parameter
        if dest_id == 'oscillator' and attribute == 'frequency':
            _log("Routing to oscillator frequency")
            voice.handle_value_change('frequency', value)
        elif dest_id == 'amplifier' and attribute == 'gain':
            _log("Routing to amplifier gain")
            voice.handle_value_change('amplitude', value)
        elif dest_id == 'filter' and attribute == 'frequency':
            _log("Routing to filter frequency")
            voice.handle_value_change('filter_freq', value)
        else:
            _log("[ERROR] Unhandled destination routing")
        
        _log("Destination routing complete")
    
    def process_updates(self):
        """Process any pending updates in voice management"""
        self.voice_manager.cleanup_voices()
