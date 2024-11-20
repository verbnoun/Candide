"""
Advanced MPE Message Router for New Instrument Configuration System

Handles complex routing based on the new instrument configuration paradigm.
"""

import time
from fixed_point_math import FixedPoint
from constants import ModSource, ModTarget, ROUTER_DEBUG

class MPEMessageRouter:
    """
    Routes MIDI messages according to the new instrument configuration system.
    Handles complex routing, source mapping, and parameter transformations.
    """
    def __init__(self, voice_manager):
        self.voice_manager = voice_manager
        self.current_config = None
        
        if ROUTER_DEBUG:
            print("[ROUTER] Initialized with voice manager")
        
    def set_config(self, config):
        """Set the current instrument configuration"""
        self.current_config = config
        self.voice_manager.set_config(config)
        
        if ROUTER_DEBUG:
            print(f"[ROUTER] Configuration set for instrument: {config.get('name', 'Unknown')}")
            print("[ROUTER] Configuration details:")
            for key, value in config.items():
                if key != 'patches':  # Skip patches array for brevity
                    print(f"  {key}: {value}")
    
    def _is_message_allowed(self, message):
        """
        Validate incoming MIDI message against instrument configuration.
        More sophisticated validation that checks CC usage and source definitions.
        
        Args:
            message (dict): Incoming MIDI message
        
        Returns:
            bool: Whether the message is valid for this instrument
        """
        if not self.current_config or not message:
            if ROUTER_DEBUG:
                print("[ROUTER] Validation failed: No config or message")
            return False
        
        msg_type = message.get('type')
        sources = self.current_config.get('sources', {})
        data = message.get('data', {})
        
        # Check if message type is supported
        if msg_type not in ['note_on', 'note_off', 'cc', 'pitch_bend', 'channel_pressure']:
            if ROUTER_DEBUG:
                print(f"[ROUTER] Unsupported message type: {msg_type}")
            return False
        
        # Note message validation
        if msg_type == 'note_on':
            if 'note_on' not in sources:
                if ROUTER_DEBUG:
                    print("[ROUTER] Note on not supported in configuration")
                return False
            if ROUTER_DEBUG:
                print(f"[ROUTER] Note message accepted: {data.get('note')}")
            return True
            
        elif msg_type == 'note_off':
            if 'note_off' not in sources:
                if ROUTER_DEBUG:
                    print("[ROUTER] Note off not supported in configuration")
                return False
            if ROUTER_DEBUG:
                print(f"[ROUTER] Note off accepted: {data.get('note')}")
            return True
            
        # CC validation
        elif msg_type == 'cc':
            cc_number = data.get('number')
            if cc_number is not None:
                # Check CC routing
                cc_routing = self.current_config.get('cc_routing', {})
                if str(cc_number) in cc_routing:
                    if ROUTER_DEBUG:
                        print(f"[ROUTER] CC {cc_number} accepted: defined in cc_routing")
                    return True
                    
                # Check module controls
                if self._is_cc_used_in_module('oscillator', cc_number) or \
                   self._is_cc_used_in_module('filter', cc_number) or \
                   self._is_cc_used_in_module('amplifier', cc_number):
                    if ROUTER_DEBUG:
                        print(f"[ROUTER] CC {cc_number} accepted: used in module control")
                    return True
                    
                if ROUTER_DEBUG:
                    print(f"[ROUTER] CC {cc_number} rejected: not used in configuration")
                return False
        
        # Other control messages
        elif msg_type in ['pitch_bend', 'channel_pressure']:
            source_type = 'pitch_bend' if msg_type == 'pitch_bend' else 'channel_pressure'
            if source_type in sources:
                if ROUTER_DEBUG:
                    print(f"[ROUTER] {msg_type} accepted")
                return True
        
        if ROUTER_DEBUG:
            print(f"[ROUTER] Message rejected: {msg_type}")
        return False
    
    def _is_cc_used_in_module(self, module_name, cc_number):
        """Check if a CC number is used in a module's controls"""
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
            if ROUTER_DEBUG:
                print("[ROUTER] No transformation config, returning original value")
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
        
        if ROUTER_DEBUG:
            print(f"[ROUTER] Value transformation:")
            print(f"  Original value: {original_value}")
            print(f"  Curve: {curve}")
            print(f"  Transformed value: {value}")
        
        return value
    
    def route_message(self, message):
        """
        Route a MIDI message through the instrument's configuration.
        
        Args:
            message (dict): Incoming MIDI message
        
        Returns:
            dict: Routing result or None
        """
        if ROUTER_DEBUG:
            print("[ROUTER] Routing message:")
            print(f"  Message: {message}")
        
        if not self._is_message_allowed(message):
            if ROUTER_DEBUG:
                print("[ROUTER] Message validation failed")
            return None
        
        msg_type = message.get('type')
        data = message.get('data', {})
        channel = message.get('channel')
        
        # Handle note messages
        if msg_type in ['note_on', 'note_off']:
            note = data.get('note')
            velocity = data.get('velocity', 127) if msg_type == 'note_on' else 0
            
            if ROUTER_DEBUG:
                print(f"[ROUTER] Processing {msg_type}:")
                print(f"  Channel: {channel}")
                print(f"  Note: {note}")
                print(f"  Velocity: {velocity}")
            
            if msg_type == 'note_on':
                voice = self.voice_manager.allocate_voice(channel, note, velocity)
                if ROUTER_DEBUG:
                    print("[ROUTER] Voice allocated")
                return {'type': 'voice_allocated', 'voice': voice}
            else:
                voice = self.voice_manager.release_voice(channel, note)
                if ROUTER_DEBUG:
                    print("[ROUTER] Voice released")
                return {'type': 'voice_released', 'voice': voice}
        
        # Handle CC messages
        if msg_type == 'cc':
            return self._route_cc_message(message)
        
        # Handle other control messages
        patches = self.current_config.get('patches', [])
        if ROUTER_DEBUG:
            print(f"[ROUTER] Processing patches: {len(patches)} patches")
        
        for patch in patches:
            source = patch.get('source', {})
            destination = patch.get('destination', {})
            processing = patch.get('processing', {})
            
            if ROUTER_DEBUG:
                print("[ROUTER] Processing patch:")
                print(f"  Source: {source}")
                print(f"  Destination: {destination}")
                print(f"  Processing: {processing}")
            
            # Determine source value
            source_value = self._get_source_value(source, message)
            
            if source_value is not None:
                if ROUTER_DEBUG:
                    print(f"[ROUTER] Source value: {source_value}")
                
                # Transform value
                transformed_value = self._transform_value(
                    source_value, 
                    processing
                )
                
                # Apply modulation amount
                amount = processing.get('amount', 1.0)
                modulated_value = transformed_value * amount
                
                if ROUTER_DEBUG:
                    print("[ROUTER] Value processing:")
                    print(f"  Transformed value: {transformed_value}")
                    print(f"  Modulation amount: {amount}")
                    print(f"  Modulated value: {modulated_value}")
                
                # Route to destination
                self._route_to_destination(
                    destination, 
                    modulated_value, 
                    message
                )
        
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
        
        if ROUTER_DEBUG:
            print("[ROUTER] Routing CC message:")
            print(f"  CC Number: {cc_number}")
            print(f"  CC Value: {cc_value}")
        
        # Check CC routing in configuration
        cc_routing = self.current_config.get('cc_routing', {})
        
        if str(cc_number) in cc_routing:
            route = cc_routing[str(cc_number)]
            if ROUTER_DEBUG:
                print("[ROUTER] CC Route found:")
                print(f"  Name: {route.get('name')}")
                print(f"  Target: {route.get('target')}")
                print(f"  Path: {route.get('path')}")
            
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
        
        if ROUTER_DEBUG:
            print("[ROUTER] Extracting source value:")
            print(f"  Source ID: {source_id}")
            print(f"  Attribute: {attribute}")
            print(f"  Message Type: {msg_type}")
            print(f"  Message Data: {data}")
        
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
        
        if ROUTER_DEBUG:
            print("[ROUTER] No source value found")
        
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
        
        if ROUTER_DEBUG:
            print("[ROUTER] Routing to destination:")
            print(f"  Destination ID: {dest_id}")
            print(f"  Attribute: {attribute}")
            print(f"  Value: {value}")
        
        # Find the corresponding voice
        channel = message.get('channel')
        note = message.get('data', {}).get('note')
        voice = self.voice_manager.get_voice(channel, note)
        
        if voice:
            if ROUTER_DEBUG:
                print("[ROUTER] Voice found for routing")
            
            # Route to specific module/parameter
            if dest_id == 'oscillator' and attribute == 'frequency':
                if ROUTER_DEBUG:
                    print("[ROUTER] Routing to oscillator frequency")
                voice.handle_value_change('frequency', value)
            elif dest_id == 'amplifier' and attribute == 'gain':
                if ROUTER_DEBUG:
                    print("[ROUTER] Routing to amplifier gain")
                voice.handle_value_change('amplitude', value)
            elif dest_id == 'filter' and attribute == 'frequency':
                if ROUTER_DEBUG:
                    print("[ROUTER] Routing to filter frequency")
                voice.handle_value_change('filter_freq', value)
            
            if ROUTER_DEBUG:
                print("[ROUTER] Destination routing complete")
    
    def process_updates(self):
        """Process any pending updates in voice management"""
        self.voice_manager.cleanup_voices()
