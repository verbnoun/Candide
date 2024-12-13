"""Parameter and path management module."""

import synthio
import array
import math
from logging import log, TAG_ROUTE
from interfaces import SynthioInterfaces, WaveformMorph

# Parameters that should stay as integers
INTEGER_PARAMS = {
    'note_number',      # MIDI note numbers are integers
    'morph_position',   # Used as MIDI value (0-127) for waveform lookup
    'ring_morph_position'  # Used as MIDI value (0-127) for waveform lookup
}

class ValueType:
    """Handles all value conversions and validations."""
    
    @staticmethod
    def to_waveform(value):
        """Convert string to waveform buffer or morph table.
        
        Args:
            value: String like 'sine' or 'sine-triangle-square'
        """
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
        """Convert string to number or range tuple.
        
        Args:
            value: String like '220' or '0.001-1'
            as_int: Whether to convert to integer
        
        Returns:
            Single value or (min, max) tuple
        """
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
        """Convert note number or direct frequency.
        
        Args:
            value: 'note_number' or frequency string
        """
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
        """Build lookup table for value definition.
        
        Args:
            value_def: Range string, direct value, or special type
            is_14_bit: Whether input is 14-bit value
            
        Returns:
            Lookup table or direct value
        """
        try:
            # Handle None value_def (direct actions like press/release)
            if value_def is None:
                return None
                
            # Handle waveform types
            if any(wave in str(value_def) for wave in ('sine', 'triangle', 'square', 'saw', 'noise')):
                return ValueType.to_waveform(value_def)
                
            # Handle note to frequency conversion
            if value_def == 'note_number':
                return self.note_to_freq
                
            # Handle range conversion
            if '-' in value_def:
                min_val, max_val = ValueType.to_number(value_def)
                return self._build_range_table(min_val, max_val, is_14_bit)
                
            # For direct values, create single-value table
            value = ValueType.to_number(value_def)
            table = array.array('f', [value])
            return table
            
        except Exception as e:
            raise ValueError(str(e))

