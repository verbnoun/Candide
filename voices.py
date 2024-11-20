"""
Advanced Voice Management System for Synthesizer

Handles voice lifecycle, parameter routing, and sound generation.
"""

import time
import sys
import synthio
from fixed_point_math import FixedPoint
from constants import VOICES_DEBUG
from synthesizer import Synthesis

def _format_log_message(message):
    """
    Format a dictionary message for console logging with specific indentation rules.
    Handles dictionaries, lists, and primitive values.
    
    Args:
        message (dict): Message to format
        
    Returns:
        str: Formatted message string
    """
    def format_value(value, indent_level=0):
        """Recursively format values with proper indentation."""
        base_indent = ' ' * 0
        extra_indent = ' ' * 2
        indent = base_indent + ' ' * (4 * indent_level)
        
        if isinstance(value, dict):
            if not value:  # Handle empty dict
                return '{}'
            lines = ['{']
            for k, v in value.items():
                formatted_v = format_value(v, indent_level + 1)
                lines.append(f"{indent + extra_indent}'{k}': {formatted_v},")
            lines.append(f"{indent}}}")
            return '\n'.join(lines)
        
        elif isinstance(value, list):
            if not value:  # Handle empty list
                return '[]'
            lines = ['[']
            for item in value:
                formatted_item = format_value(item, indent_level + 1)
                lines.append(f"{indent + extra_indent}{formatted_item},")
            lines.append(f"{indent}]")
            return '\n'.join(lines)
        
        elif isinstance(value, str):
            return f"'{value}'"
        else:
            return str(value)
            
    return format_value(message)

