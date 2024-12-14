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

class PathParser:
    """Parses instrument paths and manages parameter conversions."""
    def __init__(self):
        # Core collections for parameter management
        self.midi_mappings = {}  # midi_value -> [action objects]
        self.startup_values = {}  # handler -> value
        self.enabled_messages = set()
        self.enabled_ccs = set()
        
        # Feature flags - only set when corresponding paths are found
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_sequence = False
        self.has_ring_waveform_sequence = False
        
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
            log(TAG_ROUTE, "MIDI Mappings:")
            for midi_value, actions in self.midi_mappings.items():
                log(TAG_ROUTE, f"{midi_value} -> [")
                for action in actions:
                    log(TAG_ROUTE, f"  {action}")
                log(TAG_ROUTE, "]")
                
            log(TAG_ROUTE, "Startup Values:")
            for handler, value in self.startup_values.items():
                log(TAG_ROUTE, f"{handler} -> {value}")
                
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
        self.startup_values.clear()
        self.enabled_messages.clear()
        self.enabled_ccs.clear()
        
        # Reset feature flags
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_sequence = False
        self.has_ring_waveform_sequence = False
        
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
            
    def _parse_line(self, parts):
        """Parse a single path line."""
        if len(parts) < 3:
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
        # Special case: Note handling paths
        if parts[1] in ('press_voice', 'release_voice'):
            if parts[0] != 'channel':
                raise ValueError(f"Invalid scope for voice handling: {parts[0]}")
            if parts[2] not in ('note_on', 'note_off'):
                raise ValueError(f"Invalid trigger for voice handling: {parts[2]}")
                
            # Add to MIDI mappings
            midi_value = parts[2]  # note_on or note_off
            if midi_value not in self.midi_mappings:
                self.midi_mappings[midi_value] = []
            
            action = {
                'handler': parts[1],  # press_voice or release_voice
                'scope': 'channel'
            }
            self.midi_mappings[midi_value].append(action)
            self.enabled_messages.add(midi_value.replace('_', ''))
            return
            
        # Regular path handling
        scope = parts[0]  # channel or synth
        handler = parts[1]  # set_frequency, set_waveform, etc.
        value_or_range = parts[2]  # 130.81-523.25, triangle, etc.
        
        # Check if this is a MIDI control path (has 4 parts)
        if len(parts) == 4:
            midi_value = parts[3]  # cc74, note_number, etc.
            
            # Handle CC numbers
            if midi_value.startswith('cc'):
                cc_num = int(midi_value[2:])
                self.enabled_messages.add('cc')
                self.enabled_ccs.add(cc_num)
                midi_value = f"cc{cc_num}"
            elif midi_value == 'pitch_bend':
                self.enabled_messages.add('pitchbend')
            elif midi_value == 'pressure':
                self.enabled_messages.add('channelpressure')
                midi_value = 'channelpressure'
            elif midi_value == 'note_number':
                self.enabled_messages.add('noteon')
                
            # Create route for value conversion
            if '-' in value_or_range:
                min_val, max_val = self._parse_range(value_or_range)
                is_14_bit = midi_value == 'pitch_bend'
                route = Route(handler, min_val=min_val, max_val=max_val, 
                            is_integer=handler in INTEGER_PARAMS,
                            is_14_bit=is_14_bit)
            elif value_or_range == 'note_number':
                route = Route(handler, is_note_to_freq=True)
            else:
                # Handle waveform sequences
                if '-' in value_or_range and handler.endswith('waveform'):
                    waveform_sequence = value_or_range.split('-')
                    route = Route(handler, waveform_sequence=waveform_sequence)
                    if handler == 'set_waveform':
                        self.waveform_sequence = waveform_sequence
                        self.has_waveform_sequence = True
                    elif handler == 'set_ring_waveform':
                        self.ring_waveform_sequence = waveform_sequence
                        self.has_ring_waveform_sequence = True
                else:
                    route = Route(handler, fixed_value=value_or_range)
                    
            # Add to MIDI mappings
            if midi_value not in self.midi_mappings:
                self.midi_mappings[midi_value] = []
                
            action = {
                'handler': handler,
                'scope': scope,
                'route': route
            }
            self.midi_mappings[midi_value].append(action)
            
        else:
            # Startup value path
            if handler.startswith('set_synth_filter'):
                self.has_filter = True
                filter_parts = handler.split('_')
                self.filter_type = '_'.join(filter_parts[3:-1])  # Extract filter type
                
            elif handler == 'set_envelope_param':
                self.has_envelope_paths = True
                
            elif handler.startswith('set_ring'):
                self.has_ring_mod = True
                
            # Store startup value
            self.startup_values[handler] = value_or_range
            
            # Create waveform if needed
            if handler.endswith('waveform'):
                try:
                    value = SynthioInterfaces.create_waveform(value_or_range)
                    self.startup_values[handler] = value
                except Exception as e:
                    log(TAG_ROUTE, f"Failed to create waveform: {str(e)}", is_error=True)
                    raise

    def get_startup_values(self):
        """Get all startup values."""
        return self.startup_values.copy()

    def get_midi_mappings(self):
        """Get all MIDI mappings."""
        return self.midi_mappings.copy()
