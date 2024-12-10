"""Parameter and path management module."""

import synthio
import array
import math
from logging import log, TAG_ROUTE

# Parameters that should stay as integers
INTEGER_PARAMS = {
    'note_number',      # MIDI note numbers are integers
    'morph_position',   # Used as MIDI value (0-127) for waveform lookup
    'ring_morph_position'  # Used as MIDI value (0-127) for waveform lookup
}

class Route:
    """Creates a route that maps MIDI values to parameter values."""
    def __init__(self, name, min_val=None, max_val=None, fixed_value=None, is_integer=False):
        self.name = name
        self.is_integer = is_integer
        self.fixed_value = fixed_value
        
        # Only create lookup table if range is specified
        if min_val is not None and max_val is not None:
            self.min_val = float(min_val)
            self.max_val = float(max_val)
            self.lookup_table = array.array('f', [0] * 128)
            self._build_lookup()
            log(TAG_ROUTE, "Created route: {} [{} to {}] {}".format(
                name, min_val, max_val, '(integer)' if is_integer else ''))
        else:
            self.lookup_table = None
            if fixed_value is not None:
                log(TAG_ROUTE, f"Created route: {name} [fixed: {fixed_value}]")
            else:
                log(TAG_ROUTE, f"Created route: {name} [pass through]")
        
    def _build_lookup(self):
        """Build MIDI value lookup table for fast conversion."""
        for i in range(128):
            normalized = i / 127.0
            value = self.min_val + normalized * (self.max_val - self.min_val)
            self.lookup_table[i] = int(value) if self.is_integer else value
            
        log(TAG_ROUTE, "Lookup table for {} (sample values):".format(self.name))
        log(TAG_ROUTE, "  0: {}".format(self.lookup_table[0]))
        log(TAG_ROUTE, " 64: {}".format(self.lookup_table[64]))
        log(TAG_ROUTE, "127: {}".format(self.lookup_table[127]))
    
    def convert(self, midi_value):
        """Convert MIDI value to parameter value."""
        if not 0 <= midi_value <= 127:
            log(TAG_ROUTE, "Invalid MIDI value {} for {}".format(midi_value, self.name), is_error=True)
            raise ValueError("MIDI value must be between 0 and 127")
            
        if self.fixed_value is not None:
            return self.fixed_value
            
        if self.lookup_table is None:
            return midi_value
            
        value = self.lookup_table[midi_value]
        
        # Convert to float unless parameter is in INTEGER_PARAMS
        if self.name not in INTEGER_PARAMS:
            try:
                value = float(value)
            except (TypeError, ValueError) as e:
                log(TAG_ROUTE, f"Failed to convert parameter {self.name} to float: {str(e)}", is_error=True)
                raise
                
        return value

    def __str__(self):
        if self.fixed_value is not None:
            return f"Route(fixed: {self.fixed_value})"
        elif self.lookup_table is None:
            return "Route(pass through)"
        else:
            return f"Route({self.min_val}-{self.max_val})"

