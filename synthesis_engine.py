"""
Synthesis Engine Module

This module provides advanced waveform generation, filtering, and 
synthesis capabilities for creating complex audio signals.

Key Responsibilities:
- Generate various waveform types (sine, saw, square, triangle, custom)
- Manage waveform creation and storage
- Create and configure audio filters
- Dynamically generate and modify synthesizer notes

Primary Classes:
- WaveformManager: Creates and stores different types of waveforms
  * Supports sine, saw, square, triangle, and custom waveforms
  * Configurable through instrument configuration
  * Generates wavetables for synthesis

- FilterManager: Creates audio filters based on configuration
  * Supports lowpass, highpass, and bandpass filters
  * Configurable filter frequency and resonance

- SynthesisEngine: Central engine for note creation and parameter manipulation
  * Generates notes using configured waveforms
  * Applies filters to notes
  * Dynamically updates note parameters
"""
import array
import math
import synthio
from fixed_point_math import FixedPoint
from synth_constants import Constants

class WaveformManager:
    """Creates and stores waveforms defined in config"""
    def __init__(self, config):
        self.waveforms = {}
        self._process_config(config)
        
    def _process_config(self, config):
        """Create waveforms defined in config"""
        if not config or 'waveforms' not in config:
            return
            
        for name, waveform_def in config['waveforms'].items():
            if 'type' not in waveform_def:
                continue
                
            if Constants.DEBUG:
                print(f"[WAVE] Creating waveform: {name}")
                print(f"      Type: {waveform_def['type']}")
                
            try:
                if waveform_def['type'] == 'sine':
                    self._create_sine(name, waveform_def)
                elif waveform_def['type'] == 'saw':
                    self._create_saw(name, waveform_def)
                elif waveform_def['type'] == 'square':
                    self._create_square(name, waveform_def)
                elif waveform_def['type'] == 'triangle':
                    self._create_triangle(name, waveform_def)
                elif waveform_def['type'] == 'custom':
                    self._create_custom(name, waveform_def)
            except Exception as e:
                print(f"[ERROR] Failed to create waveform {name}: {str(e)}")
                
    def _create_sine(self, name, config):
        """Create sine waveform"""
        size = config.get('size', Constants.WAVE_TABLE_SIZE)
        amp = config.get('amplitude', 32767)
        phase = config.get('phase', 0.0)
        
        samples = array.array('h', [0] * size)
        for i in range(size):
            angle = 2 * math.pi * i / size + phase
            samples[i] = int(math.sin(angle) * amp)
            
        self.waveforms[name] = samples
        
    def _create_saw(self, name, config):
        """Create sawtooth waveform"""
        size = config.get('size', Constants.WAVE_TABLE_SIZE)
        amp = config.get('amplitude', 32767)
        
        samples = array.array('h', [0] * size)
        for i in range(size):
            value = ((i / size) * 2 - 1) * amp
            samples[i] = int(value)
            
        self.waveforms[name] = samples
        
    def _create_square(self, name, config):
        """Create square waveform"""
        size = config.get('size', Constants.WAVE_TABLE_SIZE)
        amp = config.get('amplitude', 32767)
        duty = config.get('duty_cycle', 0.5)
        
        samples = array.array('h', [0] * size)
        duty_point = int(size * duty)
        
        for i in range(size):
            samples[i] = amp if i < duty_point else -amp
            
        self.waveforms[name] = samples
        
    def _create_triangle(self, name, config):
        """Create triangle waveform"""
        size = config.get('size', Constants.WAVE_TABLE_SIZE)
        amp = config.get('amplitude', 32767)
        
        samples = array.array('h', [0] * size)
        half_size = size // 2
        
        for i in range(size):
            if i < half_size:
                value = (i / half_size) * 2 - 1
            else:
                value = 1 - ((i - half_size) / half_size) * 2
            samples[i] = int(value * amp)
            
        self.waveforms[name] = samples
        
    def _create_custom(self, name, config):
        """Create custom waveform from provided samples"""
        if 'samples' not in config:
            return
            
        # Convert to appropriate format
        samples = array.array('h', config['samples'])
        
        # Validate and store
        if len(samples) > 0:
            self.waveforms[name] = samples
            
    def get_waveform(self, name):
        """Get waveform by name"""
        return self.waveforms.get(name)

