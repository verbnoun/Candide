"""Parameter and path management module."""

import array
import math
from logging import log, TAG_ROUTE, format_value
from interfaces import SynthioInterfaces, WaveformMorph
from constants import STATIC_WAVEFORM_SAMPLES

# Complete type specification for parameters
PARAM_TYPES = {
    # Integer parameters
    'note_number': 'int',
    'morph_position': 'int', 
    'ring_morph_position': 'int',
    
    # Float parameters requiring conversion
    'frequency': 'float',
    'amplitude': 'float',
    'attack_time': 'float',
    'decay_time': 'float',
    'sustain_level': 'float',
    'release_time': 'float',
    'bend': 'float',
    'ring_frequency': 'float',
    'ring_bend': 'float',
    'filter_frequency': 'float',
    'filter_resonance': 'float'
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
    def __init__(self, name, min_val=None, max_val=None, fixed_value=None, 
                 param_type=None, is_note_to_freq=False, 
                 waveform_sequence=None, is_14_bit=False):
        self.name = name
        self.param_type = PARAM_TYPES.get(name, 'float')  # Default to float
        
        # Format fixed_value according to param_type during initialization
        if fixed_value is not None:
            try:
                if self.param_type == 'int':
                    self.fixed_value = int(fixed_value)
                elif self.param_type == 'float':
                    self.fixed_value = float(fixed_value)
                else:
                    self.fixed_value = fixed_value
            except (TypeError, ValueError) as e:
                self._log_conversion_error(fixed_value, self.param_type, e)
                raise
        else:
            self.fixed_value = None
            
        self.is_note_to_freq = is_note_to_freq
        self.is_waveform_sequence = waveform_sequence is not None
        self.is_14_bit = is_14_bit
        self.waveform_sequence = waveform_sequence
        self.waveform_morph = None
        
        if self.is_waveform_sequence:
            self.waveform_morph = WaveformMorph(name, waveform_sequence)
            log(TAG_ROUTE, f"Created morph table for {'-'.join(waveform_sequence)}")
        
        if is_note_to_freq or (min_val is not None and max_val is not None):
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
                    name, min_val, max_val, f"({self.param_type})"))
        else:
            self.lookup_table = None
            if fixed_value is not None:
                log(TAG_ROUTE, f"Created route: {name} [fixed: {format_value(fixed_value)}]")
            else:
                log(TAG_ROUTE, f"Created route: {name} [pass through]")
    
    def _build_note_to_freq_lookup(self):
        for i in range(128):
            self.lookup_table[i] = SynthioInterfaces.midi_to_hz(i)
            
        log(TAG_ROUTE, "Note to Hz lookup table for {} (sample values):".format(self.name))
        log(TAG_ROUTE, "  0: {:.2f} Hz".format(self.lookup_table[0]))
        log(TAG_ROUTE, " 60 (middle C): {:.2f} Hz".format(self.lookup_table[60]))
        log(TAG_ROUTE, " 69 (A440): {:.2f} Hz".format(self.lookup_table[69]))
        log(TAG_ROUTE, "127: {:.2f} Hz".format(self.lookup_table[127]))
        
    def _build_lookup(self):
        table_size = len(self.lookup_table)
        
        if self.is_14_bit:
            center = table_size // 2
            for i in range(table_size):
                normalized = (i - center) / center
                value = self.min_val + normalized * (self.max_val - self.min_val)
                self.lookup_table[i] = value
        else:
            for i in range(table_size):
                normalized = i / (table_size - 1)
                value = self.min_val + normalized * (self.max_val - self.min_val)
                self.lookup_table[i] = value
            
        log(TAG_ROUTE, "Lookup table for {} (sample values):".format(self.name))
        log(TAG_ROUTE, "  0: {}".format(format_value(self.lookup_table[0])))
        if self.is_14_bit:
            log(TAG_ROUTE, "  8192 (center): {}".format(format_value(self.lookup_table[8192])))
            log(TAG_ROUTE, "  16383: {}".format(format_value(self.lookup_table[16383])))
        else:
            log(TAG_ROUTE, "  64: {}".format(format_value(self.lookup_table[64])))
            log(TAG_ROUTE, "  127: {}".format(format_value(self.lookup_table[127])))
    
    def _log_conversion_error(self, value, target_type, error):
        log(TAG_ROUTE, f"Type conversion failed for {self.name}:")
        log(TAG_ROUTE, f"  Value: {value}")
        log(TAG_ROUTE, f"  Target type: {target_type}") 
        log(TAG_ROUTE, f"  Error: {str(error)}")
    
    def convert(self, midi_value):
        max_val = 16383 if self.is_14_bit else 127
        if not 0 <= midi_value <= max_val:
            log(TAG_ROUTE, "Invalid MIDI value {} for {}".format(midi_value, self.name), is_error=True)
            raise ValueError(f"MIDI value must be between 0 and {max_val}")
            
        if self.fixed_value is not None:
            return self.fixed_value
            
        if self.lookup_table is None:
            if self.is_waveform_sequence:
                return self.waveform_morph.get_waveform(midi_value)
            return midi_value
            
        value = self.lookup_table[midi_value]
        
        # Type conversion based on parameter type
        try:
            if self.param_type == 'int':
                return int(value)
            elif self.param_type == 'float':
                return float(value)
            else:
                return value  # For waveforms or other special types
        except (TypeError, ValueError) as e:
            self._log_conversion_error(value, self.param_type, e)
            raise