class TargetRouter:
    """Routes values to synthesizer targets."""
    def __init__(self):
        # Special case handlers for note press/release
        self.note_actions = {
            'press': ('handle_press', None, 'press'),
            'release': ('handle_release', None, 'release')
        }
        
        # Component handlers
        self.handlers = {
            'oscillator': {
                'frequency': ('store_value', 'frequency'),
                'waveform': ('update_parameter', 'waveform'),
                'ring/frequency': ('update_parameter', 'ring_frequency'),
                'ring/waveform': ('update_parameter', 'ring_waveform')
            },
            'filter': {
                'high_pass/frequency': ('update_parameter', 'filter_frequency'),
                'high_pass/resonance': ('update_parameter', 'filter_resonance'),
                'low_pass/frequency': ('update_parameter', 'filter_frequency'),
                'low_pass/resonance': ('update_parameter', 'filter_resonance'),
                'band_pass/frequency': ('update_parameter', 'filter_frequency'),
                'band_pass/resonance': ('update_parameter', 'filter_resonance'),
                'notch/frequency': ('update_parameter', 'filter_frequency'),
                'notch/resonance': ('update_parameter', 'filter_resonance')
            },
            'amplifier': {
                'amplitude': ('update_parameter', 'amplitude'),
                'envelope': {
                    'attack_level': ('update_envelope_param', 'attack_level'),
                    'attack_time': ('update_envelope_param', 'attack_time'),
                    'decay_time': ('update_envelope_param', 'decay_time'),
                    'sustain_level': ('update_envelope_param', 'sustain_level'),
                    'release_time': ('update_envelope_param', 'release_time')
                }
            }
        }
        
    def get_handler(self, path_parts):
        """Get handler info for path.
        
        Returns:
            Tuple of (handler_name, target, action) or None if not found
        """
        # Special case: note press/release actions
        if len(path_parts) == 2 and path_parts[0] == 'note' and path_parts[1] in ('press', 'release'):
            return self.note_actions.get(path_parts[1])
            
        # For paths starting with note, strip the note prefix
        if path_parts[0] == 'note':
            path_parts = path_parts[1:]
            
        # Handle component paths
        if not path_parts:
            return None
            
        component = path_parts[0]
        if component not in self.handlers:
            return None
            
        # Get the parameter path (everything after component)
        param_path = '/'.join(path_parts[1:])
        
        # Look up handler based on component
        if component == 'amplifier' and param_path.startswith('envelope/'):
            # Special case for envelope parameters
            envelope_param = param_path.split('/')[1]
            handler_info = self.handlers[component]['envelope'].get(envelope_param)
            if handler_info:
                return (handler_info[0], handler_info[1], None)
        else:
            # Normal component paths
            handler_info = self.handlers[component].get(param_path)
            if handler_info:
                # Store filter type if this is a filter path
                if component == 'filter':
                    self.filter_type = path_parts[1]
                return (handler_info[0], handler_info[1], None)
            
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
        if trigger.startswith('cc'):
            cc_num = int(trigger[2:])
            self.enabled_messages.add('cc')
            self.enabled_ccs.add(cc_num)
        elif trigger in ('note_on', 'note_off'):
            self.enabled_messages.add(trigger.replace('_', ''))
        elif trigger == 'pressure':
            self.enabled_messages.add('channelpressure')
        elif trigger == 'pitch_bend':
            self.enabled_messages.add('pitchbend')
            
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
                        
                    # Special case: note press/release actions
                    if parts[0] == 'note' and parts[1] in ('press', 'release'):
                        trigger = parts[-1]
                        target_parts = parts[:-1]  # Include press/release in target
                        value_def = None
                    else:
                        # Get trigger from last part
                        trigger = parts[-1]
                        
                        # Find parameter name in path
                        param_index = None
                        for i, part in enumerate(parts[:-1]):  # Skip trigger
                            if part in ('frequency', 'waveform', 'amplitude', 'resonance',
                                      'attack_level', 'attack_time', 'decay_time',
                                      'sustain_level', 'release_time'):
                                param_index = i
                                break
                                
                        if param_index is None:
                            raise ValueError(f"No parameter found in path: {line}")
                            
                        # Value comes right after parameter
                        value_def = parts[param_index + 1]
                        
                        # Target path is everything before value
                        target_parts = parts[:param_index + 1]
                    
                    # Track MIDI message
                    self._track_midi_message(trigger)
                    
                    # Get handler info
                    handler_info = self.target_router.get_handler(target_parts)
                    if not handler_info:
                        raise ValueError(f"Invalid target path: {'/'.join(target_parts)}")
                        
                    handler, target, action = handler_info  # Now includes action
                    
                    # Create action dict
                    action_dict = {
                        'handler': handler,
                        'trigger': trigger
                    }
                    
                    # Add target if provided
                    if target:
                        action_dict['target'] = target
                        
                    # Add action type if provided
                    if action:
                        action_dict['action'] = action
                        
                    # Add channel flag for note paths
                    if parts[0] == 'note':
                        action_dict['use_channel'] = True
                        
                    # Build lookup table for all values including set
                    is_14_bit = (trigger == 'pitch_bend')
                    lookup = self.value_converter.build_lookup_table(value_def, is_14_bit)
                    if lookup is not None:
                        action_dict['lookup'] = lookup
                        # Mark waveform actions
                        if target == 'waveform' or target == 'ring_waveform':
                            action_dict['is_waveform'] = True
                        
                    # Add to mappings
                    if trigger not in self.midi_mappings:
                        self.midi_mappings[trigger] = []
                    self.midi_mappings[trigger].append(action_dict)
                    
                    # Update feature flags
                    if parts[0] == 'filter':
                        self.has_filter = True
                        self.filter_type = parts[1]
                    elif parts[0] == 'amplifier' and parts[1] == 'envelope':
                        self.has_envelope_paths = True
                    elif 'ring' in parts:
                        self.has_ring_mod = True
                    elif 'waveform' in parts and '-' in str(value_def):
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
