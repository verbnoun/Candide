"""
Advanced Voice Management System for Synthesizer

Handles voice lifecycle, parameter routing, and sound generation.
"""

import time
import sys
import synthio
from fixed_point_math import FixedPoint
from constants import VOICES_DEBUG, SAMPLE_RATE
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
        if "rejected" in str(message):
            color = DARK_GRAY
        elif "[ERROR]" in str(message):
            color = RED
        elif "[SYNTHIO]" in str(message):
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
    def __init__(self, source_id, target_id, processing, global_value_getter=None):
        _log(f"Creating Route:")
        _log(f"  Source: {source_id}")
        _log(f"  Target: {target_id}")
        _log(f"  Processing: {processing}")
        
        self.source_id = source_id
        self.target_id = target_id
        self.amount = FixedPoint.from_float(processing.get('amount', 1.0))
        self.curve = processing.get('curve', 'linear')
        self.global_value_getter = global_value_getter
        
        # Extract range configuration
        range_config = processing.get('range', {})
        self.in_min = range_config.get('in_min', 0)
        self.in_max = range_config.get('in_max', 127)
        self.out_min = FixedPoint.from_float(range_config.get('out_min', 0.0))
        self.out_max = FixedPoint.from_float(range_config.get('out_max', 1.0))
        
    def process_value(self, value):
        """Process input value through configured transformations."""
        _log(f"Processing route value: source={self.source_id}, target={self.target_id}, input={value}")
        
        # Check for global value if no input value provided
        if value is None and self.global_value_getter:
            # Try to get global value based on source_id
            global_key = self.source_id.replace('.', '.')
            value = self.global_value_getter(global_key)
            _log(f"Retrieved global value for {global_key}: {value}")
        
        # If still no value, return None
        if value is None:
            _log(f"[ERROR] No value found for source {self.source_id}")
            return None
        
        # Range mapping
        if not isinstance(value, FixedPoint):
            value = FixedPoint.from_float(float(value))
            
        # Normalize input to 0-1 range
        if self.in_max != self.in_min:
            value = FixedPoint.from_float(
                (float(value) - self.in_min) / (self.in_max - self.in_min)
            )
        
        # Apply curve
        if self.curve == 'exponential':
            value = FixedPoint.multiply(value, value)
        elif self.curve == 'logarithmic':
            value = FixedPoint.ONE - FixedPoint.multiply(FixedPoint.ONE - value, FixedPoint.ONE - value)
        elif self.curve == 's_curve':
            x2 = FixedPoint.multiply(value, value)
            x3 = FixedPoint.multiply(x2, value)
            value = FixedPoint.multiply(x2, FixedPoint.from_float(3.0)) - \
                   FixedPoint.multiply(x3, FixedPoint.from_float(2.0))
            
        # Scale to output range
        range_size = self.out_max - self.out_min
        value = self.out_min + FixedPoint.multiply(value, range_size)
        
        # Apply amount
        value = FixedPoint.multiply(value, self.amount)
        
        _log(f"Route processed: value={value}")
        return value