class PathParser:
    def __init__(self):
        self.midi_mappings = {}
        self.startup_values = {}
        self.enabled_messages = set()
        self.enabled_ccs = []  # Changed to list to maintain order
        
    def parse_paths(self, paths, config_name=None):
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
                    
            log(TAG_ROUTE, "Complete routing table:")
            log(TAG_ROUTE, "MIDI Mappings:")
            for midi_value, actions in self.midi_mappings.items():
                log(TAG_ROUTE, f"{midi_value} -> [")
                for action in actions:
                    log(TAG_ROUTE, f"  {format_value(action)}")
                log(TAG_ROUTE, "]")
                
            log(TAG_ROUTE, "Startup Values:")
            for handler, value in self.startup_values.items():
                if handler.endswith('waveform'):
                    log(TAG_ROUTE, f"{handler} -> Waveform configured")
                else:
                    log(TAG_ROUTE, f"{handler} -> {format_value(value)}")
                
            log(TAG_ROUTE, f"Enabled messages: {self.enabled_messages}")
            if 'cc' in self.enabled_messages:
                log(TAG_ROUTE, f"Enabled CCs: {self.enabled_ccs}")
                
            log(TAG_ROUTE, "----------------------------------------")
            
        except Exception as e:
            log(TAG_ROUTE, f"Failed to parse paths: {str(e)}", is_error=True)
            raise
    
    def _reset(self):
        self.midi_mappings.clear()
        self.startup_values.clear()
        self.enabled_messages.clear()
        self.enabled_ccs = []  # Reset to empty list

    def _parse_range(self, range_str):
        try:
            if '-' not in range_str:
                raise ValueError(f"Invalid range format: {range_str}")
                
            min_str, max_str = range_str.split('-')
            
            if min_str.startswith('n'):
                min_val = -float(min_str[1:])
            else:
                min_val = float(min_str)
                
            max_val = float(max_str)
            return min_val, max_val
            
        except ValueError as e:
            raise ValueError(f"Invalid range format {range_str}: {str(e)}")
            
    def _parse_line(self, parts):
        if len(parts) < 3:
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
        if parts[1] in ('press_voice', 'release_voice'):
            if parts[0] != 'channel':
                raise ValueError(f"Invalid scope for voice handling: {parts[0]}")
            if parts[2] not in ('note_on', 'note_off'):
                raise ValueError(f"Invalid trigger for voice handling: {parts[2]}")
                
            midi_value = parts[2]
            if midi_value not in self.midi_mappings:
                self.midi_mappings[midi_value] = []
            
            action = {
                'handler': parts[1],
                'scope': 'channel',
                'use_channel': True
            }
            self.midi_mappings[midi_value].append(action)
            self.enabled_messages.add(midi_value)
            return
            
        scope = parts[0]
        handler = parts[1]
        value_or_range = parts[2]
        
        if len(parts) == 4:
            midi_value = parts[3]
            
            if midi_value.startswith('cc'):
                cc_num = int(midi_value[2:])
                self.enabled_messages.add('cc')
                if cc_num not in self.enabled_ccs:  # Only add if not already present
                    self.enabled_ccs.append(cc_num)  # Add to list to maintain order
                midi_value = f"cc{cc_num}"
            elif midi_value == 'pitch_bend':
                self.enabled_messages.add('pitch_bend')
            elif midi_value == 'pressure':
                self.enabled_messages.add('channel_pressure')
                midi_value = 'channel_pressure'
            elif midi_value == 'note_on':
                self.enabled_messages.add('note_on')
                
            # Check for waveform morphing before attempting to parse as range
            if handler.endswith('waveform') and '-' in value_or_range:
                waveform_sequence = value_or_range.split('-')
                route = Route(handler, waveform_sequence=waveform_sequence)
                log(TAG_ROUTE, f"Created waveform morph route: {handler} [{value_or_range}]")
            elif '-' in value_or_range:
                min_val, max_val = self._parse_range(value_or_range)
                is_14_bit = midi_value == 'pitch_bend'
                route = Route(handler, min_val=min_val, max_val=max_val, 
                            param_type=PARAM_TYPES.get(handler),
                            is_14_bit=is_14_bit)
            elif value_or_range == 'note_number':
                route = Route(handler, is_note_to_freq=True)
            else:
                route = Route(handler, fixed_value=value_or_range)
                    
            if midi_value not in self.midi_mappings:
                self.midi_mappings[midi_value] = []
                
            action = {
                'handler': handler,
                'scope': scope,
                'route': route,
                'use_channel': scope == 'channel'
            }
            self.midi_mappings[midi_value].append(action)
            
        else:
            if handler.endswith('waveform'):
                try:
                    value = SynthioInterfaces.create_waveform(value_or_range, STATIC_WAVEFORM_SAMPLES)
                    self.startup_values[handler] = {
                        'value': value,
                        'use_channel': scope == 'channel'
                    }
                except Exception as e:
                    log(TAG_ROUTE, f"Failed to create waveform: {str(e)}", is_error=True)
                    raise
            else:
                # Create a Route to handle type conversion for startup values
                route = Route(handler, fixed_value=value_or_range)
                self.startup_values[handler] = {
                    'value': route.convert(0),  # Convert using Route to ensure proper typing
                    'use_channel': scope == 'channel'
                }

    def get_startup_values(self):
        return self.startup_values.copy()

    def get_midi_mappings(self):
        return self.midi_mappings.copy()

    def get_cc_configs(self):
        cc_configs = []
        
        # Use the ordered list of CCs
        for cc_num in self.enabled_ccs:
            midi_value = f"cc{cc_num}"
            actions = self.midi_mappings.get(midi_value, [])
            
            if actions:
                handler = actions[0]['handler']
                if handler.startswith('set_'):
                    handler = handler[4:]
                cc_configs.append((cc_num, handler))
                log(TAG_ROUTE, f"Found CC mapping: cc{cc_num} -> {handler}")
                
        return cc_configs
