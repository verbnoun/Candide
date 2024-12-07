"""Parameter and path management module."""

import synthio
import sys
import array
from constants import (
    LOG_PATH, LOG_GREEN, LOG_RED, LOG_RESET,
    PATH_LOG
)

def _log(message, is_error=False):
    """Enhanced logging with error support."""
    if not PATH_LOG:
        return
    color = LOG_RED if is_error else LOG_GREEN
    if is_error:
        print("{}{} [ERROR] {}{}".format(color, LOG_PATH, message, LOG_RESET), file=sys.stderr)
    else:
        print("{}{} {}{}".format(color, LOG_PATH, message, LOG_RESET), file=sys.stderr)

class MidiRange:
    """Handles parameter range conversion and lookup table generation."""
    def __init__(self, name, min_val, max_val, is_integer=False):
        self.name = name
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.is_integer = is_integer
        self.lookup_table = array.array('f', [0] * 128)
        self._build_lookup()
        _log("Created MIDI range: {} [{} to {}] {}".format(
            name, min_val, max_val, '(integer)' if is_integer else ''))
        
    def _build_lookup(self):
        """Build MIDI value lookup table for fast conversion."""
        for i in range(128):
            normalized = i / 127.0
            value = self.min_val + normalized * (self.max_val - self.min_val)
            self.lookup_table[i] = int(value) if self.is_integer else value
            
        _log("Lookup table for {} (sample values):".format(self.name))
        _log("  0: {}".format(self.lookup_table[0]))
        _log(" 64: {}".format(self.lookup_table[64]))
        _log("127: {}".format(self.lookup_table[127]))
    
    def convert(self, midi_value):
        """Convert MIDI value (0-127) to parameter value using lookup table."""
        if not 0 <= midi_value <= 127:
            _log("Invalid MIDI value {} for {}".format(midi_value, self.name), is_error=True)
            raise ValueError("MIDI value must be between 0 and 127, got {}".format(midi_value))
        value = self.lookup_table[midi_value]
        return value

