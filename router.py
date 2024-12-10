"""Parameter and path management module."""

import synthio
import sys
import array
from logging import log, TAG_ROUTE

class Route:
    """Creates a route that maps MIDI values to parameter values using a lookup table."""
    def __init__(self, name, min_val, max_val, is_integer=False):
        self.name = name
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.is_integer = is_integer
        self.lookup_table = array.array('f', [0] * 128)
        self._build_lookup()
        log(TAG_ROUTE, "Created route: {} [{} to {}] {}".format(
            name, min_val, max_val, '(integer)' if is_integer else ''))
        
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
        """Convert MIDI value (0-127) to parameter value using lookup table."""
        if not 0 <= midi_value <= 127:
            log(TAG_ROUTE, "Invalid MIDI value {} for {}".format(midi_value, self.name), is_error=True)
            raise ValueError("MIDI value must be between 0 and 127, got {}".format(midi_value))
        value = self.lookup_table[midi_value]
        return value

class PathParser:
    """Parses instrument paths and manages parameter conversions."""
    def __init__(self):
        # Core collections for parameter management
        self.global_ranges = {}  # name -> Route
        self.key_ranges = {}     # name -> Route
        self.set_values = {}     # Values that have been set
        self.midi_mappings = {}  # trigger -> (path, param_name)
        self.enabled_messages = set()
        self.enabled_ccs = set()
        
        # Feature flags - only set when corresponding paths are found
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_morph = False
        self.has_ring_waveform_morph = False
        
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
                if not line:
                    continue
                    
                try:
                    parts = line.strip().split('/')
                    self._parse_line(parts)
                except Exception as e:
                    log(TAG_ROUTE, f"Error parsing path: {line} - {str(e)}", is_error=True)
                    raise
                    
            # Validate required paths are present
            if not self.enabled_messages:
                raise ValueError("No MIDI message types enabled in paths")
                
            # Log only features and parameters that were explicitly defined
            log(TAG_ROUTE, "Path parsing complete:")
            log(TAG_ROUTE, f"Global parameters: {list(self.global_ranges.keys())}")
            log(TAG_ROUTE, f"Per-key parameters: {list(self.key_ranges.keys())}")
            log(TAG_ROUTE, f"Set values: {self.set_values}")
            log(TAG_ROUTE, f"Enabled messages: {self.enabled_messages}")
            log(TAG_ROUTE, f"Enabled CCs: {self.enabled_ccs}")
            
            if self.has_filter:
                log(TAG_ROUTE, f"Found filter type: {self.filter_type}")
                    
            if self.has_waveform_morph:
                log(TAG_ROUTE, f"Found waveform morph sequence: {'-'.join(self.waveform_sequence)}")
                
            if self.has_ring_waveform_morph:
                log(TAG_ROUTE, f"Found ring waveform morph sequence: {'-'.join(self.ring_waveform_sequence)}")
                
            log(TAG_ROUTE, "----------------------------------------")
            
        except Exception as e:
            log(TAG_ROUTE, f"Failed to parse paths: {str(e)}", is_error=True)
            raise
    
    def _reset(self):
        """Reset all collections before parsing new paths."""
        self.global_ranges.clear()
        self.key_ranges.clear()
        self.set_values.clear()
        self.midi_mappings.clear()
        self.enabled_messages.clear()
        self.enabled_ccs.clear()
        
        # Reset feature flags
        self.has_envelope_paths = False
        self.has_filter = False
        self.has_ring_mod = False
        self.has_waveform_morph = False
        self.has_ring_waveform_morph = False
        
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
        """Parse a single path line to extract parameter information."""
        if len(parts) < 3:
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
        # Store original path for parameter mapping
        original_path = '/'.join(parts)
            
        # Check for filter configuration
        if parts[0] == 'filter':
            if len(parts) >= 2 and parts[1] in ('low_pass', 'high_pass', 'band_pass', 'notch'):
                self.has_filter = True
                self.filter_type = parts[1]
                self.set_values['filter_type'] = parts[1]
                log(TAG_ROUTE, f"Found filter type: {self.filter_type}")

        # Check for envelope paths
        if parts[0] == 'amplifier' and len(parts) >= 2 and parts[1] == 'envelope':
            self.has_envelope_paths = True
            log(TAG_ROUTE, "Found envelope path")

        # Handle base oscillator waveform configuration
        if parts[0] == 'oscillator' and len(parts) >= 2:
            if parts[1] == 'waveform':
                # Check if this is a morphing waveform
                if len(parts) >= 3 and parts[2] == 'morph':
                    self.has_waveform_morph = True
                    log(TAG_ROUTE, "Found base waveform morph configuration")
                    if len(parts) >= 5 and '-' in parts[4]:
                        self.waveform_sequence = parts[4].split('-')
                        log(TAG_ROUTE, f"Found waveform sequence: {self.waveform_sequence}")
                        self.global_ranges['morph'] = Route('morph', 0, 1)
                # Fixed waveform
                elif len(parts) >= 4 and parts[2] == 'global':
                    waveform_type = parts[3]
                    if waveform_type in ('triangle', 'sine', 'square', 'saw'):
                        self.set_values['waveform'] = waveform_type
                        log(TAG_ROUTE, f"Found base waveform: {waveform_type}")

        # Handle ring modulation configuration
        if parts[0] == 'oscillator' and len(parts) >= 2 and parts[1] == 'ring':
            self.has_ring_mod = True
            if len(parts) >= 3:
                if parts[2] == 'waveform':
                    # Check if this is a morphing ring waveform
                    if len(parts) >= 4 and parts[3] == 'morph':
                        self.has_ring_waveform_morph = True
                        if len(parts) >= 6 and '-' in parts[5]:
                            self.ring_waveform_sequence = parts[5].split('-')
                            log(TAG_ROUTE, f"Found ring waveform sequence: {self.ring_waveform_sequence}")
                            self.global_ranges['ring_morph'] = Route('ring_morph', 0, 1)
                    # Fixed ring waveform
                    elif len(parts) >= 5 and parts[3] == 'global':
                        waveform_type = parts[4]
                        if waveform_type in ('triangle', 'sine', 'square', 'saw'):
                            self.set_values['ring_waveform'] = waveform_type
                            log(TAG_ROUTE, f"Found ring waveform: {waveform_type}")
                        
        # Find parameter scope and name
        scope = None
        param_name = None
        range_str = None
        trigger = None
        
        for i, part in enumerate(parts):
            if part in ('global', 'per_key'):
                scope = part
                if i > 0:
                    param_name = parts[i-1]
                if i + 1 < len(parts):
                    next_part = parts[i+1]
                    if '-' in next_part and not any(w in next_part for w in ('sine', 'triangle', 'square', 'saw')):
                        range_str = next_part
                        
                # Look for trigger type
                for p in parts[i:]:
                    if p in ('note_on', 'note_off', 'pressure', 'velocity', 'note_number'):
                        trigger = p
                        if p in ('note_on', 'note_off'):
                            self.enabled_messages.add(p.replace('_', ''))
                        elif p == 'pressure':
                            self.enabled_messages.add('pressure')
                    elif p.startswith('cc'):
                        try:
                            cc_num = int(p[2:])
                            trigger = p
                            self.enabled_messages.add('cc')
                            self.enabled_ccs.add(cc_num)
                        except ValueError:
                            raise ValueError(f"Invalid CC number in: {p}")
                    elif p == 'pitch_bend':
                        trigger = p
                        self.enabled_messages.add('pitchbend')
                
                if trigger:
                    # Store full path info with parameter
                    self.midi_mappings[trigger] = (original_path, param_name)
                else:
                    raise ValueError(f"No trigger found in path: {original_path}")
                
                break
                
        if not scope:
            raise ValueError(f"No scope (global/per_key) found in: {original_path}")
            
        if not param_name:
            raise ValueError(f"No parameter name found in: {original_path}")
            
        if range_str:
            try:
                min_val, max_val = self._parse_range(range_str)
                route = Route(param_name, min_val, max_val)
                
                if scope == 'global':
                    self.global_ranges[param_name] = route
                else:
                    self.key_ranges[param_name] = route
            except ValueError as e:
                raise ValueError(f"Invalid range format {range_str}: {str(e)}")
    
    def convert_value(self, param_name, midi_value, is_global=True):
        """Convert MIDI value using appropriate route."""
        routes = self.global_ranges if is_global else self.key_ranges
        if param_name not in routes:
            raise KeyError(f"No route defined for parameter: {param_name}")
        return routes[param_name].convert(midi_value)
