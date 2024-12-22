"""Parameter and path management module."""

import array
import math
import synthio
from logging import log, TAG_ROUTE, format_value
import synthio
from synth_wave import WaveManager
from constants import STATIC_WAVEFORM_SAMPLES
from path_parser import PathParser

# Order of operations for startup values
STARTUP_ORDER = [
    'lfo_setup_',  # LFO setup (create and route)
]

# Complete type specification for parameters
PARAM_TYPES = {
    # Fixed Float (can't be block)
    'frequency': 'float',
    'ring_frequency': 'float',  # Must be float per synthio docs
    
    # Envelope parameters (clean names from path parser)
    'attack_time': 'float',
    'attack_level': 'float',
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
    'filter_type': 'str',  # String value for synthio.FilterMode enum
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

# MIDI message attribute mapping
MIDI_ATTRIBUTES = {
    'note_on': {
        'note': 'note',          # msg.note for frequency
        'velocity': 'velocity'    # msg.velocity for amplitude
    },
    'cc': 'value',              # msg.value
    'pitch_bend': 'bend',       # msg.bend
    'channel_pressure': 'pressure',  # msg.pressure
    'note_off': 'note'          # msg.note
}

# Message type definitions
MESSAGE_TYPES = {
    'note_on': {
        'collect': ['frequency', 'velocity', 'pressure'],
        'requires': ['frequency'],
        'action': 'press_note'
    },
    'note_off': {
        'action': 'release_note'
    },
    'cc': {
        'per_cc': True  # Each CC number has its own routes
    },
    'pitch_bend': {
        'is_14_bit': True  # Uses 14-bit value range
    },
    'channel_pressure': {
        'collect': ['pressure']  # msg.pressure value
    }
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
    'attack_time': 'Attack Time',
    'attack_level': 'Attack Level',
    'decay_time': 'Decay Time',
    'sustain_level': 'Sustain Level',
    'release_time': 'Release Time',
    
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
                if isinstance(self.fixed_value, (array.array, bytearray, memoryview)):
                    log(TAG_ROUTE, f"Created route: {name} [fixed: waveform]")
                else:
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
        """Build lookup table for MIDI note number to Hz conversion."""
        # Create 128-entry table (0-127 MIDI notes)
        self.lookup_table = array.array('f', [0] * 128)
        
        # Fill table with Hz values using synthio's converter
        for note in range(128):
            self.lookup_table[note] = synthio.midi_to_hz(note)
            
        # Log some key notes
        log(TAG_ROUTE, f"Created Hz lookup table for {self.name}:")
        log(TAG_ROUTE, f"  Note   0: {self.lookup_table[0]:.1f} Hz")  # C-1
        log(TAG_ROUTE, f"  Note  60: {self.lookup_table[60]:.1f} Hz") # Middle C
        log(TAG_ROUTE, f"  Note  69: {self.lookup_table[69]:.1f} Hz") # A440
        log(TAG_ROUTE, f"  Note 127: {self.lookup_table[127]:.1f} Hz")
        
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
    
    def convert(self, value):
        """Get value from lookup table or fixed value."""
        if self.fixed_value is not None:
            return self.fixed_value
            
        if self.lookup_table is None:
            if self.is_waveform_sequence:
                morph_position = value / 127.0
                return self.wave_manager.create_morphed_waveform(self.waveform_sequence, morph_position)
            return value
            
        return self.lookup_table[value]

class Router:
    """Route management service that creates and manages routes based on parsed path data."""
    def __init__(self):
        self.wave_manager = WaveManager()
        self.midi_mappings = {}
        self.startup_values = {}
        self.enabled_messages = set()
        self.enabled_ccs = []
        self.current_instrument_name = None
        self.on_paths_parsed = None
        self.path_parser = PathParser()
        self.lfo_config = {}  # Store LFO configuration from path parser
        
    def parse_paths(self, paths, config_name=None):
        """Parse paths and create routes."""
        log(TAG_ROUTE, "Parsing instrument paths...")
        log(TAG_ROUTE, "----------------------------------------")
        
        try:
            # Reset state
            self.midi_mappings.clear()
            self.startup_values.clear()
            self.enabled_messages.clear()
            self.enabled_ccs = []
            self.lfo_config.clear()  # Reset LFO config
            
            # Parse paths
            parse_result = self.path_parser.parse_paths(paths, config_name)
            
            # Create routes from parse result
            self._create_routes(parse_result)
            
            # Store results
            self.midi_mappings = parse_result.midi_mappings
            existing_lfo_setups = {}
            for k, v in self.startup_values.items():
                if k.startswith('lfo_setup_'):
                    existing_lfo_setups[k] = v
            self.startup_values = parse_result.startup_values  
            self.startup_values.update(existing_lfo_setups)
            self.enabled_messages = parse_result.enabled_messages
            self.enabled_ccs = parse_result.enabled_ccs
            self.current_instrument_name = parse_result.current_instrument_name
            self.lfo_config = parse_result.lfo_config  # Store LFO config from parser
            
            # Notify listeners that paths have been parsed
            if self.on_paths_parsed:
                self.on_paths_parsed()
                
        except Exception as e:
            log(TAG_ROUTE, f"Failed to parse paths: {str(e)}", is_error=True)
            raise
            
    def _create_routes(self, parse_result):
        """Create routes from parsed path data."""
        # Create routes first
        routes = {}
        note_on_routes = {}  # Special table for note-on values
        
        # Find all route types needed
        for trigger, actions in parse_result.midi_mappings.items():
            for action in actions:
                if not action.get('needs_route'):
                    continue
                    
                handler = action['handler']
                route_info = action['route_info']
                
                # Skip if route already created
                if handler in routes:
                    continue
                    
                # Create route based on type
                if route_info['type'] == 'note_to_freq':
                    route = Route(
                        handler,
                        is_note_to_freq=True,
                        wave_manager=self.wave_manager
                    )
                    routes[handler] = route
                    # Add to note-on table
                    note_on_routes['note'] = {
                        'handler': handler,
                        'route': route
                    }
                elif route_info['type'] == 'waveform_sequence':
                    routes[handler] = Route(
                        handler,
                        waveform_sequence=route_info['sequence'],
                        wave_manager=self.wave_manager
                    )
                elif route_info['type'] == 'range':
                    min_val, max_val = route_info['range']
                    route = Route(
                        handler,
                        min_val=min_val,
                        max_val=max_val,
                        is_14_bit=route_info.get('is_14_bit', False),
                        wave_manager=self.wave_manager
                    )
                    routes[handler] = route
                    routes[handler] = route
                    
                    # If this is a velocity route, also add it to note_on since velocity is part of note_on
                    if trigger == 'velocity':
                        # Create note_on list if needed
                        if 'note_on' not in self.midi_mappings:
                            self.midi_mappings['note_on'] = []
                        # Add velocity action to note_on mappings
                        velocity_action = action.copy()  # Copy to avoid modifying original
                        velocity_action['route'] = route
                        self.midi_mappings['note_on'].append(velocity_action)
                elif route_info['type'] == 'fixed':
                    routes[handler] = Route(
                        handler,
                        fixed_value=route_info['value'],
                        wave_manager=self.wave_manager
                    )
        
        # Store note-on routes table
        self.note_on_routes = note_on_routes
        
        # Attach routes to actions
        for actions in parse_result.midi_mappings.values():
            for action in actions:
                if action.get('needs_route'):
                    handler = action['handler']
                    action['route'] = routes[handler]
                    del action['needs_route']
                    del action['route_info']
        
            # Create routes for startup values and LFOs
            for handler, config in parse_result.startup_values.items():
                value = config['value']
                if isinstance(value, dict):
                    if value['type'] == 'waveform':
                        try:
                            config['value'] = self.wave_manager.create_waveform(
                                value['name'],
                                STATIC_WAVEFORM_SAMPLES
                            )
                        except Exception as e:
                            log(TAG_ROUTE, f"Failed to create waveform: {str(e)}", is_error=True)
                            raise
                    elif value['type'] == 'range':
                        route = Route(
                            handler,
                            min_val=value['range'][0],
                            max_val=value['range'][1],
                            wave_manager=self.wave_manager
                        )
                        config['value'] = route.convert(0)
                else:
                    # Create route to handle type conversion
                    route = Route(
                        handler,
                        fixed_value=value,
                        wave_manager=self.wave_manager
                    )
                    config['value'] = route.convert(0)
                    
            # Handle LFO configuration
            for lfo_name, lfo_config in parse_result.lfo_config.items():
                # Build LFO setup info
                lfo_setup = {
                    'name': lfo_name,
                    'steps': []
                }
                
                # Step 1: Create LFO with initial params
                create_params = {}
                for param_name, param_config in lfo_config['params'].items():
                    if isinstance(param_config['value'], dict):
                        if param_config['value']['type'] == 'range':
                            # Get range tuple directly
                            min_val, max_val = param_config['value']['range']
                            # Use middle of range as initial value
                            create_params[param_name] = (min_val + max_val) / 2
                        elif param_config['value']['type'] == 'waveform':
                            # Pass waveform info through to synth
                            create_params['waveform'] = {'value': param_config['value']}
                    else:
                        create_params[param_name] = float(param_config['value'])
                lfo_setup['steps'].append(('create', create_params))
                
                # Step 2: Route LFO to targets
                for target in lfo_config['targets']:
                    target_value = target['param']
                    if target['filter_type']:
                        target_value = f"{target_value}:{target['filter_type']}"
                    lfo_setup['steps'].append(('route', target_value))
                
                # Store LFO setup info
                self.startup_values[f"lfo_setup_{lfo_name}"] = {
                    'value': lfo_setup,
                    'use_channel': False  # LFO setup is always global
                }
    
    def get_startup_values(self):
        """Get startup values and LFO config.
        
        Returns:
            Tuple of (startup_values, lfo_config)
            Note: lfo_config is empty as LFOs are handled by synth
        """
        log(TAG_ROUTE, "=== Getting Startup Values ===")
        log(TAG_ROUTE, "\nLFO Config:")
        for lfo_name, config in self.lfo_config.items():
            log(TAG_ROUTE, f"LFO {lfo_name}:")
            log(TAG_ROUTE, f"  Parameters: {format_value(config['params'])}")
            log(TAG_ROUTE, f"  Targets: {config['targets']}")
            
        log(TAG_ROUTE, "\nStartup Values:")
        for handler, config in self.startup_values.items():
            if handler.startswith('lfo_setup_'):
                lfo_setup = config['value']
                log(TAG_ROUTE, f"\nLFO Setup for {lfo_setup['name']}:")
                for step, params in lfo_setup['steps']:
                    log(TAG_ROUTE, f"  {step}: {format_value(params)}")
            else:
                if isinstance(config['value'], (array.array, bytearray, memoryview)):
                    log(TAG_ROUTE, f"{handler}: waveform")
                else:
                    log(TAG_ROUTE, f"{handler}: {format_value(config['value'])}")
        
        # Create ordered dict of startup values
        ordered_values = {}
        
        # Add LFO setup first
        for handler, config in self.startup_values.items():
            if handler.startswith('lfo_setup_'):
                ordered_values[handler] = config
                lfo_setup = config['value']
                log(TAG_ROUTE, f"Adding LFO setup: {lfo_setup['name']}")
                log(TAG_ROUTE, f"  Steps: {lfo_setup['steps']}")
                    
        # Add remaining values
        for handler, config in self.startup_values.items():
            if not handler.startswith('lfo_setup_'):
                ordered_values[handler] = config
                log(TAG_ROUTE, f"Adding startup value: {handler}")
                
        log(TAG_ROUTE, "Returning ordered values")
        return (ordered_values, {})
    
    def get_midi_mappings(self):
        """Get MIDI mappings."""
        return self.midi_mappings.copy()
    
    def get_message_type(self, msg):
        """Get message type definition for a MIDI message.
        
        Args:
            msg: MIDI message to get type for
            
        Returns:
            Message type definition from MESSAGE_TYPES
        """
        msg_type = msg.type
        if msg_type == 'note_on' and msg.velocity == 0:
            msg_type = 'note_off'
        return MESSAGE_TYPES.get(msg_type)
    
    def get_midi_attribute(self, trigger):
        """Get MIDI message attribute name for a trigger.
        
        Args:
            trigger: Trigger type (note_on, velocity, cc73, etc.)
            
        Returns:
            Attribute name to get from MIDI message
        """
        if trigger.startswith('cc'):
            return MIDI_ATTRIBUTES['cc']
        elif trigger == 'velocity':
            return MIDI_ATTRIBUTES['note_on']['velocity']  # msg.velocity
        elif trigger == 'note_on':
            return MIDI_ATTRIBUTES['note_on']['note']  # msg.note
        elif trigger == 'channel_pressure':
            return 'pressure'  # msg.pressure
        else:
            return MIDI_ATTRIBUTES.get(trigger)  # Other message types
            
    def get_message_values(self, msg, msg_type):
        """Get values from a MIDI message based on type definition.
        
        Args:
            msg: MIDI message to get values from
            msg_type: Message type definition from MESSAGE_TYPES
            
        Returns:
            Dict of collected values
        """
        values = {}
        
        # Get triggers for this message type
        triggers = []
        if msg.type == 'cc':
            triggers.append(f"cc{msg.control}")
        elif msg.type == 'note_on':
            triggers.extend(['note_on', 'velocity'])
        else:
            triggers.append(msg.type)
            
        # Process each trigger
        for trigger in triggers:
            actions = self.midi_mappings.get(trigger, [])
            for action in actions:
                if 'route' in action:
                    try:
                        # Get MIDI value using mapped attribute
                        midi_value = getattr(msg, self.get_midi_attribute(trigger))
                        values[action['handler']] = action['route'].convert(midi_value)
                    except Exception as e:
                        log(TAG_ROUTE, f"Failed to convert value: {str(e)}", is_error=True)
                
        return values
    
    def get_channel_scope(self, msg, action):
        """Get channel scope for an action.
        
        Args:
            msg: MIDI message
            action: Action from route table
            
        Returns:
            Channel number to use (0 for global)
        """
        return 0 if msg.channel == 0 or not action['use_channel'] else msg.channel
    
    def get_cc_configs(self):
        """Generate CC configuration string."""
        pot_mappings = []
        for pot_num, cc_num in enumerate(self.enabled_ccs):
            midi_value = f"cc{cc_num}"
            actions = self.midi_mappings.get(midi_value, [])
            
            if actions:
                handler = actions[0]['handler']
                if handler.startswith('set_'):
                    handler = handler[4:]
                
                # Get human-readable control label
                control_label = control_label_map.get(handler, handler)
                
                # Format pot mapping
                pot_str = config_format['pot_mapping']['format'].format(
                    pot_number=pot_num,
                    cc_number=cc_num,
                    controls=control_label
                )
                pot_mappings.append(pot_str)
        
        # Build final string
        parts = []
        for element in config_format['structure']['order']:
            if element == 'cartridge_name':
                parts.append('Candide')
            elif element == 'instrument_name':
                if self.current_instrument_name:
                    parts.append(format_instrument_name(self.current_instrument_name))
                else:
                    parts.append('')
            elif element == 'type':
                parts.append('cc')
            elif element == 'pot_mappings':
                parts.extend(pot_mappings)
        
        return config_format['structure']['separators']['main'].join(parts)

# Global router service
_router = None

def get_router():
    """Get the global router service instance."""
    global _router
    if _router is None:
        _router = Router()
    return _router
