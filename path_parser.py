"""Path parsing module for converting human-readable paths to structured routing data."""

from logging import log, TAG_PARSER, format_value

class PathParseResult:
    """Container for parsed path data."""
    def __init__(self):
        self.midi_mappings = {}  # MIDI trigger -> list of actions
        self.startup_values = {}  # Handler -> {value, use_channel}
        self.enabled_messages = set()  # Enabled MIDI message types
        self.enabled_ccs = []  # Enabled CC numbers (ordered)
        self.lfo_config = {}  # LFO name -> {params: {}, targets: []}
        self.current_instrument_name = None

class PathParser:
    """Parses human-readable paths into structured routing data."""
    
    def parse_paths(self, paths, config_name=None):
        """Parse paths into structured routing data.
        
        Args:
            paths: String containing newline-separated paths
            config_name: Optional name of the configuration
            
        Returns:
            PathParseResult containing parsed routing data
        """
        log(TAG_PARSER, "=== Starting Path Parsing ===")
        result = PathParseResult()
        
        if config_name:
            log(TAG_PARSER, f"Configuration: {config_name}")
            # Extract instrument name from config name (remove _PATHS suffix)
            if config_name.endswith('_PATHS'):
                result.current_instrument_name = config_name[:-6].lower()
                log(TAG_PARSER, f"Instrument name: {result.current_instrument_name}")
        
        try:
            if not paths:
                log(TAG_PARSER, "No paths provided", is_error=True)
                raise ValueError("No paths provided")
                
            log(TAG_PARSER, "Processing paths...")
            for line in paths.strip().split('\n'):
                if not line or line.startswith('#'):
                    continue
                    
                try:
                    log(TAG_PARSER, f"\nParsing path: {line}")
                    parts = line.strip().split('/')
                    self._parse_line(parts, result)
                except Exception as e:
                    log(TAG_PARSER, f"Failed to parse path: {line}", is_error=True)
                    log(TAG_PARSER, f"Error details: {str(e)}", is_error=True)
                    raise
                    
            # Log final parse results
            log(TAG_PARSER, "\n=== Parse Results ===")
            
            log(TAG_PARSER, "\nMIDI Mappings:")
            for midi_value, actions in result.midi_mappings.items():
                log(TAG_PARSER, f"{midi_value} -> [")
                for action in actions:
                    log(TAG_PARSER, f"  {format_value(action)}")
                log(TAG_PARSER, "]")
                
            log(TAG_PARSER, "\nStartup Values:")
            for handler, config in result.startup_values.items():
                if isinstance(config['value'], dict) and config['value'].get('type') == 'waveform':
                    log(TAG_PARSER, f"{handler} -> waveform")
                else:
                    log(TAG_PARSER, f"{handler} -> {format_value(config['value'])}")
                    
            log(TAG_PARSER, "\nLFO Configuration:")
            for lfo_name, config in result.lfo_config.items():
                log(TAG_PARSER, f"LFO: {lfo_name}")
                log(TAG_PARSER, f"  Parameters: {format_value(config['params'])}")
                log(TAG_PARSER, f"  Targets: {config['targets']}")
                
            log(TAG_PARSER, f"\nEnabled messages: {result.enabled_messages}")
            if 'cc' in result.enabled_messages:
                log(TAG_PARSER, f"Enabled CCs: {result.enabled_ccs}")
                
            log(TAG_PARSER, "\n=== Path Parsing Complete ===")
            
            return result
            
        except Exception as e:
            log(TAG_PARSER, f"Failed to parse paths: {str(e)}", is_error=True)
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
                log(TAG_PARSER, f"Invalid range format: {range_str}", is_error=True)
                raise ValueError(f"Invalid range format: {range_str}")
                
            min_str, max_str = range_str.split('-')
            
            if min_str.startswith('n'):
                min_val = -float(min_str[1:])
            else:
                min_val = float(min_str)
                
            max_val = float(max_str)
            
            log(TAG_PARSER, f"Parsed range {range_str} -> {min_val} to {max_val}")
            
            return min_val, max_val
            
        except ValueError as e:
            log(TAG_PARSER, f"Failed to parse range: {range_str}", is_error=True)
            log(TAG_PARSER, f"Error details: {str(e)}", is_error=True)
            raise ValueError(f"Invalid range format {range_str}: {str(e)}")

    def _parse_line(self, parts, result):
        """Parse a single path line and update the parse result.
        
        Args:
            parts: List of path components
            result: PathParseResult to update
        """
        if len(parts) < 3:
            log(TAG_PARSER, f"Invalid path format: {'/'.join(parts)}", is_error=True)
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
        scope = parts[0]
        handler = parts[1]
        value_or_range = parts[2]
        
        log(TAG_PARSER, f"  Scope: {scope}")
        log(TAG_PARSER, f"  Handler: {handler}")
        log(TAG_PARSER, f"  Value/Range: {value_or_range}")

        # Note handling
        if handler in ('press_note', 'release_note'):
            if scope != 'channel':
                log(TAG_PARSER, f"Invalid scope for note handling: {scope}", is_error=True)
                raise ValueError(f"Invalid scope for note handling: {scope}")
            if value_or_range not in ('note_on', 'note_off'):
                log(TAG_PARSER, f"Invalid trigger for note handling: {value_or_range}", is_error=True)
                raise ValueError(f"Invalid trigger for note handling: {value_or_range}")
                
            midi_value = value_or_range
            if midi_value not in result.midi_mappings:
                result.midi_mappings[midi_value] = []
            
            action = {
                'handler': handler,
                'scope': 'channel',
                'use_channel': True
            }
            result.midi_mappings[midi_value].append(action)
            result.enabled_messages.add(midi_value)
            log(TAG_PARSER, f"  Added note handler: {handler} -> {midi_value}")
            return

        # Map paths to store parameters
        if ':' in handler:
            if handler.startswith('envelope:'):
                # Format: scope/envelope:param/value/trigger
                _, param = handler.split(':')
                # Use clean parameter name
                handler = param
                log(TAG_PARSER, f"  Mapped envelope parameter: {param}")
                
            elif handler.startswith('filter_frequency:') or handler.startswith('filter_resonance:'):
                # Format: scope/filter_(frequency|resonance):type/value/trigger
                _, filter_type = handler.split(':')
                # Store filter type
                if 'filter_type' not in result.startup_values:
                    result.startup_values['filter_type'] = {
                        'value': filter_type,
                        'use_channel': scope == 'channel'
                    }
                # Map handler to appropriate parameter
                if handler.startswith('filter_frequency:'):
                    handler = 'filter_frequency'
                    log(TAG_PARSER, f"  Mapped filter frequency: {filter_type}")
                else:
                    handler = 'filter_q'
                    log(TAG_PARSER, f"  Mapped filter resonance: {filter_type}")

        # LFO parameter definition
        if handler == 'lfo':
            # Format: scope/lfo/param/name:value/[trigger]
            if len(parts) < 4:
                log(TAG_PARSER, "Invalid LFO parameter path", is_error=True)
                raise ValueError("Invalid LFO parameter path")
            param = value_or_range
            name_value = parts[3]
            if ':' not in name_value:
                log(TAG_PARSER, "Invalid LFO name:value format", is_error=True)
                raise ValueError("Invalid LFO name:value format")
            name_parts = name_value.split(':')
            if len(name_parts) != 2:
                log(TAG_PARSER, "Invalid LFO name:value format", is_error=True)
                raise ValueError("Invalid LFO name:value format")
                
            lfo_name = name_parts[0]  # Get LFO name first
            value = name_parts[1]
            handler = f"lfo_{param}_{lfo_name}"
            
            log(TAG_PARSER, f"  Processing LFO: {lfo_name}")
            log(TAG_PARSER, f"    Parameter: {param}")
            log(TAG_PARSER, f"    Value: {value}")
            
            # Initialize LFO config if needed
            if lfo_name not in result.lfo_config:
                result.lfo_config[lfo_name] = {
                    'params': {},
                    'targets': []
                }
            
            # Parse LFO parameter value
            param_config = {}
            
            # Handle boolean parameters
            if param in ('once', 'interpolate'):
                param_config['value'] = value.lower() == 'true'
                log(TAG_PARSER, f"    Boolean parameter {param}: {param_config['value']}")
                
            # Handle waveform parameter
            elif param == 'waveform':
                param_config['value'] = {'type': 'waveform', 'name': value}
                log(TAG_PARSER, f"    Waveform parameter: {value}")
                
            # Handle numeric range or value
            else:
                if '-' in value:
                    min_val, max_val = self._parse_range(value)
                    param_config['value'] = {'type': 'range', 'range': (min_val, max_val)}
                    log(TAG_PARSER, f"    Range parameter {param}: {min_val} to {max_val}")
                else:
                    try:
                        param_config['value'] = float(value)
                        log(TAG_PARSER, f"    Numeric parameter {param}: {value}")
                    except ValueError:
                        param_config['value'] = value
                        log(TAG_PARSER, f"    String parameter {param}: {value}")
                
            # Handle MIDI control if present
            if len(parts) > 4:
                midi_value = parts[4]
                param_config['midi'] = midi_value
                log(TAG_PARSER, f"    MIDI Control: {midi_value}")
                
                # Enable MIDI message type
                if midi_value.startswith('cc'):
                    cc_num = int(midi_value[2:])
                    result.enabled_messages.add('cc')
                    if cc_num not in result.enabled_ccs:
                        result.enabled_ccs.append(cc_num)
                    midi_value = f"cc{cc_num}"
                    log(TAG_PARSER, f"    Enabled CC: {cc_num}")
                elif midi_value == 'pitch_bend':
                    result.enabled_messages.add('pitch_bend')
                elif midi_value == 'pressure':
                    result.enabled_messages.add('channel_pressure')
                    midi_value = 'channel_pressure'
                elif midi_value == 'velocity':
                    result.enabled_messages.add('note_on')
                    midi_value = 'velocity'
                    
                # Add MIDI mapping
                if midi_value not in result.midi_mappings:
                    result.midi_mappings[midi_value] = []
                result.midi_mappings[midi_value].append({
                    'handler': f"lfo_{param}_{lfo_name}",  # Unique handler per LFO param
                    'scope': scope,
                    'use_channel': scope == 'channel',
                    'needs_route': True,
                    'route_info': {
                        'type': 'range',
                        'range': param_config['value']['range'] if 'range' in param_config['value'] else (0, 1)
                    }
                })
                log(TAG_PARSER, f"    Added MIDI mapping: {midi_value}")
            
            # Store parameter config
            result.lfo_config[lfo_name]['params'][param] = param_config
            log(TAG_PARSER, f"    Stored parameter config: {format_value(param_config)}")
            return

        # LFO routing (including filter targets)
        if value_or_range.startswith('lfo:'):
            # Format: scope/target[:type]/lfo:name
            lfo_name = value_or_range.split(':')[1].strip()
            
            # Handle filter target with type
            if ':' in handler:
                base_handler, filter_type = handler.split(':')
                if filter_type not in result.startup_values:
                    result.startup_values['filter_type'] = {
                        'value': filter_type,
                        'use_channel': scope == 'channel'
                    }
                handler = base_handler
                
            # Add target to LFO config
            if lfo_name in result.lfo_config:
                target_info = {
                    'param': handler,
                    'filter_type': filter_type if ':' in handler else None
                }
                result.lfo_config[lfo_name]['targets'].append(target_info)
                log(TAG_PARSER, f"  Added LFO target: {lfo_name} -> {target_info}")
            return

        if len(parts) == 4:
            midi_value = parts[3]
            log(TAG_PARSER, f"  MIDI trigger: {midi_value}")
            
            if midi_value.startswith('cc'):
                cc_num = int(midi_value[2:])
                result.enabled_messages.add('cc')
                if cc_num not in result.enabled_ccs:
                    result.enabled_ccs.append(cc_num)
                midi_value = f"cc{cc_num}"
                log(TAG_PARSER, f"  Enabled CC: {cc_num}")
            elif midi_value == 'pitch_bend':
                result.enabled_messages.add('pitch_bend')
            elif midi_value == 'pressure':
                # Translate human-friendly 'pressure' to MIDI message type
                result.enabled_messages.add('channel_pressure')
                midi_value = 'channel_pressure'  # Use actual MIDI message type
                log(TAG_PARSER, f"  Mapped pressure to channel_pressure")
            elif midi_value == 'velocity':
                result.enabled_messages.add('note_on')
                midi_value = 'velocity'
            elif midi_value == 'note_on':
                result.enabled_messages.add('note_on')
                
            # Add to MIDI mappings
            if midi_value not in result.midi_mappings:
                result.midi_mappings[midi_value] = []
                
            action = {
                'handler': handler,
                'scope': scope,
                'use_channel': scope == 'channel'
            }

            # Check for waveform morphing
            if handler.endswith('waveform') and '-' in value_or_range:
                action['needs_route'] = True
                action['route_info'] = {
                    'type': 'waveform_sequence',
                    'sequence': value_or_range.split('-')
                }
                log(TAG_PARSER, f"  Added waveform morph route: {value_or_range}")
            elif '-' in value_or_range:
                action['needs_route'] = True
                action['route_info'] = {
                    'type': 'range',
                    'range': self._parse_range(value_or_range),
                    'is_14_bit': midi_value == 'pitch_bend'
                }
                log(TAG_PARSER, f"  Added range route: {value_or_range}")
            elif value_or_range == 'note_number':
                action['needs_route'] = True
                action['route_info'] = {
                    'type': 'note_to_freq'
                }
                log(TAG_PARSER, f"  Added note-to-freq route")
            else:
                action['needs_route'] = True
                action['route_info'] = {
                    'type': 'fixed',
                    'value': value_or_range
                }
                log(TAG_PARSER, f"  Added fixed route: {value_or_range}")
                
            result.midi_mappings[midi_value].append(action)
            log(TAG_PARSER, f"  Added MIDI mapping: {midi_value}")
            
        else:
            # Store as startup value
            if handler.endswith('waveform'):
                result.startup_values[handler] = {
                    'value': {'type': 'waveform', 'name': value_or_range},
                    'use_channel': scope == 'channel'
                }
                log(TAG_PARSER, f"  Added waveform")
            else:
                result.startup_values[handler] = {
                    'value': value_or_range,
                    'use_channel': scope == 'channel'
                }
                log(TAG_PARSER, f"  Added startup value: {value_or_range}")