class NoteState:
    """
    Comprehensive note state management with advanced routing capabilities.
    Handles per-note parameter tracking and modulation.
    """
    def __init__(self, channel, note, velocity, config, synthesis, routes, global_value_getter=None):
        _log(f"Creating NoteState:")
        _log(f"  channel={channel}")
        _log(f"  note={note}")
        _log(f"  velocity={velocity}")
        
        self.channel = channel
        self.note = note
        self.active = True
        self.creation_time = time.monotonic()
        self.synthesis = synthesis
        self.config = config
        
        # Update routes with global value getter
        self.routes = [
            Route(
                route.source_id, 
                route.target_id, 
                route.processing, 
                global_value_getter
            ) for route in routes
        ]
        
        # Initialize core parameters
        velocity_fixed = FixedPoint.normalize_midi_value(velocity)
        note_fixed = FixedPoint.from_float(float(note))
        freq_fixed = FixedPoint.midi_note_to_fixed(note)
        
        self.parameter_values = {
            'amplitude': velocity_fixed,
            'note_on.note': note_fixed,
            'note_on.velocity': velocity_fixed,
            'frequency': freq_fixed
        }
        
        _log("Initialized parameter values:")
        for key, value in self.parameter_values.items():
            _log(f"  {key}: {value} (float: {FixedPoint.to_float(value)})")
        
        # Create synthio Note
        self.synth_note = self._create_synthio_note()
        
    def _create_synthio_note(self):
        """Create synthio Note object from config"""
        try:
            _log("[SYNTHIO] Creating Note object")
            
            if 'oscillator' not in self.config:
                _log("[ERROR] No oscillator configuration found")
                return None
                
            osc_config = self.config['oscillator']
            waveform_config = osc_config.get('waveform', {})
            
            # Get waveform
            waveform = self.synthesis.waveform_manager.get_waveform(
                waveform_config.get('type', 'triangle'),
                waveform_config
            )
            if not waveform:
                _log("[ERROR] Failed to get waveform")
                return None
            
            # Create note parameters
            note_params = {
                'frequency': FixedPoint.to_float(self.parameter_values['frequency']),
                'amplitude': FixedPoint.to_float(self.parameter_values['amplitude']),
                'waveform': waveform
            }
            
            # Only add envelope if it exists in config
            if 'amplifier' in self.config and 'envelope' in self.config['amplifier']:
                env_config = self.config['amplifier']['envelope']
                
                # Extract envelope parameters only if they exist in config
                env_params = {}
                
                if 'attack' in env_config:
                    attack = env_config['attack']
                    if 'time' in attack and 'value' in attack['time']:
                        env_params['attack_time'] = float(attack['time']['value'])
                    if 'level' in attack and 'value' in attack['level']:
                        env_params['attack_level'] = float(attack['level']['value'])
                        
                if 'decay' in env_config:
                    decay = env_config['decay']
                    if 'time' in decay and 'value' in decay['time']:
                        env_params['decay_time'] = float(decay['time']['value'])
                        
                if 'sustain' in env_config:
                    sustain = env_config['sustain']
                    if 'level' in sustain and 'value' in sustain['level']:
                        env_params['sustain_level'] = float(sustain['level']['value'])
                        
                if 'release' in env_config:
                    release = env_config['release']
                    if 'time' in release and 'value' in release['time']:
                        env_params['release_time'] = float(release['time']['value'])
                
                # Only create envelope if we have parameters
                if env_params:
                    _log("[SYNTHIO] Creating envelope with params:")
                    _log(env_params)
                    note_params['envelope'] = synthio.Envelope(**env_params)
            
            # Create note
            note = synthio.Note(**note_params)
            
            _log(f"[SYNTHIO] Created Note object:")
            _log(f"[SYNTHIO]   Frequency: {note.frequency:.1f}Hz")
            _log(f"[SYNTHIO]   Amplitude: {note.amplitude:.3f}")
            _log(f"[SYNTHIO]   Has Envelope: {'envelope' in note_params}")
            
            return note
            
        except Exception as e:
            _log(f"[ERROR] Failed to create synthio Note: {str(e)}")
            return None
    
    def handle_value_change(self, source_id, value):
        """Process value changes through configured routes."""
        _log(f"Handling value change: source={source_id}, value={value}")
        
        # Store source value
        self.parameter_values[source_id] = value
        
        # Process through routes
        for route in self.routes:
            if route.source_id == source_id:
                processed_value = route.process_value(value)
                target_id = route.target_id
                
                # Store processed value
                self.parameter_values[target_id] = processed_value
                
                # Update synthio note if needed
                if self.synth_note:
                    if target_id == 'oscillator.frequency':
                        self.synth_note.frequency = FixedPoint.to_float(processed_value)
                    elif target_id == 'amplifier.gain':
                        self.synth_note.amplitude = FixedPoint.to_float(processed_value)
                
                _log(f"Route processed: target={target_id}, value={processed_value}")
    
    def handle_release(self):
        """Process note release"""
        _log(f"Handling note release: channel={self.channel}, note={self.note}")
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            _log("Note release completed")

