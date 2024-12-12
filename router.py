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

# Parameters that synthio handles per-note
PER_NOTE_PARAMS = {
    'bend', 'amplitude', 'panning', 'waveform',
    'waveform_loop_start', 'waveform_loop_end',
    'filter', 'ring_frequency', 'ring_bend',
    'ring_waveform', 'ring_waveform_loop_start',
    'ring_waveform_loop_end'
}

class Route:
    """Creates a route that maps MIDI values to parameter values."""
    def __init__(self, name, min_val=None, max_val=None, fixed_value=None, is_integer=False, 
                 is_note_to_freq=False, waveform_sequence=None, is_14_bit=False):
        self.name = name
        self.is_integer = is_integer
        self.fixed_value = fixed_value
        self.is_note_to_freq = is_note_to_freq
        self.is_waveform_sequence = waveform_sequence is not None
        self.is_14_bit = is_14_bit
        self.waveform_sequence = waveform_sequence
        self.waveform_morph = None
        
        # Initialize WaveformMorph if sequence provided
        if self.is_waveform_sequence:
            self.waveform_morph = WaveformMorph(name, waveform_sequence)
            log(TAG_ROUTE, f"Created morph table for {'-'.join(waveform_sequence)}")
        
        # Only create lookup table if range is specified or note_to_freq
        if is_note_to_freq or (min_val is not None and max_val is not None):
            # Use 14-bit table size for 14-bit values
            table_size = 16384 if is_14_bit else 128
            self.lookup_table = array.array('f', [0] * table_size)
            if is_note_to_freq:
                self._build_note_to_freq_lookup()
                log(TAG_ROUTE, "Created route: {} [MIDI note to Hz]".format(name))
            else:
                self.min_val = float(min_val)
                self.max_val = float(max_val)
                self._build_lookup()
                log(TAG_ROUTE, "Created route: {} [{} to {}] {}".format(
                    name, min_val, max_val, '(integer)' if is_integer else ''))
        else:
            self.lookup_table = None
            if fixed_value is not None:
                log(TAG_ROUTE, f"Created route: {name} [fixed: {fixed_value}]")
            else:
                log(TAG_ROUTE, f"Created route: {name} [pass through]")
    
    def _build_note_to_freq_lookup(self):
        """Build lookup table for MIDI note number to Hz conversion."""
        for i in range(128):
            self.lookup_table[i] = synthio.midi_to_hz(i)
            
        log(TAG_ROUTE, "Note to Hz lookup table for {} (sample values):".format(self.name))
        log(TAG_ROUTE, "  0: {:.2f} Hz".format(self.lookup_table[0]))
        log(TAG_ROUTE, " 60 (middle C): {:.2f} Hz".format(self.lookup_table[60]))
        log(TAG_ROUTE, " 69 (A440): {:.2f} Hz".format(self.lookup_table[69]))
        log(TAG_ROUTE, "127: {:.2f} Hz".format(self.lookup_table[127]))
        
    def _build_lookup(self):
        """Build MIDI value lookup table for fast conversion."""
        table_size = len(self.lookup_table)
        
        if self.is_14_bit:
            # For 14-bit values, normalize around center point (8192)
            center = table_size // 2
            for i in range(table_size):
                normalized = (i - center) / center
                value = self.min_val + normalized * (self.max_val - self.min_val)
                self.lookup_table[i] = int(value) if self.is_integer else value
        else:
            # Standard 7-bit MIDI normalization
            for i in range(table_size):
                normalized = i / (table_size - 1)
                value = self.min_val + normalized * (self.max_val - self.min_val)
                self.lookup_table[i] = int(value) if self.is_integer else value
            
        log(TAG_ROUTE, "Lookup table for {} (sample values):".format(self.name))
        log(TAG_ROUTE, "  0: {}".format(self.lookup_table[0]))
        if self.is_14_bit:
            log(TAG_ROUTE, "  8192 (center): {}".format(self.lookup_table[8192]))
            log(TAG_ROUTE, "  16383: {}".format(self.lookup_table[16383]))
        else:
            log(TAG_ROUTE, "  64: {}".format(self.lookup_table[64]))
            log(TAG_ROUTE, "  127: {}".format(self.lookup_table[127]))
    
    def convert(self, midi_value):
        """Convert MIDI value to parameter value."""
        max_val = 16383 if self.is_14_bit else 127
        if not 0 <= midi_value <= max_val:
            log(TAG_ROUTE, "Invalid MIDI value {} for {}".format(midi_value, self.name), is_error=True)
            raise ValueError(f"MIDI value must be between 0 and {max_val}")
            
        if self.fixed_value is not None:
            return self.fixed_value
            
        if self.lookup_table is None:
            if self.is_waveform_sequence:
                # Get pre-calculated waveform from morph table
                return self.waveform_morph.get_waveform(midi_value)
            return midi_value
            
        # Get value from lookup table
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
            if self.is_waveform_sequence:
                return f"Route(waveform sequence: {'-'.join(self.waveform_sequence)})"
            return "Route(pass through)"
        elif self.is_note_to_freq:
            return "Route(MIDI note to Hz)"
        else:
            return f"Route({self.min_val}-{self.max_val})"