class FilterManager:
    """Creates filters according to config"""
    def __init__(self, synth):
        self.synth = synth
        self.current_config = None
        
    def create_filter(self, config):
        """Create filter from config definition"""
        if not config or 'type' not in config:
            return None
            
        try:
            self.current_config = config
            filter_type = config['type']
            
            # Get initial parameters through config routes
            frequency = self._get_routed_value('frequency', config)
            resonance = self._get_routed_value('resonance', config)
            
            # Create filter based on type
            if filter_type == 'lowpass':
                return self.synth.low_pass_filter(frequency, resonance)
            elif filter_type == 'highpass':
                return self.synth.high_pass_filter(frequency, resonance)
            elif filter_type == 'bandpass':
                return self.synth.band_pass_filter(frequency, resonance)
                
        except Exception as e:
            print(f"[ERROR] Failed to create filter: {str(e)}")
            
        return None
        
    def _get_routed_value(self, param_name, config):
        """Get parameter value through config routing"""
        if param_name not in config:
            return self._get_default_value(param_name)
            
        param_config = config[param_name]
        
        # Get base value
        value = param_config.get('value', self._get_default_value(param_name))
        
        # Apply any route transformations
        if 'route' in param_config:
            route = param_config['route']
            # Apply route modifiers (scale, offset, etc)
            if 'scale' in route:
                value *= route['scale']
            if 'offset' in route:
                value += route['offset']
                
        return value
        
    def _get_default_value(self, param_name):
        """Get default parameter value"""
        if param_name == 'frequency':
            return 1000  # Default cutoff
        elif param_name == 'resonance':
            return 0.7   # Default Q
        return 0.0

class SynthesisEngine:
    """Config-driven synthesis engine"""
    def __init__(self, synth):
        self.synth = synth
        self.waveform_manager = None
        self.filter_manager = FilterManager(synth)
        self.current_config = None
        
    def configure(self, config):
        """Configure synthesis from config"""
        self.current_config = config
        self.waveform_manager = WaveformManager(config)
        
    def create_note(self, frequency, amplitude=0.0, config_override=None):
        """Create note from configuration and parameters"""
        if not self.current_config:
            return None
            
        try:
            # Use provided config or current
            config = config_override or self.current_config
            
            # Get waveform
            waveform_name = config.get('waveform', 'triangle')
            if not waveform_name:
                if Constants.DEBUG:
                    print("[SYNTH] No waveform specified")
                return None
                
            waveform = self.waveform_manager.get_waveform(waveform_name)
            if not waveform:
                if Constants.DEBUG:
                    print(f"[SYNTH] Waveform not found: {waveform_name}")
                return None
            
            # Get parameter configuration
            param_config = config.get('parameters', {})
            
            # Create envelope
            envelope_config = config.get('envelope', {}).get('stages', {})
            envelope = synthio.Envelope(
                attack_time=envelope_config.get('attack', {}).get('time', {}).get('value', 0.01),
                decay_time=envelope_config.get('decay', {}).get('time', {}).get('value', 0.1),
                release_time=envelope_config.get('release', {}).get('time', {}).get('value', 0.2),
                attack_level=envelope_config.get('attack', {}).get('level', {}).get('value', 1.0),
                sustain_level=envelope_config.get('sustain', {}).get('level', {}).get('value', 0.5)
            )
            
            # Create base note
            note = synthio.Note(
                frequency=frequency,
                waveform=waveform,
                amplitude=amplitude,
                envelope=envelope
            )
            
            # Apply filter if configured
            filter_config = config.get('filter')
            if filter_config:
                note.filter = self.filter_manager.create_filter(filter_config)
                
            if Constants.DEBUG:
                print(f"[SYNTH] Created note:")
                print(f"      Freq: {frequency:.2f}Hz")
                print(f"      Amp: {amplitude:.3f}")
                print(f"      Wave: {waveform_name}")
                print(f"      Envelope: {envelope}")
                print(f"      Filter: {True if note.filter else False}")
                
            return note
            
        except Exception as e:
            print(f"[ERROR] Note creation failed: {str(e)}")
            return None
            
    def update_note_parameters(self, note, params):
        """Update note parameters based on config mapping"""
        if not note or not self.current_config:
            return
            
        try:
            # Get parameter mapping from config
            param_map = self.current_config.get('parameter_mapping', {})
            
            # Update each mapped parameter
            for param_name, param_value in params.items():
                if param_name not in param_map:
                    continue
                    
                # Get synthio parameter name
                synthio_param = param_map[param_name]
                if hasattr(note, synthio_param):
                    setattr(note, synthio_param, param_value)
                    
                    if Constants.DEBUG:
                        print(f"[SYNTH] Updated parameter:")
                        print(f"      Name: {param_name}")
                        print(f"      Value: {param_value:.3f}")
                        
        except Exception as e:
            print(f"[ERROR] Parameter update failed: {str(e)}")
