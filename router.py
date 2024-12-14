"""Parameter and path management module."""

import synthio
import array
import math
from logging import log, TAG_ROUTE
from interfaces import SynthioInterfaces, WaveformMorph
from router_dicts import INTEGER_PARAMS, VALUES, TARGETS, SOURCES

class ValueType:
    """Handles all value conversions and validations."""
    
    @staticmethod
    def parse_value(value_str):
        """Parse value string into type and data.
        
        Args:
            value_str: String like 'press', 'note_number', '0.001-1'
            
        Returns:
            Tuple of (type, data)
        """
        # Check for known value
        if value_str in VALUES:
            value_info = VALUES[value_str]
            return (value_info['type'], value_info)
            
        # Check for range
        if '-' in value_str:
            min_str, max_str = value_str.split('-')
            # Handle negative numbers with 'n' prefix
            min_val = -float(min_str[1:]) if min_str.startswith('n') else float(min_str)
            max_val = float(max_str)
            return ('range', (min_val, max_val))
            
        # Must be direct value
        return ('direct', value_str)
    
    @staticmethod
    def to_waveform(value):
        """Convert string to waveform buffer or morph table."""
        if '-' in value:
            # Multiple waveforms - create morph table
            log(TAG_ROUTE, f"Creating morph table for sequence: {value}")
            return WaveformMorph('waveform', value.split('-'))
            
        # Single waveform - create lookup table with one entry
        log(TAG_ROUTE, f"Creating single waveform: {value}")
        waveform = SynthioInterfaces.create_waveform(value)
        return array.array('h', waveform)  # Convert to array for consistent lookup
        
    @staticmethod
    def to_number(value, as_int=False):
        """Convert string to number or range tuple."""
        if '-' in value:
            # Parse range
            min_str, max_str = value.split('-')
            # Handle negative numbers with 'n' prefix
            min_val = -float(min_str[1:]) if min_str.startswith('n') else float(min_str)
            max_val = float(max_str)
            if as_int:
                return (int(min_val), int(max_val))
            return (min_val, max_val)
        # Parse direct value
        return int(value) if as_int else float(value)
        
    @staticmethod
    def to_frequency(value):
        """Convert note number or direct frequency."""
        if value == 'note_number':
            table = array.array('f', [0] * 128)
            for i in range(128):
                table[i] = synthio.midi_to_hz(i)
            return table
        return float(value)

class ValueConverter:
    """Converts input values to target ranges."""
    def __init__(self):
        self.note_to_freq = ValueType.to_frequency('note_number')
        
    def _build_range_table(self, min_val, max_val, is_14_bit=False):
        """Build lookup table for range conversion."""
        size = 16384 if is_14_bit else 128
        table = array.array('f', [0] * size)
        
        if is_14_bit:
            # For 14-bit values, normalize around center point (8192)
            center = size // 2
            for i in range(size):
                normalized = (i - center) / center
                table[i] = min_val + normalized * (max_val - min_val)
        else:
            # Standard 7-bit MIDI normalization
            for i in range(size):
                normalized = i / (size - 1)
                table[i] = min_val + normalized * (max_val - min_val)
                
        return table
        
    def build_lookup_table(self, value_def, is_14_bit=False):
        """Build lookup table for value definition."""
        try:
            # Handle None value_def (direct actions like press/release)
            if value_def is None:
                return None
                
            # Parse value type and data
            value_type, value_data = ValueType.parse_value(value_def)
            
            # Handle value types
            if value_type == 'action':
                return None  # Actions don't need lookup tables
                
            elif value_type == 'special':
                if 'converter' in value_data:
                    if value_data['converter'] == 'note_to_freq':
                        return self.note_to_freq
                elif 'range' in value_data:
                    min_val, max_val = value_data['range']
                    return self._build_range_table(min_val, max_val, is_14_bit)
                    
            elif value_type == 'waveform':
                return ValueType.to_waveform(value_data['waveform'])
                
            elif value_type == 'range':
                min_val, max_val = value_data
                return self._build_range_table(min_val, max_val, is_14_bit)
                
            elif value_type == 'direct':
                # For direct values, create single-value table
                value = ValueType.to_number(value_data)
                table = array.array('f', [value])
                return table
                
        except Exception as e:
            raise ValueError(str(e))

class TargetRouter:
    """Routes values to synthesizer targets."""
    def __init__(self):
        # No initialization needed - just use TARGETS dictionary
        pass
        
    def get_handler(self, path_parts):
        """Get handler info for path."""
        # Get full path
        path = '/'.join(path_parts)
        
        # Look up in TARGETS
        target = TARGETS.get(path)
        if target:
            return (target['handler'], target['synth_param'], target.get('action'))
            
        # For paths starting with note, check if rest is a target
        if path_parts[0] == 'note':
            rest_path = '/'.join(path_parts[1:])
            target = TARGETS.get(rest_path)
            if target:
                return (target['handler'], target['synth_param'], target.get('action'))
            
        return None

