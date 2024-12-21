"""Parameter and path management module."""

import array
import math
import synthio
from logging import log, TAG_ROUTE, format_value
from synth_wave import WaveManager
from constants import STATIC_WAVEFORM_SAMPLES

# Complete type specification for parameters
PARAM_TYPES = {
    # Fixed Float (can't be block)
    'frequency': 'float',
    'ring_frequency': 'float',  # Must be float per synthio docs
    'attack_time': 'float',
    'decay_time': 'float',
    'sustain_level': 'float',
    'release_time': 'float',
    
    # BlockInput (must be block)
    'amplitude': 'block',
    'bend': 'block',
    'panning': 'block',
    'waveform_loop_start': 'block',
    'waveform_loop_end': 'block',
    'ring_bend': 'block',
    'ring_waveform_loop_start': 'block',
    'ring_waveform_loop_end': 'block',
    'filter_frequency': 'block',
    'filter_q': 'block',
    
    # LFO parameters
    'lfo_rate': 'block',      # Base type for all LFO rates
    'lfo_scale': 'block',     # Base type for all LFO scales
    'lfo_offset': 'block',    # Base type for all LFO offsets
    'lfo_phase_offset': 'block',  # Base type for all LFO phase offsets
    
    # Special Objects (handled separately)
    'filter': 'filter',
    'waveform': 'waveform',
    'ring_waveform': 'waveform',
    'envelope': 'envelope',
    
    # Integer parameters
    'note_number': 'int',
    'morph_position': 'int',
    'ring_morph_position': 'int'
}

# Parameters that synthio handles per-note
PER_NOTE_PARAMS = {
    'bend', 'amplitude', 'panning', 'waveform',
    'waveform_loop_start', 'waveform_loop_end',
    'filter', 'ring_frequency', 'ring_bend',
    'ring_waveform', 'ring_waveform_loop_start',
    'ring_waveform_loop_end'
}

def format_instrument_name(name):
    """Format instrument name by converting underscores to spaces and capitalizing words.
    CircuitPython compatible version."""
    # Split by underscore and convert to uppercase for first letter only
    words = name.split('_')
    formatted_words = []
    for word in words:
        if word:  # Check if word is not empty
            # Manual capitalization: first letter upper, rest lower
            formatted_word = word[0].upper() + word[1:].lower()
            formatted_words.append(formatted_word)
    return ' '.join(formatted_words)

# Configuration dictionary defining string format structure
config_format = {
    'structure': {
        'order': ['cartridge_name', 'instrument_name', 'type', 'pot_mappings'],
        'separators': {
            'main': '|',
            'pot': '=',
            'controls': ':',
            'multi_control': ','
        }
    },
    'pot_mapping': {
        'format': '{pot_number}={cc_number}:{controls}',
        'controls_join': ','
    }
}

# Map internal handler names to human-readable control labels
control_label_map = {
    # Envelope Controls
    'envelope_attack_time': 'Attack Time',
    'envelope_attack_level': 'Attack Level',
    'envelope_decay_time': 'Decay Time',
    'envelope_sustain_level': 'Sustain Level',
    'envelope_release_time': 'Release Time',
    
    # Filter Controls
    'synth_filter_low_pass_frequency': 'Low Pass Cutoff',
    'synth_filter_low_pass_resonance': 'Low Pass Resonance',
    'synth_filter_high_pass_frequency': 'High Pass Cutoff',
    'synth_filter_high_pass_resonance': 'High Pass Resonance',
    'synth_filter_band_pass_frequency': 'Band Pass Cutoff',
    'synth_filter_band_pass_resonance': 'Band Pass Resonance',
    'synth_filter_notch_frequency': 'Notch Cutoff',
    'synth_filter_notch_resonance': 'Notch Resonance',
    
    # Oscillator Controls
    'ring_frequency': 'Ring Frequency',
    'ring_bend': 'Ring Bend',
    'ring_waveform': 'Ring Waveform',
    'ring_waveform_loop_start': 'Ring Loop Start',
    'ring_waveform_loop_end': 'Ring Loop End',
    'oscillator_frequency': 'Frequency',
    
    # Waveform Controls
    'waveform': 'Waveform',
    'waveform_loop_start': 'Wave Loop Start',
    'waveform_loop_end': 'Wave Loop End',
    
    # Basic Controls
    'amplitude': 'Key Amplitude',
    'frequency': 'Frequency',
    'bend': 'Pitch Bend',
    'panning': 'Pan',
    
    # Additional Controls from synthesizer.py
    'release_velocity': 'Release Velocity',
    'velocity': 'Note Velocity',
    'pressure': 'Key Pressure',
    'morph_position': 'Wave Morph',
    'ring_morph_position': 'Ring Morph',
    
    # LFO Controls
    'lfo_rate': 'LFO Rate',
    'lfo_scale': 'LFO Scale',
    'lfo_offset': 'LFO Offset',
    'lfo_phase_offset': 'LFO Phase',
    'lfo_once': 'LFO Once',
    'lfo_interpolate': 'LFO Interpolate'
}

