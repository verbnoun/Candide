"""
Advanced Voice Management System for Synthesizer with modular architecture.
Handles voice lifecycle, parameter routing, and sound generation with module separation.
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
    """Conditional logging function that respects VOICES_DEBUG flag."""
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
    def __init__(self, source_id, target_id, processing=None):
        processing = processing or {}
        
        _log(f"Creating Route:")
        _log(f"  Source: {source_id}")
        _log(f"  Target: {target_id}")
        _log(f"  Processing: {processing}")
        
        self.source_id = source_id
        self.target_id = target_id
        
        # Safely extract processing parameters with defaults
        self.amount = FixedPoint.from_float(processing.get('amount', 1.0))
        self.curve = processing.get('curve', 'linear')
        
        # Extract range configuration with robust defaults
        range_config = processing.get('range', {})
        self.in_min = range_config.get('in_min', 0)
        self.in_max = range_config.get('in_max', 127)
        self.out_min = FixedPoint.from_float(range_config.get('out_min', 0.0))
        self.out_max = FixedPoint.from_float(range_config.get('out_max', 1.0))
        
        self.processing = processing
        
    def process_value(self, value):
        """Process input value through configured transformations."""
        _log(f"Processing route value: source={self.source_id}, target={self.target_id}, input={value}")
        
        if value is None:
            _log(f"[ERROR] No value provided for source {self.source_id}")
            return None
        
        # Special handling for envelope parameters - keep as float
        if 'envelope' in self.target_id:
            if self.in_max != self.in_min:
                value = (float(value) - self.in_min) / (self.in_max - self.in_min)
            value = value * (float(self.out_max) - float(self.out_min)) + float(self.out_min)
            value = value * float(self.amount)
            _log(f"Envelope parameter processed: value={value}")
            return value
            
        if not isinstance(value, FixedPoint):
            value = FixedPoint.from_float(float(value))
            
        if self.in_max != self.in_min:
            value = FixedPoint.from_float(
                (float(value) - self.in_min) / (self.in_max - self.in_min)
            )
        
        if self.curve == 'exponential':
            value = FixedPoint.multiply(value, value)
        elif self.curve == 'logarithmic':
            value = FixedPoint.ONE - FixedPoint.multiply(FixedPoint.ONE - value, FixedPoint.ONE - value)
        elif self.curve == 's_curve':
            x2 = FixedPoint.multiply(value, value)
            x3 = FixedPoint.multiply(x2, value)
            value = FixedPoint.multiply(x2, FixedPoint.from_float(3.0)) - \
                   FixedPoint.multiply(x3, FixedPoint.from_float(2.0))
            
        range_size = self.out_max - self.out_min
        value = self.out_min + FixedPoint.multiply(value, range_size)
        value = FixedPoint.multiply(value, self.amount)
        
        _log(f"Route processed: value={value}")
        return value

class BaseModuleState:
    """Base class for all module states"""
    def __init__(self, name):
        self.name = name
        self.parameter_values = {}
        
    def set_parameter(self, param_name, value):
        """Set parameter with logging"""
        self.parameter_values[param_name] = value
        _log(f"{self.name}: Set {param_name} = {value}")
        
    def get_parameter(self, param_name, default=None):
        return self.parameter_values.get(param_name, default)

class EnvelopeState(BaseModuleState):
    """Independent envelope state management"""
    def __init__(self, config=None):
        super().__init__("Envelope")
        self.config = config or {}
        self.params = {
            'attack': {'time': 0.1, 'level': 1.0},
            'decay': {'time': 0.05},
            'sustain': {'level': 0.8},
            'release': {'time': 0.2}
        }
        
    def update_parameter(self, stage, param, value):
        """Update envelope parameter"""
        if stage in self.params and param in self.params[stage]:
            self.params[stage][param] = float(value)
            _log(f"Envelope {stage}.{param} updated to {value}")
            return True
        return False
        
    def create_synthio_envelope(self):
        """Create synthio Envelope object from current state"""
        try:
            env_params = {
                'attack_time': self.params['attack']['time'],
                'attack_level': self.params['attack']['level'],
                'decay_time': self.params['decay']['time'],
                'sustain_level': self.params['sustain']['level'],
                'release_time': self.params['release']['time']
            }
            return synthio.Envelope(**env_params)
        except Exception as e:
            _log(f"[ERROR] Failed to create envelope: {str(e)}")
            return None

class OscillatorState(BaseModuleState):
    """Manages oscillator parameters and waveform"""
    def __init__(self, synthesis):
        super().__init__("Oscillator")
        self.synthesis = synthesis
        self.waveform = None
        self.set_parameter('frequency', FixedPoint.from_float(440.0))
        
    def update_frequency(self, value):
        """Update frequency with proper conversion"""
        if isinstance(value, FixedPoint):
            self.set_parameter('frequency', value)
        else:
            self.set_parameter('frequency', FixedPoint.from_float(float(value)))
            
    def configure_waveform(self, config):
        """Setup waveform from config"""
        try:
            waveform_config = config.get('waveform', {})
            self.waveform = self.synthesis.waveform_manager.get_waveform(
                waveform_config.get('type', 'triangle'),
                waveform_config
            )
            return bool(self.waveform)
        except Exception as e:
            _log(f"[ERROR] Waveform configuration failed: {str(e)}")
            return False

class FilterState(BaseModuleState):
    """Manages filter parameters and configuration"""
    def __init__(self):
        super().__init__("Filter")
        self.set_parameter('frequency', FixedPoint.from_float(1000.0))
        self.set_parameter('resonance', FixedPoint.from_float(0.707))
        self.set_parameter('type', 'lowpass')
        
    def update_parameter(self, param_name, value):
        """Update filter parameter with type checking"""
        if param_name in ['frequency', 'resonance']:
            if isinstance(value, FixedPoint):
                self.set_parameter(param_name, value)
            else:
                self.set_parameter(param_name, FixedPoint.from_float(float(value)))
        else:
            self.set_parameter(param_name, value)

class AmplifierState(BaseModuleState):
    """Manages amplifier parameters"""
    def __init__(self):
        super().__init__("Amplifier")
        self.set_parameter('gain', FixedPoint.from_float(0.5))
        
    def update_gain(self, value):
        """Update gain with proper conversion"""
        if isinstance(value, FixedPoint):
            self.set_parameter('gain', value)
        else:
            self.set_parameter('gain', FixedPoint.from_float(float(value)))

class NoteState:
    """Manages complete note state using module-specific states"""
    def __init__(self, channel, note, velocity, config, synthesis, routes):
        _log(f"Creating NoteState: channel={channel}, note={note}, velocity={velocity}")
        
        self.channel = channel
        self.note = note
        self.active = True
        self.creation_time = time.monotonic()
        self.routes = [Route(r.source_id, r.target_id, r.processing) for r in routes]
        
        # Initialize module states
        self.oscillator = OscillatorState(synthesis)
        self.filter = FilterState()
        self.amplifier = AmplifierState()
        self.envelope = EnvelopeState()
        
        # Configure from config
        self._configure_from_config(config)
        
        # Set initial values
        self._set_initial_values(note, velocity)
        
        # Create synthio note
        self.synth_note = self._create_synthio_note()
        
    def _configure_from_config(self, config):
        """Apply configuration to all modules"""
        try:
            if 'oscillator' in config:
                self.oscillator.configure_waveform(config['oscillator'])
                
            if 'filter' in config:
                for param, value in config['filter'].get('parameters', {}).items():
                    if 'value' in value:
                        self.filter.update_parameter(param, value['value'])
                        
            if 'amplifier' in config:
                amp_config = config['amplifier']
                if 'envelope' in amp_config:
                    self.envelope = EnvelopeState(amp_config['envelope'])
                    
        except Exception as e:
            _log(f"[ERROR] Configuration failed: {str(e)}")
            
    def _set_initial_values(self, note, velocity):
        """Set initial note parameters"""
        velocity_fixed = FixedPoint.normalize_midi_value(velocity)
        freq_fixed = FixedPoint.midi_note_to_fixed(note)
        
        self.oscillator.update_frequency(freq_fixed)
        self.amplifier.update_gain(velocity_fixed)
        
    def _create_synthio_note(self):
        """Create synthio Note object from current state"""
        try:
            params = {
                'frequency': FixedPoint.to_float(self.oscillator.get_parameter('frequency')),
                'amplitude': FixedPoint.to_float(self.amplifier.get_parameter('gain')),
                'waveform': self.oscillator.waveform
            }
            
            # Add envelope if configured
            env = self.envelope.create_synthio_envelope()
            if env:
                params['envelope'] = env
                
            # Create note
            note = synthio.Note(**params)
            
            _log(f"[SYNTHIO] Created Note: freq={params['frequency']:.1f}Hz, amp={params['amplitude']:.3f}")
            return note
            
        except Exception as e:
            _log(f"[ERROR] Failed to create synthio Note: {str(e)}")
            return None
            
    def handle_value_change(self, source_id, value):
        """Process value changes through configured routes"""
        _log(f"Value change: source={source_id}, value={value}")
        
        # Process through routes
        for route in self.routes:
            if route.source_id == source_id:
                processed_value = route.process_value(value)
                target_id = route.target_id
                
                # Route to appropriate module
                try:
                    module_name, param = target_id.split('.', 1)
                    
                    if module_name == 'oscillator':
                        self.oscillator.update_frequency(processed_value)
                        if self.synth_note:
                            self.synth_note.frequency = FixedPoint.to_float(processed_value)
                            
                    elif module_name == 'filter':
                        self.filter.update_parameter(param, processed_value)
                        if self.synth_note and hasattr(self.synth_note, 'filter'):
                            setattr(self.synth_note.filter, param, FixedPoint.to_float(processed_value))
                        
                    elif module_name == 'amplifier':
                        if 'envelope' in param:
                            _, stage, param_type = param.split('.')
                            self.envelope.update_parameter(stage, param_type, processed_value)
                            if self.synth_note and hasattr(self.synth_note, 'envelope'):
                                setattr(self.synth_note.envelope, f"{stage}_{param_type}", processed_value)
                        else:
                            self.amplifier.update_gain(processed_value)
                            if self.synth_note:
                               self.synth_note.amplitude = FixedPoint.to_float(processed_value)
                               
                except Exception as e:
                   _log(f"[ERROR] Failed to route value: {str(e)}")
   
    def handle_release(self):
        """Process note release"""
        if self.active:
            self.active = False
            self.release_time = time.monotonic()
            _log(f"Note released: channel={self.channel}, note={self.note}")

class VoiceManager:
   """Manages voice lifecycle and module coordination"""
   def __init__(self, output_manager, sample_rate=SAMPLE_RATE):
       _log("Initializing VoiceManager")
       self.active_notes = {}
       self.current_config = None
       self.routes = []
       self.synthesis = Synthesis()
       
       try:
           self.synthio_synth = synthio.Synthesizer(
               sample_rate=sample_rate,
               channel_count=2
           )
           
           if output_manager and hasattr(output_manager, 'attach_synthesizer'):
               output_manager.attach_synthesizer(self.synthio_synth)
               _log("[SYNTHIO] Synthesizer initialized and attached")
               
       except Exception as e:
           _log(f"[ERROR] Synthesizer initialization failed: {str(e)}")
           self.synthio_synth = None
           
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
           
           route = Route(source_id, target_id, processing)
           self.routes.append(route)
           
       _log(f"Processed {len(self.routes)} routes from configuration")
   
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
           # Create note state with pre-processed routes
           note_state = NoteState(
               channel, note, velocity,
               self.current_config, self.synthesis,
               self.routes
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
       """Retrieve an active voice"""
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
    