class VoiceManager:
    """
    Manages voice lifecycle, allocation, and global voice state.
    """
    def __init__(self, output_manager, sample_rate=SAMPLE_RATE):
        _log("Initializing VoiceManager")
        self.active_notes = {}
        self.pending_values = {}
        self.current_config = None
        self.routes = []
        self.global_value_getter = None  # New attribute for global value retrieval
        
        # Create synthesis instance
        self.synthesis = Synthesis()
        
        try:
            self.synthio_synth = synthio.Synthesizer(
                sample_rate=sample_rate,
                channel_count=2
            )
            _log("[SYNTHIO] Initialized synthesizer")
            _log(f"[SYNTHIO] Sample Rate: {self.synthio_synth.sample_rate}")
            
            # Attach synthesizer to output manager
            if output_manager and hasattr(output_manager, 'attach_synthesizer'):
                output_manager.attach_synthesizer(self.synthio_synth)
                _log("[SYNTHIO] Attached synthesizer to output manager")
                
        except Exception as e:
            _log(f"[ERROR] Failed to initialize synthio synthesizer: {str(e)}")
            self.synthio_synth = None
    
    def set_global_value_getter(self, getter):
        """
        Set a function to retrieve global values.
        
        Args:
            getter (callable): Function that takes a source key and returns a value
        """
        self.global_value_getter = getter
        _log(f"Global value getter set: {getter}")
    
    def set_config(self, config):
        """Update current instrument configuration and pre-process routes"""
        _log(f"Setting instrument configuration:")
        _log(config)
        
        if not isinstance(config, dict):
            _log("[ERROR] VoiceManager config must be a dictionary")
            raise ValueError("VoiceManager config must be a dictionary")
        
        self.current_config = config
        self.routes = []
        
        # Pre-process routes from patches
        patches = config.get('patches', [])
        for patch in patches:
            source = patch.get('source', {})
            destination = patch.get('destination', {})
            processing = patch.get('processing', {})
            
            source_id = f"{source['id']}.{source['attribute']}" if 'attribute' in source else source['id']
            target_id = f"{destination['id']}.{destination['attribute']}" if 'attribute' in destination else destination['id']
            
            route = Route(source_id, target_id, processing, self.global_value_getter)
            self.routes.append(route)
            
        _log(f"Processed {len(self.routes)} routes from configuration")
    
    def store_pending_value(self, channel, source_id, value, control_name=None):
        """Store values that arrive before note-on event."""
        key = (channel, source_id)
        self.pending_values[key] = (value, control_name)
        _log(f"Stored pending value: channel={channel}, source_id={source_id}, value={value}")
    
    def get_pending_values(self, channel):
        """Retrieve and clear pending values for a specific channel."""
        values = {}
        for (c, source_id), (value, control_name) in list(self.pending_values.items()):
            if c == channel:
                values[source_id] = (value, control_name)
                del self.pending_values[(c, source_id)]
        return values
    
    def allocate_voice(self, channel, note, velocity):
        """Create a new voice for a note"""
        _log(f"Attempting to allocate voice:")
        _log(f"  channel={channel}")
        _log(f"  note={note}")
        _log(f"  velocity={velocity}")
        
        if not self.current_config:
            _log("[ERROR] No current configuration available")
            return None
        
        try:
            # Create note state with pre-processed routes and global value getter
            note_state = NoteState(
                channel, note, velocity,
                self.current_config, self.synthesis,
                self.routes,
                self.global_value_getter
            )
            
            # Store voice
            self.active_notes[(channel, note)] = note_state
            
            # Press note if synthesizer available
            if self.synthio_synth and note_state.synth_note:
                self.synthio_synth.press(note_state.synth_note)
                _log(f"[SYNTHIO] Pressed note {note}")
            
            _log(f"Voice allocated successfully")
            return note_state
            
        except Exception as e:
            _log(f"[ERROR] Voice allocation failed: {str(e)}")
            return None
    
    def get_voice(self, channel, note):
        """Retrieve an active voice."""
        return self.active_notes.get((channel, note))
    
    def release_voice(self, channel, note):
        """Handle voice release"""
        voice = self.get_voice(channel, note)
        if voice:
            voice.handle_release()
            if self.synthio_synth and voice.synth_note:
                self.synthio_synth.release(voice.synth_note)
            return voice
        return None
    
    def cleanup_voices(self):
        """Remove completed voices after grace period"""
        current_time = time.monotonic()
        for key in list(self.active_notes.keys()):
            note = self.active_notes[key]
            if not note.active and (current_time - note.release_time) > 0.5:
                del self.active_notes[key]
                _log(f"Removed inactive voice: channel={key[0]}, note={key[1]}")