class Route:
    def __init__(self, name, min_val=None, max_val=None, fixed_value=None, 
                 param_type=None, is_note_to_freq=False, 
                 waveform_sequence=None, is_14_bit=False, wave_manager=None):
        # Initialize basic attributes first
        self.wave_manager = wave_manager
        self.name = name
        self.param_type = PARAM_TYPES.get(name, 'float')  # Default to float
        self.is_note_to_freq = is_note_to_freq
        self.is_waveform_sequence = waveform_sequence is not None
        self.is_14_bit = is_14_bit
        self.waveform_sequence = waveform_sequence
        self.waveform_morph = None
        self.lookup_table = None
        self.fixed_value = None
        self.min_val = None
        self.max_val = None
        
        # Log waveform sequence if present
        if self.is_waveform_sequence and self.wave_manager:
            log(TAG_ROUTE, f"Using waveform sequence: {'-'.join(waveform_sequence)}")
        
        try:
            # Handle fixed value or range
            if fixed_value is not None:
                # Handle LFO routing first
                if isinstance(fixed_value, str) and fixed_value.startswith('lfo:'):
                    # Store LFO name for routing
                    self.fixed_value = fixed_value
                else:
                    # Handle as fixed value
                    try:
                        if self.param_type == 'int':
                            self.fixed_value = int(fixed_value)
                        elif self.param_type == 'float':
                            self.fixed_value = float(fixed_value)
                        elif self.param_type == 'block':
                            # Create Math block for fixed value
                            self.fixed_value = synthio.Math(
                                operation=synthio.MathOperation.SUM,
                                a=float(fixed_value),
                                b=0.0,
                                c=0.0
                            )
                        else:
                            self.fixed_value = fixed_value
                    except (TypeError, ValueError):
                        # If conversion fails, try parsing as range
                        if isinstance(fixed_value, str) and '-' in fixed_value:
                            min_val, max_val = self._parse_range(fixed_value)
                            self.min_val = float(min_val)
                            self.max_val = float(max_val)
                            table_size = 128  # Standard MIDI resolution
                            self.lookup_table = array.array('f', [0] * table_size)
                            self._build_lookup()
                        else:
                            raise
            
            # Handle note-to-freq or explicit min/max values
            elif is_note_to_freq or (min_val is not None and max_val is not None):
                table_size = 16384 if self.is_14_bit else 128
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
            
            # Log creation
            if self.fixed_value is not None:
                log(TAG_ROUTE, f"Created route: {name} [fixed: {format_value(self.fixed_value)}]")
            elif self.lookup_table is None:
                log(TAG_ROUTE, f"Created route: {name} [pass through]")
                
        except (TypeError, ValueError) as e:
            self._log_conversion_error(fixed_value, self.param_type, e)
            raise
    
    def _parse_range(self, range_str):
        """Parse a range string into min and max values.
        
        Args:
            range_str: String in format "min-max" or "nmin-max" for negative min
            
        Returns:
            Tuple of (min_val, max_val) as floats
        """
        try:
            if '-' not in range_str:
                raise ValueError(f"Invalid range format: {range_str}")
                
            min_str, max_str = range_str.split('-')
            
            if min_str.startswith('n'):
                min_val = -float(min_str[1:])
            else:
                min_val = float(min_str)
                
            max_val = float(max_str)
            
            # Log the parsed range
            log(TAG_ROUTE, f"Parsed range {range_str} -> {min_val} to {max_val}")
            
            return min_val, max_val
            
        except ValueError as e:
            raise ValueError(f"Invalid range format {range_str}: {str(e)}")
    
    def _build_note_to_freq_lookup(self):
        for i in range(128):
            self.lookup_table[i] = self.wave_manager.midi_to_hz(i)
            
        log(TAG_ROUTE, "Note to Hz lookup table for {} (sample values):".format(self.name))
        log(TAG_ROUTE, "  0: {:.2f} Hz".format(self.lookup_table[0]))
        log(TAG_ROUTE, " 60 (middle C): {:.2f} Hz".format(self.lookup_table[60]))
        log(TAG_ROUTE, " 69 (A440): {:.2f} Hz".format(self.lookup_table[69]))
        log(TAG_ROUTE, "127: {:.2f} Hz".format(self.lookup_table[127]))
        
    def _build_lookup(self):
        table_size = len(self.lookup_table)
        
        # Simple linear mapping for all cases
        for i in range(table_size):
            normalized = i / (table_size - 1)  # 0 to 1
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
                morph_position = midi_value / 127.0
                return self.wave_manager.create_morphed_waveform(self.waveform_sequence, morph_position)
            return midi_value
            
        value = self.lookup_table[midi_value]
        
        # Type conversion based on parameter type
        try:
            if self.fixed_value is not None:
                return self.fixed_value  # Return any fixed value (including booleans) directly
            elif self.param_type == 'block':
                # Create Math block to hold value
                return synthio.Math(
                    operation=synthio.MathOperation.SUM,
                    a=float(value),
                    b=0.0,
                    c=0.0
                )
            elif self.param_type == 'int':
                return int(value)
            elif self.param_type == 'float':
                return float(value)
            else:
                return value  # For special types (waveform, filter, envelope)
        except (TypeError, ValueError) as e:
            self._log_conversion_error(value, self.param_type, e)
            raise