class PathParser:
    """Parses instrument paths and manages parameter conversions."""
    def __init__(self):
        self.global_ranges = {}  # name -> MidiRange
        self.key_ranges = {}     # name -> MidiRange
        self.fixed_values = {}   # name -> value (e.g. waveform types)
        self.midi_mappings = {}  # trigger -> (path, param_name)
        self.enabled_messages = set()
        self.enabled_ccs = set()
        self.filter_type = None  # Current filter type
        self.current_filter_params = {
            'frequency': 0,
            'resonance': 0
        }
        self.current_ring_params = {
            'frequency': 20,  # Default to minimum
            'bend': 0,       # Default to no bend
            'waveform': None # Will be set during parsing
        }
        self.current_envelope_params = {
            'attack_time': 0.1,
            'decay_time': 0.05,
            'release_time': 0.2,
            'attack_level': 1.0,
            'sustain_level': 0.8
        }
        # Keep morph state separate and clear
        self.current_morph_position = 0.0  # Base waveform morph (CC72)
        self.current_ring_morph_position = 0.0  # Ring waveform morph (CC76)
        self.waveform_sequence = None  # Base waveform sequence
        self.ring_waveform_sequence = None  # Ring waveform sequence
        
    def parse_paths(self, paths):
        """Parse instrument paths to extract parameters and mappings."""
        _log("Parsing instrument paths...")
        _log("----------------------------------------")
        
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
                    _log(f"Error parsing path: {line} - {str(e)}", is_error=True)
                    raise
                    
            # Validate required paths are present
            if not self.enabled_messages:
                raise ValueError("No MIDI messages enabled in paths")
                
            _log("Path parsing complete:")
            _log(f"Global parameters: {list(self.global_ranges.keys())}")
            _log(f"Per-key parameters: {list(self.key_ranges.keys())}")
            _log(f"Fixed values: {self.fixed_values}")
            _log(f"Enabled messages: {self.enabled_messages}")
            _log(f"Enabled CCs: {self.enabled_ccs}")
            _log(f"Filter type: {self.filter_type}")
            _log(f"Ring mod params: {self.current_ring_params}")
            _log(f"Envelope params: {self.current_envelope_params}")
            if self.waveform_sequence:
                _log(f"Waveform morph sequence: {'-'.join(self.waveform_sequence)}")
            if self.ring_waveform_sequence:
                _log(f"Ring waveform morph sequence: {'-'.join(self.ring_waveform_sequence)}")
                
            _log("----------------------------------------")
            
        except Exception as e:
            _log(f"Failed to parse paths: {str(e)}", is_error=True)
            raise
    
    def _reset(self):
        """Reset all collections before parsing new paths."""
        self.global_ranges.clear()
        self.key_ranges.clear()
        self.fixed_values.clear()
        self.midi_mappings.clear()
        self.enabled_messages.clear()
        self.enabled_ccs.clear()
        self.filter_type = None
        self.current_filter_params = {
            'frequency': 0,
            'resonance': 0
        }
        self.current_ring_params = {
            'frequency': 20,  # Default to minimum
            'bend': 0,       # Default to no bend
            'waveform': None # Will be set during parsing
        }
        self.current_envelope_params = {
            'attack_time': 0.1,
            'decay_time': 0.05,
            'release_time': 0.2,
            'attack_level': 1.0,
            'sustain_level': 0.8
        }
        self.current_morph_position = 0.0
        self.current_ring_morph_position = 0.0
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
                self.filter_type = parts[1]
                _log(f"Found filter type: {self.filter_type}")

        # Check for waveform morph configuration
        if (parts[0] == 'oscillator' and len(parts) >= 4 and 
            parts[1] == 'waveform' and parts[2] == 'morph'):
            _log("Found waveform morph configuration")
            # Extract waveform sequence from the path
            if len(parts) >= 5 and '-' in parts[4]:
                self.waveform_sequence = parts[4].split('-')
                _log(f"Found waveform sequence: {self.waveform_sequence}")
                # Create range for morph parameter (0-1)
                self.global_ranges['morph'] = MidiRange('morph', 0, 1)

        # Check for ring modulation configuration
        if parts[0] == 'oscillator' and len(parts) >= 2 and parts[1] == 'ring':
            if len(parts) >= 3:
                if parts[2] == 'waveform':
                    if parts[3] == 'morph':
                        # Extract ring waveform sequence
                        if len(parts) >= 6 and '-' in parts[5]:
                            self.ring_waveform_sequence = parts[5].split('-')
                            _log(f"Found ring waveform sequence: {self.ring_waveform_sequence}")
                            # Create separate range for ring morph
                            self.global_ranges['ring_morph'] = MidiRange('ring_morph', 0, 1)
                    elif len(parts) >= 5:
                        self.current_ring_params['waveform'] = parts[4]
                        _log(f"Found ring mod waveform: {parts[4]}")
                        
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
                    elif param_name == 'waveform' and next_part in ('triangle', 'sine', 'square', 'saw'):
                        self.fixed_values[param_name] = next_part
                        
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
                range_obj = MidiRange(param_name, min_val, max_val)
                
                if scope == 'global':
                    self.global_ranges[param_name] = range_obj
                else:
                    self.key_ranges[param_name] = range_obj
            except ValueError as e:
                raise ValueError(f"Invalid range format {range_str}: {str(e)}")
    
    def convert_value(self, param_name, midi_value, is_global=True):
        """Convert MIDI value using appropriate range."""
        ranges = self.global_ranges if is_global else self.key_ranges
        if param_name not in ranges:
            raise KeyError(f"No range defined for parameter: {param_name}")
        return ranges[param_name].convert(midi_value)

    def update_envelope(self):
        """Create a new envelope with current parameters."""
        return synthio.Envelope(
            attack_time=self.current_envelope_params['attack_time'],
            decay_time=self.current_envelope_params['decay_time'],
            release_time=self.current_envelope_params['release_time'],
            attack_level=self.current_envelope_params['attack_level'],
            sustain_level=self.current_envelope_params['sustain_level']
        )
