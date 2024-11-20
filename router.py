"""
Advanced MPE Message Router for New Instrument Configuration System

Handles complex routing based on the new instrument configuration paradigm.
"""
import sys
from fixed_point_math import FixedPoint

class Logging:
    """
    Centralized logging functionality for router components.
    Provides consistent message formatting and debug level control.
    """
    @staticmethod
    def format_log_message(message):
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

    @staticmethod
    def log(message, debug_flag=True):
        """
        Conditional logging function that respects debug flag.
        
        Args:
            message (str or dict): Message to log
            debug_flag (bool): Whether to output the log
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

        if debug_flag:
            if "rejected" in str(message):
                color = DARK_GRAY
            elif "[ERROR]" in str(message):
                color = RED
            else:
                color = BLUE
            
            # If message is a dictionary, format with custom indentation
            if isinstance(message, dict):
                formatted_message = Logging.format_log_message(message)
                print(f"{color}{formatted_message}{RESET}", file=sys.stderr)
            else:
                print(f"{color}[ROUTER] {message}{RESET}", file=sys.stderr)

class MidiValidator:
    """
    Validates incoming MIDI messages against instrument configuration.
    Ensures messages are valid for the current configuration.
    """
    def __init__(self, config=None):
        self.config = config
        
    def set_config(self, config):
        """Update configuration"""
        self.config = config
        
    def is_message_allowed(self, message):
        """
        Validate incoming MIDI message against instrument configuration.
        
        Args:
            message (dict): Incoming MIDI message
        
        Returns:
            bool: Whether the message is valid for this instrument
        """
        if not self.config or not message:
            Logging.log("Validation failed: No config or message")
            return False
        
        msg_type = message.get('type')
        sources = self.config.get('sources', {})
        data = message.get('data', {})
        
        # Mapping of message types to their source keys
        type_to_source = {
            'note_on': 'note_on',
            'note_off': 'note_off',
            'cc': 'cc',
            'pitch_bend': 'pitch_bend',
            'channel_pressure': 'channel_pressure',
            'pressure': 'channel_pressure'  # Handle potential type variation
        }
        
        # Check if message type is supported
        if msg_type not in type_to_source:
            Logging.log(f"Message rejected: Unsupported message type {msg_type}")
            return False
        
        # Normalize source key
        source_key = type_to_source[msg_type]
        
        # Specific validation for CC messages
        if msg_type == 'cc':
            cc_number = data.get('number')
            if cc_number is not None:
                # Check CC routing
                cc_routing = self.config.get('cc_routing', {})
                if str(cc_number) in cc_routing:
                    Logging.log(f"CC {cc_number} accepted: in cc_routing")
                    return True
                    
                # Check module controls
                if self.is_cc_used_in_module('oscillator', cc_number) or \
                   self.is_cc_used_in_module('filter', cc_number) or \
                   self.is_cc_used_in_module('amplifier', cc_number):
                    Logging.log(f"CC {cc_number} accepted: used in module control")
                    return True
                    
                Logging.log(f"Message rejected: CC {cc_number} not in sources or module controls")
                return False
        
        # Check if source is defined in configuration
        if source_key not in sources:
            Logging.log(f"Message rejected: {source_key} not in instrument sources")
            return False
        
        # Log acceptance for other message types
        Logging.log(f"{msg_type} accepted")
        return True
        
    def is_cc_used_in_module(self, module_name, cc_number):
        """
        Check if a CC number is used in a module's controls.
        
        Args:
            module_name (str): Name of the module to check
            cc_number (int): CC number to search for
        
        Returns:
            bool: Whether the CC number is used in the module
        """
        if not self.config:
            return False
            
        module = self.config.get(module_name, {})
        
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

class MidiTranslator:
    """
    Handles MIDI message value extraction and transformation.
    Converts MIDI messages into normalized control values.
    """
    def __init__(self, config=None):
        self.config = config
        
    def set_config(self, config):
        """Update configuration"""
        self.config = config
        
    def get_source_value(self, source, message):
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
        
        Logging.log("Extracting source value:")
        Logging.log(f"  Source ID: {source_id}")
        Logging.log(f"  Attribute: {attribute}")
        Logging.log(f"  Message Type: {msg_type}")
        Logging.log(f"  Message Data: {data}")
        
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
        
        Logging.log("[ERROR] No source value found for specified source")
        
        return None
        
    def transform_value(self, value, transform_config):
        """
        Transform a value based on configuration.
        
        Args:
            value (float/int): Input value
            transform_config (dict): Transformation configuration
        
        Returns:
            float: Transformed value
        """
        if not transform_config:
            Logging.log("No transformation config, returning original value")
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
        
        Logging.log("Value transformation:")
        Logging.log(f"  Original value: {original_value}")
        Logging.log(f"  Curve: {curve}")
        Logging.log(f"  Transformed value: {value}")
        
        return value

class VoiceNav:
    """
    Handles routing to voices and parameters.
    Manages voice allocation and parameter updates.
    """
    def __init__(self, voice_manager):
        self.voice_manager = voice_manager
        
    def route_to_destination(self, destination, value, message):
        """
        Route a transformed value to its destination.
        
        Args:
            destination (dict): Destination configuration
            value (float): Transformed value
            message (dict): Original MIDI message
        """
        dest_id = destination.get('id')
        attribute = destination.get('attribute')
        
        Logging.log("Routing to destination:")
        Logging.log(f"  Destination ID: {dest_id}")
        Logging.log(f"  Attribute: {attribute}")
        Logging.log(f"  Value: {value}")
        
        # Find the corresponding voice
        channel = message.get('channel')
        note = message.get('data', {}).get('note')
        voice = self.voice_manager.get_voice(channel, note)
        
        if not voice:
            Logging.log("[ERROR] No voice found for routing")
            return
        
        Logging.log("Voice found for routing")
        
        # Route to specific module/parameter
        if dest_id == 'oscillator' and attribute == 'frequency':
            Logging.log("Routing to oscillator frequency")
            voice.handle_value_change('frequency', value)
        elif dest_id == 'amplifier' and attribute == 'gain':
            Logging.log("Routing to amplifier gain")
            voice.handle_value_change('amplitude', value)
        elif dest_id == 'filter' and attribute == 'frequency':
            Logging.log("Routing to filter frequency")
            voice.handle_value_change('filter_freq', value)
        else:
            Logging.log("[ERROR] Unhandled destination routing")
        
        Logging.log("Destination routing complete")
        
    def route_cc_message(self, message):
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
        
        Logging.log("Routing CC message:")
        Logging.log(f"  CC Number: {cc_number}")
        Logging.log(f"  CC Value: {cc_value}")
        
        # Check CC routing in configuration
        cc_routing = self.voice_manager.current_config.get('cc_routing', {})
        
        if str(cc_number) in cc_routing:
            route = cc_routing[str(cc_number)]
            Logging.log("CC Route found:")
            Logging.log(f"  Name: {route.get('name')}")
            Logging.log(f"  Target: {route.get('target')}")
            Logging.log(f"  Path: {route.get('path')}")
            
            # Normalize CC value using FixedPoint method
            normalized_value = FixedPoint.normalize_midi_value(cc_value)
            
            # Route to destination
            destination = {
                'id': route.get('target'),
                'attribute': route.get('path', '').split('.')[-1]
            }
            
            self.route_to_destination(
                destination, 
                normalized_value, 
                message
            )
        else:
            Logging.log("[ERROR] CC route not found despite passing initial validation")
        
        return None

class RouteMap:
    """
    Core message routing orchestration.
    Coordinates the flow of MIDI messages through the system.
    """
    def __init__(self, voice_manager):
        """
        Initialize the RouteMap with specialized components.
        
        Args:
            voice_manager (VoiceManager): Voice management system
        """
        self.voice_manager = voice_manager
        self.validator = MidiValidator()
        self.translator = MidiTranslator()
        self.voice_router = VoiceNav(voice_manager)
        self.current_config = None
        
        Logging.log("Initialized RouteMap with components")
        
    def set_config(self, config):
        """
        Set the current instrument configuration and propagate to components.
        
        Args:
            config (dict): Instrument configuration dictionary
        """
        self.current_config = config
        self.validator.set_config(config)
        self.translator.set_config(config)
        self.voice_manager.set_config(config)
        
        Logging.log(f"Configuration set for instrument: {config.get('name', 'Unknown')}")
        Logging.log(config)
    
    def route_message(self, message):
        """
        Route a MIDI message through the instrument's configuration.
        
        Args:
            message (dict): Incoming MIDI message
        
        Returns:
            dict: Routing result or None
        """
        Logging.log("Processing MIDI message:")
        Logging.log(message)
        
        # First check: Is message allowed
        if not self.validator.is_message_allowed(message):
            return None
        
        msg_type = message.get('type')
        data = message.get('data', {})
        channel = message.get('channel')
        
        # Handle note messages
        if msg_type in ['note_on', 'note_off']:
            note = data.get('note')
            velocity = data.get('velocity', 127) if msg_type == 'note_on' else 0
            
            Logging.log(f"Processing {msg_type}:")
            Logging.log(f"  Channel: {channel}")
            Logging.log(f"  Note: {note}")
            Logging.log(f"  Velocity: {velocity}")
            
            if msg_type == 'note_on':
                voice = self.voice_manager.allocate_voice(channel, note, velocity)
                if not voice:
                    Logging.log("[ERROR] Failed to allocate voice")
                    return None
                Logging.log("Voice allocated")
                return {'type': 'voice_allocated', 'voice': voice}
            else:
                voice = self.voice_manager.release_voice(channel, note)
                if not voice:
                    Logging.log("[ERROR] Failed to release voice")
                    return None
                Logging.log("Voice released")
                return {'type': 'voice_released', 'voice': voice}
        
        # Handle CC messages
        if msg_type == 'cc':
            return self.voice_router.route_cc_message(message)
        
        # Handle other control messages
        patches = self.current_config.get('patches', [])
        Logging.log(f"Processing patches: {len(patches)} patches")
        
        processed_any_patch = False
        for patch in patches:
            source = patch.get('source', {})
            destination = patch.get('destination', {})
            processing = patch.get('processing', {})
            
            Logging.log("Processing patch:")
            Logging.log(f"  Source: {source}")
            Logging.log(f"  Destination: {destination}")
            Logging.log(f"  Processing: {processing}")
            
            # Determine source value
            source_value = self.translator.get_source_value(source, message)
            
            if source_value is not None:
                processed_any_patch = True
                Logging.log(f"Source value: {source_value}")
                
                # Transform value
                transformed_value = self.translator.transform_value(
                    source_value, 
                    processing
                )
                
                # Apply modulation amount
                amount = processing.get('amount', 1.0)
                modulated_value = transformed_value * amount
                
                Logging.log("Value processing:")
                Logging.log(f"  Transformed value: {transformed_value}")
                Logging.log(f"  Modulation amount: {amount}")
                Logging.log(f"  Modulated value: {modulated_value}")
                
                # Route to destination
                self.voice_router.route_to_destination(
                    destination, 
                    modulated_value, 
                    message
                )
        
        # If no patches were processed, log an error
        if not processed_any_patch:
            Logging.log("[ERROR] No patches processed for message")
        
        return None
    
    def process_updates(self):
        """Process any pending updates in voice management"""
        self.voice_manager.cleanup_voices()