class PathParser:
    """Parses instrument paths and manages parameter conversions."""
    def __init__(self):
        # Core collections for parameter management
        self.midi_mappings = {}  # trigger -> [action objects]
        self.enabled_messages = set()
        self.enabled_ccs = set()
        self.set_values = {}     # Values that have been set
        
        # Feature flags - only set when corresponding paths are found
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_morph = False
        self.has_ring_waveform_morph = False
        self.has_math_ops = False
        self.has_lfo = False
        
        # Path configurations - only set when found in paths
        self.filter_type = None
        self.waveform_sequence = None
        self.ring_waveform_sequence = None
        
    def parse_paths(self, paths, config_name=None):
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
                    self._parse_line(parts)
                except Exception as e:
                    log(TAG_ROUTE, f"Error parsing path: {line} - {str(e)}", is_error=True)
                    raise
                    
            # Log complete routing table
            log(TAG_ROUTE, "Complete routing table:")
            for trigger, actions in self.midi_mappings.items():
                log(TAG_ROUTE, f"{trigger} -> [")
                for action in actions:
                    if 'action' in action:
                        log(TAG_ROUTE, f"  {{handler: {action['handler']}, action: {action['action']}, scope: {action['scope']}}}")
                    elif 'source' in action:
                        log(TAG_ROUTE, f"  {{handler: {action['handler']}, target: {action['target']}, scope: {action['scope']}, source: {action['source']}}}")
                    elif 'lookup' in action:
                        log(TAG_ROUTE, f"  {{handler: {action['handler']}, target: {action['target']}, scope: {action['scope']}, lookup: {action['lookup']}}}")
                    else:
                        log(TAG_ROUTE, f"  {{handler: {action['handler']}, target: {action['target']}, scope: {action['scope']}, value: {action['value']}}}")
                log(TAG_ROUTE, "]")
                
            # Log set values
            if self.set_values:
                log(TAG_ROUTE, "Set values:")
                for name, value in self.set_values.items():
                    log(TAG_ROUTE, f"  {name}: {value}")
                
            # Log enabled messages
            log(TAG_ROUTE, f"Enabled messages: {self.enabled_messages}")
            if 'cc' in self.enabled_messages:
                log(TAG_ROUTE, f"Enabled CCs: {self.enabled_ccs}")
                
            log(TAG_ROUTE, "----------------------------------------")
            
        except Exception as e:
            log(TAG_ROUTE, f"Failed to parse paths: {str(e)}", is_error=True)
            raise
    
    def _reset(self):
        """Reset all collections before parsing new paths."""
        self.midi_mappings.clear()
        self.enabled_messages.clear()
        self.enabled_ccs.clear()
        self.set_values.clear()
        
        # Reset feature flags
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_morph = False
        self.has_ring_waveform_morph = False
        self.has_math_ops = False
        self.has_lfo = False
        
        # Reset path configurations
        self.filter_type = None
        self.waveform_sequence = None
        self.ring_waveform_sequence = None

    def _parse_range(self, range_str):
        """Parse a range string, handling negative numbers with 'n' prefix."""
        try:
            if '-' not in range_str:
                raise ValueError(f"Invalid range format: {range_str}")
                
            min_str, max_str = range_str.split('-')
            
            # Handle negative numbers with 'n' prefix
            if min_str.startswith('n'):
                min_val = -float(min_str[1:])
            else:
                min_val = float(min_str)
                
            max_val = float(max_str)
            return min_val, max_val
            
        except ValueError as e:
            raise ValueError(f"Invalid range format {range_str}: {str(e)}")
            
    def _parse_routing(self, parts):
        """Parse path to build routing info."""
        # Get trigger (note_on, cc74, etc)
        trigger = parts[-1]
        if trigger.startswith('cc'):
            trigger = f"cc{int(trigger[2:])}"
            self.enabled_messages.add('cc')
            self.enabled_ccs.add(int(trigger[2:]))
        elif trigger in ('note_on', 'note_off'):
            self.enabled_messages.add(trigger.replace('_', ''))
        elif trigger == 'pressure':
            self.enabled_messages.add('pressure')
        elif trigger == 'pitch_bend':
            self.enabled_messages.add('pitchbend')
        elif trigger == 'set':
            # Handle set values separately
            value_part = parts[-2]
            try:
                # Convert numeric values to float unless in INTEGER_PARAMS
                if parts[1] not in INTEGER_PARAMS:
                    value = float(value_part)
                else:
                    value = int(value_part)
            except ValueError:
                # Not a numeric value, leave as-is (e.g., waveform types)
                value = value_part
                
            # Store in set_values and create action
            if parts[0] == 'oscillator':
                if parts[1] == 'frequency':
                    target = 'frequency'
                    handler = 'update_voice_parameter'
                elif parts[1] == 'waveform':
                    target = 'waveform'
                    handler = 'update_global_waveform'
                elif parts[1] == 'ring':
                    target = f'ring_{parts[2]}'
                    handler = 'update_ring_modulation'
            elif parts[0] == 'filter':
                target = f'filter_{parts[2]}'
                handler = 'update_global_filter'
                self.filter_type = parts[1]
            elif parts[0] == 'amplifier' and parts[1] == 'envelope':
                target = parts[2]
                handler = 'update_global_envelope'
                
            self.set_values[target] = value
            log(TAG_ROUTE, f"Found set value for {target}: {value}")
            
            # Create action for set value
            action = {
                'handler': handler,
                'target': target,
                'scope': 'global' if 'global' in parts else 'per_key',
                'value': value
            }
            
            # Initialize array if needed
            if trigger not in self.midi_mappings:
                self.midi_mappings[trigger] = []
            self.midi_mappings[trigger].append(action)
            return
            
        # Initialize array if needed
        if trigger not in self.midi_mappings:
            self.midi_mappings[trigger] = []
            
        # Create appropriate action object
        if parts[0] == 'note' and parts[1] in ('press', 'release'):
            # Direct action
            action = {
                'handler': f'handle_{parts[1]}',
                'action': parts[1],
                'scope': parts[2]  # per_key
            }
        else:
            # Value path
            value_part = parts[-2]
            scope = 'global' if 'global' in parts else 'per_key'
            
            # Determine target and handler
            if parts[0] == 'oscillator':
                if parts[1] == 'frequency':
                    target = 'frequency'
                    handler = 'update_voice_parameter'
                elif parts[1] == 'waveform':
                    if 'morph' in parts:
                        target = 'morph'
                        handler = 'update_morph_position'
                    else:
                        target = 'waveform'
                        handler = 'update_global_waveform'
                        # Add waveform to set_values
                        if value_part in ('sine', 'triangle', 'square', 'saw'):
                            self.set_values['waveform'] = value_part
                elif parts[1] == 'ring':
                    target = f'ring_{parts[2]}'  # ring_frequency, ring_bend
                    handler = 'update_ring_modulation'
                elif parts[1] in ('pitch', 'timbre', 'pressure'):
                    target = parts[1]
                    handler = 'update_voice_parameter'
            elif parts[0] == 'filter':
                target = f'filter_{parts[2]}'  # filter_frequency, filter_resonance
                handler = 'update_global_filter'
                self.filter_type = parts[1]
            elif parts[0] == 'amplifier' and parts[1] == 'envelope':
                target = parts[2]  # attack_time, decay_time, etc
                handler = 'update_global_envelope'
            elif parts[0] == 'math':
                target = f'math_{parts[1]}'  # math_sum, math_add_sub, etc
                handler = 'update_math_parameter'
                self.has_math_ops = True
            elif parts[0] == 'lfo':
                if parts[1] == 'target':
                    target = f'lfo_target_{parts[2]}'  # lfo_target_filter_frequency, etc
                    handler = 'update_lfo_target'
                elif parts[1] == 'waveform':
                    target = 'lfo_waveform'
                    handler = 'update_lfo_waveform'
                else:
                    target = f'lfo_{parts[1]}'  # lfo_rate, lfo_scale, etc
                    handler = 'update_lfo_parameter'
                self.has_lfo = True
                
            action = {
                'handler': handler,
                'target': target,
                'scope': scope
            }
            
            # Determine value source
            if value_part in ('note_number', 'velocity', 'pressure'):
                action['source'] = value_part
            elif '-' in value_part and not any(w in value_part for w in ('sine', 'triangle', 'square', 'saw')):
                min_val, max_val = self._parse_range(value_part)
                action['lookup'] = Route(target, min_val, max_val, is_integer=target in INTEGER_PARAMS)
            else:
                action['value'] = value_part
                
        self.midi_mappings[trigger].append(action)
        
        # Set feature flags based on path
        if parts[0] == 'filter':
            self.has_filter = True
        elif parts[0] == 'amplifier' and parts[1] == 'envelope':
            self.has_envelope_paths = True
        elif parts[0] == 'oscillator':
            if parts[1] == 'waveform' and len(parts) >= 3 and parts[2] == 'morph':
                self.has_waveform_morph = True
                if len(parts) >= 5 and '-' in parts[4]:
                    self.waveform_sequence = parts[4].split('-')
            elif parts[1] == 'ring':
                self.has_ring_mod = True
                if len(parts) >= 4 and parts[2] == 'waveform' and parts[3] == 'morph':
                    self.has_ring_waveform_morph = True
                    if len(parts) >= 6 and '-' in parts[5]:
                        self.ring_waveform_sequence = parts[5].split('-')
    
    def _parse_line(self, parts):
        """Parse a single path line."""
        if len(parts) < 3:
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
        # Parse routing info
        self._parse_routing(parts)
