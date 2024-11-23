"""
Synthesis Module

Handles parameter manipulation and waveform generation for synthio notes.
Provides calculations needed by voice modules to control synthesis.
"""
import sys
import array
import math
import synthio
from constants import SYNTH_DEBUG

def _log(message, module="SYNTH"):
    """Enhanced logging for synthesis operations"""
    if not SYNTH_DEBUG:
        return
        
    GREEN = "\033[32m"  # Green for synthesis operations
    RED = "\033[31m"    # Red for errors
    RESET = "\033[0m"
    
    color = RED if "[ERROR]" in str(message) else GREEN
    print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class WaveformManager:
    """Creates and manages waveforms for synthesis"""
    def __init__(self):
        self.waveforms = {}
        _log("WaveformManager initialized")
        
    def create_triangle_wave(self, config):
        """Create triangle waveform from configuration"""
        try:
            size = int(config['size'])  # Ensure size is an integer
            amplitude = int(config['amplitude'])  # Ensure amplitude is an integer
            
            # Use double quotes for typecode in CircuitPython
            samples = array.array("h", [0] * size)
            half = size // 2
            
            # Generate triangle wave with explicit integer conversion
            for i in range(size):
                if i < half:
                    value = (i / half) * 2 - 1
                else:
                    value = 1 - ((i - half) / half) * 2
                # Ensure integer conversion for array values
                samples[i] = int(round(value * amplitude))
                    
            _log(f"Created triangle wave: size={size}, amplitude={amplitude}")
            return samples
            
        except Exception as e:
            _log(f"[ERROR] Failed to create waveform: {str(e)}")
            return None
            
    def get_waveform(self, wave_type, config=None):
        """Get or create waveform by type"""
        try:
            if not config:
                _log("[ERROR] No configuration provided for waveform")
                return None
                
            cache_key = f"{wave_type}_{config.get('size', 0)}"
            
            if cache_key in self.waveforms:
                _log(f"Retrieved cached waveform: {cache_key}")
                return self.waveforms[cache_key]
                
            if wave_type == 'triangle':
                waveform = self.create_triangle_wave(config)
                if waveform:
                    self.waveforms[cache_key] = waveform
                    _log(f"Created and cached triangle waveform: size={config['size']}")
                    return waveform
                    
            _log(f"[ERROR] Failed to get/create waveform: {wave_type}")
            return None
        except Exception as e:
            _log(f"[ERROR] Failed in get_waveform: {str(e)}")
            return None