class PathParser:
    """Maps MIDI values to synthesizer actions."""
    def __init__(self):
        # Core collections
        self.midi_mappings = {}
        self.enabled_messages = set()
        self.enabled_ccs = set()
        
        # Feature flags
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_sequence = False
        self.filter_type = None
        self.waveform_sequence = None
        
        # Initialize components
        self.value_converter = ValueConverter()
        self.target_router = TargetRouter()
        
    def _reset(self):
        """Reset all collections before parsing new paths."""
        self.midi_mappings.clear()
        self.enabled_messages.clear()
        self.enabled_ccs.clear()
        
        # Reset feature flags
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_sequence = False
        self.filter_type = None
        self.waveform_sequence = None
        
    def _track_midi_message(self, trigger):
        """Update enabled messages and CCs based on trigger."""
        # Get source info
        source = SOURCES.get(trigger)
        if not source:
            return
            
        # Track MIDI type
        if source['midi_type'].startswith('cc'):
            self.enabled_messages.add('cc')
            self.enabled_ccs.add(source['cc_number'])
        else:
            # Use midi_type for enabled messages
            self.enabled_messages.add(source['midi_type'])
            
    def parse_paths(self, paths: str, config_name=None):
        """Parse instrument paths to extract parameters and mappings."""
        log(TAG_ROUTE, "Parsing instrument paths...")
        log(TAG_ROUTE, "----------------------------------------")
        
        if config_name:
            log(TAG_ROUTE, f"Using paths configuration: {config_name}")
            
        try:
            self._reset()
            
            if not paths:
                raise ValueError("No paths provided")
                
            for line in paths.strip().split('\n'):
                if not line or line.startswith('#'):
                    continue
                    
                try:
                    parts = line.strip().split('/')
                    if len(parts) < 3:
                        continue
                        
                    # Special handling for note/release/note_off path
                    if parts[0] == 'note' and parts[1] == 'release' and parts[-1] == 'note_off':
                        trigger = 'note_off'  # Use note_off as trigger
                        value_def = None
                        target_parts = ['note', 'release', 'note_off']
                    else:
                        # Normal path handling
                        trigger = parts[-1]
                        value_def = parts[-2] if len(parts) > 2 else None
                        target_parts = parts[:-2] if value_def else parts[:-1]
                        
                    target_path = '/'.join(target_parts)
                    
                    # Get source info
                    source = SOURCES.get(trigger)
                    if not source:
                        raise ValueError(f"Unknown source: {trigger}")
                        
                    # Get target info
                    target = TARGETS.get(target_path)
                    if not target:
                        raise ValueError(f"Invalid target path: {target_path}")
                        
                    # Track MIDI message
                    self._track_midi_message(trigger)
                    
                    # Create action dict
                    action_dict = {
                        'handler': target['handler'],
                        'trigger': source['midi_type']  # Use source midi_type
                    }
                    
                    # Add target if provided
                    if target['synth_param']:
                        action_dict['target'] = target['synth_param']
                        
                    # Add action type if provided
                    if 'action' in target:
                        action_dict['action'] = target['action']
                        
                    # Add channel flag if target uses channels
                    if target.get('use_channel') or target_path.startswith('note/'):
                        action_dict['use_channel'] = True
                        
                    # Build lookup table for all values including set
                    is_14_bit = (source['value_type'] == 'continuous_14bit')
                    lookup = self.value_converter.build_lookup_table(value_def, is_14_bit)
                    if lookup is not None:
                        action_dict['lookup'] = lookup
                        # Mark waveform actions
                        if target['synth_property'] == 'waveform':
                            action_dict['is_waveform'] = True
                        
                    # Add to mappings using trigger name
                    mapping_key = trigger  # Always use trigger name
                    if mapping_key not in self.midi_mappings:
                        self.midi_mappings[mapping_key] = []
                    self.midi_mappings[mapping_key].append(action_dict)
                    
                    # Update feature flags
                    if target_path.startswith('filter/'):
                        self.has_filter = True
                        self.filter_type = target_parts[1]
                    elif target_path.startswith('amplifier/envelope/'):
                        self.has_envelope_paths = True
                    elif 'ring' in target_path:
                        self.has_ring_mod = True
                    elif target['synth_property'] == 'waveform' and value_def and '-' in value_def:
                        self.has_waveform_sequence = True
                        self.waveform_sequence = value_def.split('-')
                    
                except Exception as e:
                    log(TAG_ROUTE, f"Error parsing path: {line} - {str(e)}", is_error=True)
                    raise
                    
            # Log complete routing table
            log(TAG_ROUTE, "Complete routing table:")
            for trigger, actions in self.midi_mappings.items():
                log(TAG_ROUTE, f"{trigger} -> [")
                for action in actions:
                    if 'target' in action:
                        log(TAG_ROUTE, f"  {{handler: {action['handler']}, target: {action['target']}, use_channel: {action.get('use_channel', False)}, lookup: {type(action.get('lookup', None)).__name__}}}")
                    else:
                        log(TAG_ROUTE, f"  {{handler: {action['handler']}, use_channel: {action.get('use_channel', False)}, lookup: {type(action.get('lookup', None)).__name__}}}")
                log(TAG_ROUTE, "]")
                
            # Log enabled messages
            log(TAG_ROUTE, f"Enabled messages: {self.enabled_messages}")
            if 'cc' in self.enabled_messages:
                log(TAG_ROUTE, f"Enabled CCs: {self.enabled_ccs}")
                
            log(TAG_ROUTE, "----------------------------------------")
            
        except Exception as e:
            log(TAG_ROUTE, f"Failed to parse paths: {str(e)}", is_error=True)
            raise
            
    def get_value(self, action, input_value):
        """Get value from pre-computed lookup table."""
        # For actions with lookup tables, use table
        if 'lookup' in action:
            # For waveforms, return whole buffer
            if action.get('is_waveform'):
                return action['lookup']
                
            # For numeric lookup tables
            if isinstance(action['lookup'], array.array):
                if not 0 <= input_value < len(action['lookup']):
                    raise ValueError(f"Input value {input_value} out of range")
                return action['lookup'][input_value]
                
            # For WaveformMorph, get waveform for input value
            if hasattr(action['lookup'], 'get_waveform'):
                return action['lookup'].get_waveform(input_value)
                
            return action['lookup']  # Direct value
            
        # For actions without lookup, return input directly
        return input_value