def _log(message):
    """
    Conditional logging function that respects VOICES_DEBUG flag.
    Args:
        message (str): Message to log
    """
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[37m"
    DARK_GRAY = "\033[90m"
    RESET = "\033[0m" 
    
    if VOICES_DEBUG:
        if "rejected" in message:
            color = DARK_GRAY
        elif "[ERROR]" in message:
            color = RED
        elif "[SYNTHIO]" in message:
            color = GREEN
        else:
            color = CYAN

        # If message is a dictionary, format with custom indentation
        if isinstance(message, dict):
            formatted_message = _format_log_message(message)
            print(f"{color}{formatted_message}{RESET}", file=sys.stderr)
        else:
            print(f"{color}[VOICES] {message}{RESET}", file=sys.stderr)

class Route:
    """
    Handles parameter routing with advanced processing capabilities.
    Supports various curve transformations and scaling.
    """
    def __init__(self, config):
        _log(f"Creating Route with config:")
        _log(config)
        
        # Direct config validation - fail fast if missing required fields
        if not isinstance(config, dict):
            _log("[ERROR] Route config must be a dictionary")
            raise ValueError("Route config must be a dictionary")
            
        self.source_id = config['source']
        self.target_id = config['target']
        
        if not self.source_id or not self.target_id:
            _log("[ERROR] Route requires both source and target IDs")
            raise ValueError("Route requires both source and target IDs")
        
        self.amount = FixedPoint.from_float(config.get('amount', 1.0))
        self.curve = config['curve']
        
        # Direct range extraction - no recursive processing
        range_config = config.get('range', {})
        self.min_value = FixedPoint.from_float(range_config.get('min', 0.0))
        self.max_value = FixedPoint.from_float(range_config.get('max', 1.0))
        
        # State tracking
        self.current_value = FixedPoint.ZERO
        self.last_value = FixedPoint.ZERO
        
        _log(f"Route created successfully:")
        _log(f"  Source: {self.source_id}")
        _log(f"  Target: {self.target_id}")
        _log(f"  Amount: {self.amount}")
        _log(f"  Curve: {self.curve}")
    
    def process_value(self, value):
        """
        Process input value through configured transformations.
        
        Args:
            value (float/int): Input value to process
        
        Returns:
            FixedPoint: Processed and scaled value
        """
        _log(f"Processing route value: source={self.source_id}, target={self.target_id}, input={value}")
        
        if not isinstance(value, FixedPoint):
            value = FixedPoint.from_float(value)
        
        # Store previous value
        self.last_value = self.current_value
        
        # Direct curve application without recursive processing
        if self.curve == 'exponential':
            processed = self._exponential_curve(value)
            _log(f"Applied exponential curve transformation")
        elif self.curve == 'logarithmic':
            processed = self._logarithmic_curve(value)
            _log(f"Applied logarithmic curve transformation")
        elif self.curve == 's_curve':
            processed = self._s_curve(value)
            _log(f"Applied S-curve transformation")
        else:  # linear
            processed = value
            _log(f"Using linear transformation")
        
        # Direct range scaling
        range_size = self.max_value - self.min_value
        scaled_value = self.min_value + FixedPoint.multiply(processed, range_size)
        
        # Apply modulation amount
        self.current_value = FixedPoint.multiply(scaled_value, self.amount)
        
        _log(f"Route processed: last_value={self.last_value}, current_value={self.current_value}")
        
        return self.current_value
    
    def _exponential_curve(self, value):
        """Exponential curve transformation"""
        _log(f"Computing exponential curve for value: {value}")
        exp_scale = FixedPoint.from_float(5.0)
        scaled = FixedPoint.multiply(value, exp_scale)
        x2 = FixedPoint.multiply(scaled, scaled)
        x3 = FixedPoint.multiply(x2, scaled)
        processed = (FixedPoint.ONE + scaled + 
                     FixedPoint.multiply(x2, FixedPoint.from_float(0.5)) + 
                     FixedPoint.multiply(x3, FixedPoint.from_float(0.166)))
        result = FixedPoint.multiply(processed, FixedPoint.from_float(0.0084))
        _log(f"Exponential curve result: {result}")
        return result
    
    def _logarithmic_curve(self, value):
        """Logarithmic curve transformation"""
        _log(f"Computing logarithmic curve for value: {value}")
        result = FixedPoint.ONE - FixedPoint.multiply(
            FixedPoint.ONE - value,
            FixedPoint.ONE - value
        )
        _log(f"Logarithmic curve result: {result}")
        return result
    
    def _s_curve(self, value):
        """S-curve transformation"""
        _log(f"Computing S-curve for value: {value}")
        x2 = FixedPoint.multiply(value, value)
        x3 = FixedPoint.multiply(x2, value)
        result = FixedPoint.multiply(x2, FixedPoint.from_float(3.0)) - \
               FixedPoint.multiply(x3, FixedPoint.from_float(2.0))
        _log(f"S-curve result: {result}")
        return result

class NoteState:
    """
    Comprehensive note state management with advanced routing capabilities.
    Handles per-note parameter tracking and modulation.
    """
    def __init__(self, channel, note, velocity, config, synthesis):
        _log(f"Creating NoteState:")
        _log(f"  channel={channel}")
        _log(f"  note={note}")
        _log(f"  velocity={velocity}")
        
        if not isinstance(config, dict):
            _log("[ERROR] NoteState config must be a dictionary")
            raise ValueError("NoteState config must be a dictionary")
        
        self.channel = channel
        self.note = note
        self.active = True
        self.creation_time = time.monotonic()
        self.last_update = self.creation_time
        self.config = config
        self.synthesis = synthesis
        
        # Direct parameter initialization without recursion
        self.parameter_values = {
            'note': FixedPoint.midi_note_to_fixed(note),
            'velocity': FixedPoint.normalize_midi_value(velocity),
            'frequency': FixedPoint.from_float(synthio.midi_to_hz(note)),
            'amplitude': FixedPoint.normalize_midi_value(velocity)
        }
        
        _log("Initialized parameter values:")
        _log(self.parameter_values)
        
        # Initialize module parameters directly
        for module_name in ['oscillator', 'amplifier', 'filter']:  # Keep all module support
            if module_name in config:
                self._init_module_parameters(module_name, config[module_name])
        
        # Flat route management
        self.routes_by_source = {}
        self.routes_by_target = {}
        self._create_routes()
        
        # Create synthio Note
        self.synth_note = self._create_synthio_note()
        
        _log(f"NoteState initialized with {len(self.routes_by_source)} source routes")
    
    def _init_module_parameters(self, module_name, module_config):
        """Initialize parameters for a module from config"""
        _log(f"Initializing parameters for module: {module_name}")
        
        if not isinstance(module_config, dict):
            return
            
        for param_name, param_data in module_config.items():
            if isinstance(param_data, dict) and 'value' in param_data:
                param_id = f"{module_name}.{param_name}"
                self.parameter_values[param_id] = FixedPoint.from_float(param_data['value'])
                _log(f"Set parameter {param_id} to {self.parameter_values[param_id]}")
    
    def _create_routes(self):
        """Create routing configuration based on instrument patches."""
        _log("Creating routes from instrument configuration")
        
        patches = self.config.get('patches', [])
        if not patches:
            _log("[ERROR] No patches found in configuration")
            raise ValueError("No patches found in configuration")
        
        for patch_config in patches:
            source = patch_config['source']
            destination = patch_config['destination']
            processing = patch_config['processing']
            
            # Flatten route configuration
            route_config = {
                'source': f"{source['id']}.{source['attribute']}" if 'attribute' in source else source['id'],
                'target': f"{destination['id']}.{destination['attribute']}" if 'attribute' in destination else destination['id'],
                'amount': processing.get('amount', 1.0),
                'curve': processing.get('curve', 'linear'),
                'range': processing.get('range', {})
            }
            
            _log("Creating route with config:")
            _log(route_config)
            
            # Create route with flattened config
            route = Route(route_config)
            
            # Index routes directly
            source_id = route.source_id
            target_id = route.target_id
            
            if source_id not in self.routes_by_source:
                self.routes_by_source[source_id] = []
            self.routes_by_source[source_id].append(route)
            
            if target_id not in self.routes_by_target:
                self.routes_by_target[target_id] = []
            self.routes_by_target[target_id].append(route)
            
            _log(f"Route created and indexed: source={source_id}, target={target_id}")
    
    def _create_synthio_note(self):
        """Create synthio Note object from config"""
        try:
            _log("[SYNTHIO] Creating Note object")
            
            osc_config = self.config['oscillator']
            waveform_config = osc_config['waveform']
            env_config = self.config.get('envelope', {}).get('stages', {})
            
            # Extract envelope values from config without defaults
            attack = env_config.get('attack', {})
            decay = env_config.get('decay', {})
            sustain = env_config.get('sustain', {})
            release = env_config.get('release', {})
            
            # Create envelope from config, converting fixed-point to float
            envelope = synthio.Envelope(
                attack_time=FixedPoint.to_float(attack.get('time', {}).get('value')),
                decay_time=FixedPoint.to_float(decay.get('time', {}).get('value')),
                release_time=FixedPoint.to_float(release.get('time', {}).get('value')),
                attack_level=FixedPoint.to_float(attack.get('level', {}).get('value')),
                sustain_level=FixedPoint.to_float(sustain.get('level', {}).get('value'))
            )
            
            _log("[SYNTHIO] Created envelope:")
            _log(f"[SYNTHIO]   Attack: {envelope.attack_time}s")
            _log(f"[SYNTHIO]   Decay: {envelope.decay_time}s")
            _log(f"[SYNTHIO]   Release: {envelope.release_time}s")
            _log(f"[SYNTHIO]   Attack Level: {envelope.attack_level}")
            _log(f"[SYNTHIO]   Sustain Level: {envelope.sustain_level}")
            
            # Get waveform from synthesis
            waveform = self.synthesis.waveform_manager.get_waveform(
                waveform_config.get('default', 'triangle'),
                waveform_config
            )
            if not waveform:
                _log("[ERROR] Failed to get waveform")
                raise ValueError("Failed to get waveform")
                
            _log(f"[SYNTHIO] Using waveform: {len(waveform)} samples")
            
            # Create note with all possible parameters
            note_params = {
                'frequency': FixedPoint.to_float(self.parameter_values['frequency']),
                'waveform': waveform,
                'envelope': envelope,
                'amplitude': FixedPoint.to_float(self.parameter_values['amplitude'])
            }
            
            # Add filter if configured
            if 'filter' in self.config:
                filter_config = self.config['filter']
                note_params['filter'] = synthio.Biquad(
                    filter_config.get('b0', 1.0),
                    filter_config.get('b1', 0.0),
                    filter_config.get('b2', 0.0),
                    filter_config.get('a1', 0.0),
                    filter_config.get('a2', 0.0)
                )
            
            note = synthio.Note(**note_params)
            
            _log(f"[SYNTHIO] Created Note object:")
            _log(f"[SYNTHIO]   Frequency: {note.frequency:.1f}Hz")
            _log(f"[SYNTHIO]   Amplitude: {note.amplitude:.3f}")
            _log(f"[SYNTHIO]   Has Filter: {hasattr(note, 'filter')}")
            _log(f"[SYNTHIO]   Note ID: {id(note)}")
            
            return note
            
        except Exception as e:
            _log(f"[ERROR] Failed to create synthio Note: {str(e)}")
            return None
    
    def handle_value_change(self, source_id, value):
        """Process value changes through configured routes."""
        _log(f"Handling value change: source={source_id}, value={value}")
        
        if source_id not in self.routes_by_source:
            _log(f"[ERROR] No routes found for source: {source_id}")
            return
        
        # Store source value directly
        self.parameter_values[source_id] = value
        
        # Process through routes without recursion
        for route in self.routes_by_source[source_id]:
            processed_value = route.process_value(value)
            target_id = route.target_id
            
            # Direct parameter update
            self.parameter_values[target_id] = processed_value
            
            # Use synthesis for note parameter updates
            if self.synth_note:
                self.synthesis.update_note(self.synth_note, target_id, processed_value)
            
            _log(f"Route processed: source={source_id}, target={target_id}, processed_value={processed_value}")
    
    def get_parameter_value(self, param_id):
        """Retrieve current value for a specific parameter."""
        value = self.parameter_values.get(param_id, FixedPoint.ZERO)
        _log(f"Retrieved parameter value: param_id={param_id}, value={value}")
        return value
    
    def handle_release(self):
        """Process note release"""
        _log(f"Handling note release: channel={self.channel}, note={self.note}")
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            self.handle_value_change('gate', FixedPoint.ZERO)
            _log("[SYNTHIO] Note entering release phase")
            _log("Note release completed")

class VoiceManager:
    """
    Manages voice lifecycle, allocation, and global voice state.
    """
    def __init__(self, sample_rate=44100):
        _log("Initializing VoiceManager")
        self.active_notes = {}
        self.pending_values = {}
        self.current_config = None
        
        # Create synthesis instance
        self.synthesis = Synthesis()
        
        try:
            self.synthio_synth = synthio.Synthesizer(
                sample_rate=sample_rate,
                channel_count=2
            )
            _log("[SYNTHIO] Initialized synthesizer")
            _log(f"[SYNTHIO] Sample Rate: {self.synthio_synth.sample_rate}")
        except Exception as e:
            _log(f"[ERROR] Failed to initialize synthio synthesizer: {str(e)}")
            self.synthio_synth = None
    
    def set_config(self, config):
        """Update current instrument configuration"""
        _log(f"Setting instrument configuration:")
        _log(config)
        
        if not isinstance(config, dict):
            _log("[ERROR] VoiceManager config must be a dictionary")
            raise ValueError("VoiceManager config must be a dictionary")
            
        if 'oscillator' not in config:
            _log("[ERROR] Configuration missing required oscillator module")
            raise ValueError("Configuration missing required oscillator module")
            
        if 'amplifier' not in config:
            _log("[ERROR] Configuration missing required amplifier module")
            raise ValueError("Configuration missing required amplifier module")
        
        self.current_config = config
        
        if self.synthio_synth:
            synth_config = config.get('synthesizer', {})
            if synth_config:
                self.synthio_synth.sample_rate = synth_config.get('sample_rate', 44100)
                _log(f"[SYNTHIO] Updated sample rate: {self.synthio_synth.sample_rate}")
    
    def store_pending_value(self, channel, source_id, value, control_name=None):
        """Store values that arrive before note-on event."""
        key = (channel, source_id)
        self.pending_values[key] = (value, control_name)
        _log(f"Stored pending value: channel={channel}, source_id={source_id}, value={value}, control_name={control_name}")
    
    def get_pending_values(self, channel):
        """Retrieve and clear pending values for a specific channel."""
        values = {}
        for (c, source_id), (value, control_name) in list(self.pending_values.items()):
            if c == channel:
                values[source_id] = (value, control_name)
                del self.pending_values[(c, source_id)]
        
        _log(f"Retrieved pending values for channel {channel}: {values}")
        return values
    
    def allocate_voice(self, channel, note, velocity):
        """Create a new voice for a note"""
        _log(f"Attempting to allocate voice:")
        _log(f"  channel={channel}")
        _log(f"  note={note}")
        _log(f"  velocity={velocity}")
        
        if not self.current_config:
            _log("[ERROR] No current configuration available for voice allocation")
            raise ValueError("No current configuration available for voice allocation")
        
        try:
            note_state = NoteState(channel, note, velocity, self.current_config, self.synth_engine)
            
            # Apply pending values directly
            pending = self.get_pending_values(channel)
            for source_id, (value, _) in pending.items():
                note_state.handle_value_change(source_id, value)
            
            self.active_notes[(channel, note)] = note_state
            
            if self.synthio_synth and note_state.synth_note:
                try:
                    self.synthio_synth.press(note_state.synth_note)
                    _log(f"[SYNTHIO] Pressed note {note} (ID: {id(note_state.synth_note)})")
                    # Get envelope state after press
                    env_state, env_value = self.synthio_synth.note_info(note_state.synth_note)
                    _log(f"[SYNTHIO] Note envelope state: {env_state}")
                    _log(f"[SYNTHIO] Note envelope value: {env_value:.3f}")
                except Exception as e:
                    _log(f"[ERROR] Failed to press synthio note: {str(e)}")
            
            _log(f"Voice allocated successfully: channel={channel}, note={note}")
            return note_state
            
        except Exception as e:
            _log(f"[ERROR] Voice allocation failed: {str(e)}")
            return None
    
    def get_voice(self, channel, note):
        """Retrieve an active voice."""
        voice = self.active_notes.get((channel, note))
        _log(f"Retrieving voice:")
        _log(f"  channel={channel}")
        _log(f"  note={note}")
        _log(f"  voice={voice is not None}")
        return voice
    
    def release_voice(self, channel, note):
        """Handle voice release"""
        _log(f"Releasing voice:")
        _log(f"  channel={channel}")
        _log(f"  note={note}")
        
        voice = self.get_voice(channel, note)
        if voice:
            voice.handle_release()
            
            if self.synthio_synth and voice.synth_note:
                try:
                    # Get envelope state before release
                    env_state, env_value = self.synthio_synth.note_info(voice.synth_note)
                    _log(f"[SYNTHIO] Pre-release envelope state: {env_state}")
                    _log(f"[SYNTHIO] Pre-release envelope value: {env_value:.3f}")
                    
                    self.synthio_synth.release(voice.synth_note)
                    _log(f"[SYNTHIO] Released note {note} (ID: {id(voice.synth_note)})")
                    
                    # Get envelope state after release
                    env_state, env_value = self.synthio_synth.note_info(voice.synth_note)
                    _log(f"[SYNTHIO] Post-release envelope state: {env_state}")
                    _log(f"[SYNTHIO] Post-release envelope value: {env_value:.3f}")
                except Exception as e:
                    _log(f"[ERROR] Failed to release synthio note: {str(e)}")
            
            _log(f"Voice released successfully:")
            _log(f"  channel={channel}")
            _log(f"  note={note}")
            return voice
            
        _log(f"No voice found to release:")
        _log(f"  channel={channel}")
        _log(f"  note={note}")
        return None
    
    def cleanup_voices(self):
        """Remove completed voices after grace period"""
        current_time = time.monotonic()
        for key in list(self.active_notes.keys()):
            note = self.active_notes[key]
            if not note.active and (current_time - note.release_time) > 0.5:
                if self.synthio_synth and note.synth_note:
                    # Check final note state before cleanup
                    try:
                        env_state, env_value = self.synthio_synth.note_info(note.synth_note)
                        _log(f"[SYNTHIO] Final note state before cleanup:")
                        _log(f"[SYNTHIO]   Note ID: {id(note.synth_note)}")
                        _log(f"[SYNTHIO]   Envelope State: {env_state}")
                        _log(f"[SYNTHIO]   Envelope Value: {env_value:.3f}")
                    except Exception as e:
                        _log(f"[SYNTHIO] Note already removed by synthio (ID: {id(note.synth_note)})")
                
                del self.active_notes[key]
                _log(f"Removed inactive voice:")
                _log(f"  channel={key[0]}")
                _log(f"  note={key[1]}")