class PathParser:
    """Parses instrument paths and manages parameter conversions."""
    def __init__(self):
        # Core collections for parameter management
        self.midi_mappings = {}  # trigger -> [action objects]
        self.enabled_messages = set()
        self.enabled_ccs = set()
        
        # Feature flags - only set when corresponding paths are found
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_sequence = False
        self.has_ring_waveform_sequence = False
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
        
        # Reset feature flags
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_sequence = False
        self.has_ring_waveform_sequence = False
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
        
        # Handle standard MIDI message types
        if trigger.startswith('cc'):
            trigger = f"cc{int(trigger[2:])}"
            self.enabled_messages.add('cc')
            self.enabled_ccs.add(int(trigger[2:]))
        elif trigger in ('note_on', 'note_off'):
            self.enabled_messages.add(trigger.replace('_', ''))
        elif trigger == 'pressure':
            self.enabled_messages.add('channelpressure')
        elif trigger == 'pitch_bend':
            self.enabled_messages.add('pitchbend')
        elif trigger == 'set':
            # Handle set values - store directly in synth state through action
            value_part = parts[-2]
            
            # Get the actual parameter name based on path structure
            param_name = None
            if parts[0] == 'oscillator':
                if parts[1] == 'ring':
                    param_name = f'ring_{parts[2]}'  # frequency, bend, etc
                else:
                    param_name = parts[1]  # waveform, frequency, etc
            elif parts[0] == 'filter':
                param_name = f'filter_{parts[2]}'  # frequency, resonance, etc
            elif parts[0] == 'amplifier':
                if parts[1] == 'envelope':
                    param_name = parts[2]  # attack_time, decay_time, etc
                else:
                    param_name = parts[1]  # amplitude
            
            try:
                # Convert numeric values to float unless in INTEGER_PARAMS
                if param_name not in INTEGER_PARAMS:  # Check actual parameter name
                    # Handle negative numbers with 'n' prefix
                    if value_part.startswith('n'):
                        value = -float(value_part[1:])
                    else:
                        value = float(value_part)
                else:
                    value = int(value_part)
            except ValueError:
                # Not a numeric value, must be a waveform type
                if parts[0] == 'oscillator':
                    if parts[1] == 'waveform':
                        # Create waveform buffer immediately
                        value = SynthioInterfaces.create_waveform(value_part)
                    elif parts[1] == 'ring' and parts[2] == 'waveform':
                        # Create ring waveform buffer immediately
                        value = SynthioInterfaces.create_waveform(value_part)
                else:
                    value = value_part
                
            # Create store action based on path
            if parts[0] == 'oscillator':
                if parts[1] == 'frequency':
                    target = 'frequency'
                    handler = 'store_value'
                elif parts[1] == 'bend':
                    target = 'bend'
                    handler = 'update_parameter'
                elif parts[1] == 'waveform':
                    target = 'waveform'
                    handler = 'update_parameter'
                elif parts[1] == 'ring':
                    if parts[2] == 'waveform':
                        target = 'ring_waveform'
                        handler = 'update_parameter'
                    else:
                        target = f'ring_{parts[2]}'
                        handler = 'update_parameter'
            elif parts[0] == 'filter':
                target = f'filter_{parts[2]}'
                handler = 'update_parameter'
                self.filter_type = parts[1]
            elif parts[0] == 'amplifier':
                if parts[1] == 'envelope':
                    target = parts[2]
                    handler = 'update_global_envelope'
                elif parts[1] == 'amplitude':
                    target = 'amplifier_amplitude'
                    handler = 'update_parameter'
                
            # Determine scope based on path starting with 'note'
            scope = 'per_key' if parts[0] == 'note' else 'global'
                
            # Create action for storing value
            action = {
                'handler': handler,
                'target': target,
                'scope': scope,
                'value': value,
                'all_channels': scope == 'per_key'  # Set values for note paths go to all channels
            }
            
            # If global scope and target is a per-note parameter, store in all channels
            if scope == 'global' and target in PER_NOTE_PARAMS:
                action['store_in_channels'] = True
                log(TAG_ROUTE, f"Global per-note parameter {target} will be stored in all channels")
            
            # Initialize array if needed
            if trigger not in self.midi_mappings:
                self.midi_mappings[trigger] = []
            self.midi_mappings[trigger].append(action)
            
            log(TAG_ROUTE, f"Created store action for {target}: {value}")
            return
            
        # Initialize array if needed
        if trigger not in self.midi_mappings:
            self.midi_mappings[trigger] = []
            
        # Create appropriate action object
        if parts[0] == 'note':
            if parts[1] == 'press' or parts[1] == 'release':
                # Direct action
                action = {
                    'handler': f'handle_{parts[1]}',
                    'action': parts[1],
                    'scope': 'per_key'
                }
            else:
                # Nested path after note/ prefix
                # Skip 'note' prefix and process rest of path
                nested_parts = parts[1:]  # ['oscillator', 'frequency', 'bend', 'n1-1', 'pitch_bend']
                
                # Set default handler and target
                handler = 'update_parameter'
                target = None
                
                # Handle nested paths
                if nested_parts[0] == 'oscillator':
                    if nested_parts[1] == 'frequency':
                        target = 'frequency'
                        if nested_parts[-2] == 'note_number':
                            action = {
                                'handler': handler,
                                'target': target,
                                'scope': 'per_key',
                                'lookup': Route(target, is_note_to_freq=True)
                            }
                            self.midi_mappings[trigger].append(action)
                            return
                        elif nested_parts[2] == 'bend':
                            target = 'bend'
                            min_val, max_val = self._parse_range(nested_parts[-2])
                            action = {
                                'handler': handler,
                                'target': target,
                                'scope': 'per_key',
                                'lookup': Route(target, min_val=min_val, max_val=max_val, is_14_bit=True)
                            }
                            self.midi_mappings[trigger].append(action)
                            return
                    elif nested_parts[1] == 'ring':
                        if nested_parts[2] == 'frequency' and nested_parts[3] == 'bend':
                            target = 'ring_bend'
                            min_val, max_val = self._parse_range(nested_parts[-2])
                            action = {
                                'handler': handler,
                                'target': target,
                                'scope': 'per_key',
                                'lookup': Route(target, min_val=min_val, max_val=max_val, is_14_bit=True)
                            }
                            self.midi_mappings[trigger].append(action)
                            return
                    elif nested_parts[1] == 'waveform':
                        target = 'waveform'
                        if '-' in nested_parts[-2]:
                            waveform_sequence = nested_parts[-2].split('-')
                            action = {
                                'handler': handler,
                                'target': target,
                                'scope': 'per_key',
                                'lookup': Route(target, waveform_sequence=waveform_sequence)
                            }
                            self.waveform_sequence = waveform_sequence
                            self.has_waveform_sequence = True
                            self.midi_mappings[trigger].append(action)
                            return
                        else:
                            value = SynthioInterfaces.create_waveform(nested_parts[-2])
                            action = {
                                'handler': handler,
                                'target': target,
                                'scope': 'per_key',
                                'value': value
                            }
                elif nested_parts[0] == 'amplifier':
                    if nested_parts[1] == 'amplitude':
                        target = 'amplitude'
                        range_str = nested_parts[2]  # Get range value directly
                        min_val, max_val = self._parse_range(range_str)
                        
                        # Handle velocity and pressure
                        if nested_parts[-1] == 'note_on' and nested_parts[-2] == 'velocity':
                            action = {
                                'handler': handler,
                                'target': target,
                                'scope': 'per_key',
                                'lookup': Route(target, min_val=min_val, max_val=max_val)
                            }
                            self.midi_mappings[trigger].append(action)
                            return
                        elif nested_parts[-1] == 'pressure':
                            action = {
                                'handler': handler,
                                'target': target,
                                'scope': 'per_key',
                                'lookup': Route(target, min_val=min_val, max_val=max_val, is_14_bit=True)
                            }
                            self.midi_mappings[trigger].append(action)
                            return
                
                if target is None:
                    raise ValueError(f"Could not determine target for path: {'/'.join(parts)}")
                
                action = {
                    'handler': handler,
                    'target': target,
                    'scope': 'per_key'
                }
                
                # Determine value source
                if nested_parts[-2] in ('velocity', 'pressure'):
                    action['source'] = nested_parts[-2]
                elif '-' in nested_parts[-2]:
                    min_val, max_val = self._parse_range(nested_parts[-2])
                    action['lookup'] = Route(target, min_val, max_val, is_integer=target in INTEGER_PARAMS)
                else:
                    action['value'] = nested_parts[-2]
        else:
            # Global scope paths
            value_part = parts[-2]
            
            # Determine target and handler
            if parts[0] == 'oscillator':
                if parts[1] == 'frequency':
                    if parts[2] == 'bend':
                        target = 'bend'
                        handler = 'update_parameter'
                    else:
                        target = 'frequency'
                        handler = 'store_value'
                elif parts[1] == 'ring':
                    if parts[2] == 'frequency' and parts[3] == 'bend':
                        target = 'ring_bend'
                        handler = 'update_parameter'
                    elif parts[2] == 'waveform':
                        target = 'ring_waveform'
                        handler = 'update_parameter'
                    else:
                        target = f'ring_{parts[2]}'
                        handler = 'update_parameter'
                elif parts[1] == 'waveform':
                    target = 'waveform'
                    handler = 'update_parameter'
                    if '-' in value_part:
                        waveform_sequence = value_part.split('-')
                        action = {
                            'handler': handler,
                            'target': target,
                            'scope': 'global',
                            'lookup': Route(target, waveform_sequence=waveform_sequence)
                        }
                        self.waveform_sequence = waveform_sequence
                        self.has_waveform_sequence = True
                        self.midi_mappings[trigger].append(action)
                        return
                    else:
                        value = SynthioInterfaces.create_waveform(value_part)
                        action = {
                            'handler': handler,
                            'target': target,
                            'scope': 'global',
                            'value': value
                        }
            elif parts[0] == 'filter':
                target = f'filter_{parts[2]}'
                handler = 'update_parameter'
                self.filter_type = parts[1]
            elif parts[0] == 'amplifier':
                if parts[1] == 'envelope':
                    target = parts[2]
                    handler = 'update_global_envelope'
                elif parts[1] == 'amplitude':
                    target = 'amplifier_amplitude'
                    handler = 'update_parameter'
            elif parts[0] == 'math':
                target = f'math_{parts[1]}'
                handler = 'update_math_parameter'
                self.has_math_ops = True
            elif parts[0] == 'lfo':
                if parts[1] == 'target':
                    target = f'lfo_target_{parts[2]}'
                    handler = 'update_lfo_target'
                elif parts[1] == 'waveform':
                    target = 'lfo_waveform'
                    handler = 'update_lfo_waveform'
                else:
                    target = f'lfo_{parts[1]}'
                    handler = 'update_lfo_parameter'
                self.has_lfo = True
                
            action = {
                'handler': handler,
                'target': target,
                'scope': 'global'
            }
            
            # If global scope and target is a per-note parameter, store in all channels
            if target in PER_NOTE_PARAMS:
                action['store_in_channels'] = True
                log(TAG_ROUTE, f"Global per-note parameter {target} will be stored in all channels")
            
            # Determine value source
            if value_part in ('velocity', 'pressure'):
                action['source'] = value_part
            elif '-' in value_part:
                min_val, max_val = self._parse_range(value_part)
                action['lookup'] = Route(target, min_val, max_val, is_integer=target in INTEGER_PARAMS)
            else:
                action['value'] = value_part
                
        self.midi_mappings[trigger].append(action)
        
        # Set feature flags based on path
        if parts[0] == 'filter' or (parts[0] == 'note' and parts[1] == 'filter'):
            self.has_filter = True
        elif (parts[0] == 'amplifier' and parts[1] == 'envelope') or \
             (parts[0] == 'note' and parts[1] == 'amplifier' and parts[2] == 'envelope'):
            self.has_envelope_paths = True
        elif (parts[0] == 'oscillator' and parts[1] == 'ring') or \
             (parts[0] == 'note' and parts[1] == 'oscillator' and parts[2] == 'ring'):
            self.has_ring_mod = True
    
    def _parse_line(self, parts):
        """Parse a single path line."""
        if len(parts) < 3:
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
        # Parse routing info
        self._parse_routing(parts)