class Synthesis:
    """Core synthesis parameter processing"""
    def __init__(self, synthio_synth=None):
        self.waveform_manager = WaveformManager()
        self.synthio_synth = synthio_synth
        _log("Synthesis engine initialized")
            
    def create_note(self, frequency, envelope_params=None):
        """Create a synthio note with the given frequency and envelope parameters
        
        Args:
            frequency: Base frequency in Hz
            envelope_params: Dictionary of envelope parameters
            
        Returns:
            synthio.Note: The created note
        """
        try:
            # Create envelope if parameters provided
            envelope = None
            if envelope_params:
                envelope = synthio.Envelope(
                    attack_time=max(0.001, float(envelope_params.get('attack_time', 0.001))),
                    attack_level=float(envelope_params.get('attack_level', 1.0)),
                    decay_time=max(0.001, float(envelope_params.get('decay_time', 0.001))),
                    sustain_level=float(envelope_params.get('sustain_level', 0.0)),
                    release_time=max(0.001, float(envelope_params.get('release_time', 0.001)))
                )
                _log(f"Created envelope with params: {envelope_params}")
            
            # Create note with envelope
            note = synthio.Note(
                frequency=float(frequency),
                envelope=envelope
            )
            _log(f"Created note with frequency {frequency}")
            return note
            
        except Exception as e:
            _log(f"[ERROR] Failed to create note: {str(e)}")
            return None

    def update_note(self, note, param_id, value):
        """Update synthio note parameter
        
        Args:
            note: synthio.Note instance
            param_id: Parameter identifier (frequency, amplitude, etc)
            value: New parameter value (pre-normalized by router)
            
        Returns:
            bool: True if parameter was updated successfully
        """
        if not note:
            _log("[ERROR] No note provided for update")
            return False
            
        try:
            _log(f"Updating note parameter: {param_id}={value}")
            
            # Handle basic parameters
            if param_id == 'frequency':
                note.frequency = float(value)
                _log(f"Set frequency: {value}")
                return True
                
            elif param_id == 'amplitude':
                note.amplitude = float(value)
                _log(f"Set amplitude: {value}")
                return True
                
            elif param_id == 'bend':
                note.bend = float(value)
                _log(f"Set bend: {value}")
                return True
                
            elif param_id == 'waveform':
                try:
                    # If value is already a waveform array, use it directly
                    if isinstance(value, array.array):
                        note.waveform = value
                        _log("Set waveform from array")
                        return True
                        
                    # Otherwise, expect a configuration dictionary
                    if not isinstance(value, dict):
                        _log("[ERROR] Expected waveform configuration dictionary")
                        return False
                        
                    wave_type = value.get('type')
                    if not wave_type:
                        _log("[ERROR] No waveform type specified")
                        return False
                        
                    # Create waveform using waveform_manager
                    waveform = self.waveform_manager.get_waveform(wave_type, value)
                    if waveform and isinstance(waveform, array.array):
                        note.waveform = waveform
                        _log(f"Set waveform: type={wave_type}")
                        return True
                        
                    _log("[ERROR] Invalid waveform generated")
                    return False
                except Exception as e:
                    _log(f"[ERROR] Failed to set waveform: {str(e)}")
                    return False
                    
            # Handle envelope parameters
            elif param_id.startswith('envelope_'):
                try:
                    # Get current envelope parameters
                    current_envelope = note.envelope
                    if not current_envelope:
                        _log("[ERROR] Note has no envelope")
                        return False
                        
                    # Get current parameter values
                    params = {
                        'attack_time': current_envelope.attack_time,
                        'attack_level': current_envelope.attack_level,
                        'decay_time': current_envelope.decay_time,
                        'sustain_level': current_envelope.sustain_level,
                        'release_time': current_envelope.release_time
                    }
                    
                    # Update specific parameter
                    param_name = param_id.split('envelope_')[1]
                    params[param_name] = max(0.001, float(value)) if 'time' in param_name else float(value)
                    
                    # Create new envelope with updated parameters
                    note.envelope = synthio.Envelope(**params)
                    _log(f"Updated envelope {param_name}: {value}")
                    return True
                    
                except Exception as e:
                    _log(f"[ERROR] Failed to update envelope: {str(e)}")
                    return False
                    
            # Handle filter parameters
            elif param_id.startswith('filter_'):
                if not self.synthio_synth:
                    _log("[ERROR] No synthesizer available for filter creation")
                    return False
                    
                current_filter = getattr(note, 'filter', None)
                current_freq = getattr(current_filter, 'frequency', 20000)
                current_q = getattr(current_filter, 'Q', 0.707)
                
                if param_id == 'filter_frequency':
                    note.filter = self.synthio_synth.low_pass_filter(
                        frequency=float(value),
                        Q=current_q
                    )
                    _log(f"Updated filter frequency: {value}")
                    return True
                    
                elif param_id == 'filter_resonance':
                    note.filter = self.synthio_synth.low_pass_filter(
                        frequency=current_freq,
                        Q=float(value)
                    )
                    _log(f"Updated filter resonance: {value}")
                    return True
                    
            _log(f"[ERROR] Unhandled parameter: {param_id}")
            return False
            
        except Exception as e:
            _log(f"[ERROR] Failed to update {param_id}: {str(e)}")
            return False