# Global router service
_parser = None

def get_router():
    """Get the global router service instance."""
    global _parser
    if _parser is None:
        _parser = PathParser()
    return _parser

class PathParser:
    """Path parsing service that provides parsed info to components."""
    def __init__(self):
        self.wave_manager = WaveManager()
        self.midi_mappings = {}
        self.startup_values = {}
        self.enabled_messages = set()
        self.enabled_ccs = []  # Changed to list to maintain order
        self.current_instrument_name = None
        self.on_paths_parsed = None  # Callback for when paths are parsed
        
        # LFO tracking
        self.lfo_params = {}  # lfo_name -> {param: value}
        self.lfo_routes = {}  # param -> lfo_name
        
    def parse_paths(self, paths, config_name=None):
        log(TAG_ROUTE, "Parsing instrument paths...")
        log(TAG_ROUTE, "----------------------------------------")
        
        if config_name:
            log(TAG_ROUTE, f"Using paths configuration: {config_name}")
            # Extract instrument name from config name (remove _PATHS suffix)
            if config_name.endswith('_PATHS'):
                self.current_instrument_name = config_name[:-6].lower()
        
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
            
            # Notify listeners that paths have been parsed
            if self.on_paths_parsed:
                self.on_paths_parsed()
            
        except Exception as e:
            log(TAG_ROUTE, f"Failed to parse paths: {str(e)}", is_error=True)
            raise
    
    def _reset(self):
        self.midi_mappings.clear()
        self.startup_values.clear()
        self.enabled_messages.clear()
        self.enabled_ccs = []  # Reset to empty list
        self.lfo_params.clear()
        self.lfo_routes.clear()

    def _parse_range(self, range_str):
        """Parse a range string into min and max values.
        
        Args:
            range_str: String in format "min-max" or "nmin-max" for negative min
            
        Returns:
            Tuple of (min_val, max_val) as floats
        """
        try:
            if '-' not in range_str:
                raise ValueError(f"Invalid range format: {range_str}")
                
            min_str, max_str = range_str.split('-')
            
            if min_str.startswith('n'):
                min_val = -float(min_str[1:])
            else:
                min_val = float(min_str)
                
            max_val = float(max_str)
            
            # Log the parsed range
            log(TAG_ROUTE, f"Parsed range {range_str} -> {min_val} to {max_val}")
            
            return min_val, max_val
            
        except ValueError as e:
            raise ValueError(f"Invalid range format {range_str}: {str(e)}")
            
    def _parse_line(self, parts):
        if len(parts) < 3:
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
        scope = parts[0]
        handler = parts[1]
        value_or_range = parts[2]

        # Note handling
        if handler in ('press_note', 'release_note'):
            if scope != 'channel':
                raise ValueError(f"Invalid scope for note handling: {scope}")
            if value_or_range not in ('note_on', 'note_off'):
                raise ValueError(f"Invalid trigger for note handling: {value_or_range}")
                
            midi_value = value_or_range
            if midi_value not in self.midi_mappings:
                self.midi_mappings[midi_value] = []
            
            action = {
                'handler': handler,
                'scope': 'channel',
                'use_channel': True
            }
            self.midi_mappings[midi_value].append(action)
            self.enabled_messages.add(midi_value)
            return

        # Map paths to store parameters
        if ':' in handler:
            if handler.startswith('envelope:'):
                # Format: scope/envelope:param/value/trigger
                _, param = handler.split(':')
                # Store as envelope parameter
                handler = f"envelope_{param}"
                
            elif handler.startswith('filter_frequency:'):
                # Format: scope/filter_frequency:type/value/trigger
                _, filter_type = handler.split(':')
                # Store filter type and frequency
                self.startup_values['filter_type'] = {
                    'value': filter_type,
                    'use_channel': scope == 'channel'
                }
                handler = 'filter_frequency'
                
            elif handler.startswith('filter_resonance:'):
                # Format: scope/filter_resonance:type/value/trigger
                _, filter_type = handler.split(':')
                # Store filter type and Q
                self.startup_values['filter_type'] = {
                    'value': filter_type,
                    'use_channel': scope == 'channel'
                }
                handler = 'filter_q'

        # LFO parameter definition
        if handler == 'lfo':
            # Format: scope/lfo/param/name:value/[trigger]
            if len(parts) < 4:
                raise ValueError("Invalid LFO parameter path")
            param = value_or_range
            name_value = parts[3]
            if ':' not in name_value:
                raise ValueError("Invalid LFO name:value format")
            name_parts = name_value.split(':')
            if len(name_parts) != 2:
                raise ValueError("Invalid LFO name:value format")
                
            lfo_name = name_parts[0]  # Get LFO name first
            value = name_parts[1]
            handler = f"lfo_{param}_{lfo_name}"
            value_or_range = value
            
            # Add handler to PARAM_TYPES if not already there
            if handler not in PARAM_TYPES:
                base_type = f"lfo_{param}"  # e.g. lfo_rate, lfo_scale
                PARAM_TYPES[handler] = PARAM_TYPES.get(base_type, 'block')
                
            log(TAG_ROUTE, f"Processing LFO parameter: {lfo_name}.{param} = {value}")
            
            # If MIDI trigger present, enable it and create route
            if len(parts) > 4:
                midi_value = parts[4]
                # Handle all MIDI triggers for LFO parameters
                if midi_value.startswith('cc'):
                    cc_num = int(midi_value[2:])
                    self.enabled_messages.add('cc')
                    if cc_num not in self.enabled_ccs:
                        self.enabled_ccs.append(cc_num)
                    midi_value = f"cc{cc_num}"
                elif midi_value == 'pitch_bend':
                    self.enabled_messages.add('pitch_bend')
                elif midi_value == 'pressure':
                    self.enabled_messages.add('channel_pressure')
                    midi_value = 'channel_pressure'
                elif midi_value == 'velocity':
                    self.enabled_messages.add('note_on')
                    midi_value = 'velocity'
                
                # Create route for MIDI control
                if '-' in value:
                    min_val, max_val = self._parse_range(value)
                    is_14_bit = midi_value == 'pitch_bend'
                    route = Route(handler, min_val=min_val, max_val=max_val, 
                                is_14_bit=is_14_bit, wave_manager=self.wave_manager)
                    
                    # Add MIDI mapping
                    if midi_value not in self.midi_mappings:
                        self.midi_mappings[midi_value] = []
                    self.midi_mappings[midi_value].append({
                        'handler': handler,
                        'scope': scope,
                        'route': route,
                        'use_channel': scope == 'channel'
                    })
            
            # Store LFO parameter
            if len(parts) == 4:
                # Track LFO parameters
                if lfo_name not in self.lfo_params:
                    self.lfo_params[lfo_name] = {}
                
                # Check if value is a range
                if '-' in value:
                    min_val, max_val = self._parse_range(value)
                    route = Route(handler, min_val=min_val, max_val=max_val, wave_manager=self.wave_manager)
                    value = route.convert(0)  # Convert to BlockInput
                else:
                    # Try to convert value to float if possible
                    try:
                        value = float(value)
                    except ValueError:
                        pass  # Keep as string if not a valid float
                
                # Store parameter value
                # Create route to handle type conversion
                route = Route(handler, fixed_value=value, wave_manager=self.wave_manager)
                block = route.convert(0)  # Convert to proper type (Math block for numeric)
                self.lfo_params[lfo_name][param] = block
                self.startup_values[handler] = {
                    'value': block,
                    'use_channel': scope == 'channel'
                }
                return

        # Handle filter type in handler
        if ':' in handler and (handler.startswith('filter_frequency:') or handler.startswith('filter_resonance:')):
            # Format: scope/filter_param:type/value/trigger
            param, filter_type = handler.split(':')
            handler = f"{param}_{filter_type}"
            
            # Add handler to PARAM_TYPES if not already there
            if handler not in PARAM_TYPES:
                PARAM_TYPES[handler] = PARAM_TYPES.get(param, 'float')

        # LFO routing
        if value_or_range.startswith('lfo:'):
            # Format: scope/target/lfo:name
            lfo_name = value_or_range.split(':')[1].strip()
            
            # Track LFO routing
            self.lfo_routes[handler] = lfo_name
            
            # Create route to handle LFO routing
            route = Route(handler, fixed_value=value_or_range, wave_manager=self.wave_manager)
            self.startup_values[handler] = {
                'value': route.fixed_value,  # Store LFO routing string
                'use_channel': scope == 'channel'
            }
            return

        # Envelope parameters
        elif ':' in handler and handler.startswith('envelope:'):
            # Format: scope/envelope:param/value/trigger
            _, param = handler.split(':')
            handler = f"envelope_{param}"
        
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
            elif midi_value == 'velocity':
                self.enabled_messages.add('note_on')
                midi_value = 'velocity'
            elif midi_value == 'note_on':
                self.enabled_messages.add('note_on')
                
            # Check for waveform morphing before attempting to parse as range
            if handler.endswith('waveform') and '-' in value_or_range:
                waveform_sequence = value_or_range.split('-')
                route = Route(handler, waveform_sequence=waveform_sequence, wave_manager=self.wave_manager)
                log(TAG_ROUTE, f"Created waveform morph route: {handler} [{value_or_range}]")
            elif '-' in value_or_range:
                min_val, max_val = self._parse_range(value_or_range)
                is_14_bit = midi_value == 'pitch_bend'
                route = Route(handler, min_val=min_val, max_val=max_val, 
                            param_type=PARAM_TYPES.get(handler),
                            is_14_bit=is_14_bit, wave_manager=self.wave_manager)
            elif value_or_range == 'note_number':
                route = Route(handler, is_note_to_freq=True, wave_manager=self.wave_manager)
            else:
                route = Route(handler, fixed_value=value_or_range, wave_manager=self.wave_manager)
                    
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
                    value = self.wave_manager.create_waveform(value_or_range, STATIC_WAVEFORM_SAMPLES)
                    self.startup_values[handler] = {
                        'value': value,
                        'use_channel': scope == 'channel'
                    }
                except Exception as e:
                    log(TAG_ROUTE, f"Failed to create waveform: {str(e)}", is_error=True)
                    raise
            else:
                # Create a Route to handle type conversion for startup values
                route = Route(handler, fixed_value=value_or_range, wave_manager=self.wave_manager)
                self.startup_values[handler] = {
                    'value': route.convert(0),  # Convert using Route to ensure proper typing
                    'use_channel': scope == 'channel'
                }

    def get_startup_values(self):
        """Get startup values and LFO params.
        
        Returns:
            Tuple of (startup_values, lfo_params)
        """
        return (self.startup_values.copy(), self.lfo_params.copy())

    def get_midi_mappings(self):
        return self.midi_mappings.copy()

    def get_cc_configs(self):
        """Generate CC configuration string using format configuration."""
        pot_mappings = []
        for pot_num, cc_num in enumerate(self.enabled_ccs):
            midi_value = f"cc{cc_num}"
            actions = self.midi_mappings.get(midi_value, [])
            
            if actions:
                handler = actions[0]['handler']
                if handler.startswith('set_'):
                    handler = handler[4:]
                
                # Get human-readable control label or use handler name as fallback
                control_label = control_label_map.get(handler, handler)
                
                # Format pot mapping using configuration
                pot_str = config_format['pot_mapping']['format'].format(
                    pot_number=pot_num,
                    cc_number=cc_num,
                    controls=control_label
                )
                pot_mappings.append(pot_str)
        
        # Build final string using structure configuration
        parts = []
        for element in config_format['structure']['order']:
            if element == 'cartridge_name':
                parts.append('Candide')
            elif element == 'instrument_name':
                # Format the instrument name if available
                if self.current_instrument_name:
                    parts.append(format_instrument_name(self.current_instrument_name))
                else:
                    parts.append('')  # Empty string if no instrument name
            elif element == 'type':
                parts.append('cc')
            elif element == 'pot_mappings':
                parts.extend(pot_mappings)
        
        return config_format['structure']['separators']['main'].join(parts)
