"""
Synthesis Module

Handles parameter manipulation and waveform generation for synthio notes.
Provides calculations needed by voice modules to control synthesis.
"""

import array
import math

def _log(message):
    """Basic logging for synthesis operations"""
    print(f"[SYNTH] {message}", file=sys.stderr)

class WaveformManager:
    """Creates and manages waveforms for synthesis"""
    def __init__(self):
        self.waveforms = {}
        
    def create_triangle_wave(self, config):
        """Create triangle waveform from configuration"""
        try:
            size = config['size']
            amplitude = config['amplitude']
            
            samples = array.array('h', [0] * size)
            half = size // 2
            
            # Generate triangle wave
            for i in range(size):
                if i < half:
                    value = (i / half) * 2 - 1
                else:
                    value = 1 - ((i - half) / half) * 2
                samples[i] = int(value * amplitude)
                    
            return samples
            
        except Exception as e:
            _log(f"[ERROR] Failed to create waveform: {str(e)}")
            return None
            
    def get_waveform(self, wave_type, config=None):
        """Get or create waveform by type"""
        cache_key = f"{wave_type}_{config.get('size', 0)}"
        
        if cache_key in self.waveforms:
            return self.waveforms[cache_key]
            
        if wave_type == 'triangle' and config:
            waveform = self.create_triangle_wave(config)
            if waveform:
                self.waveforms[cache_key] = waveform
                _log(f"Created triangle waveform size={config['size']}")
                return waveform
                
        return None

class Synthesis:
    """Core synthesis parameter processing"""
    def __init__(self):
        self.waveform_manager = WaveformManager()
            
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
            return False
            
        try:
            # Handle basic parameters
            if param_id == 'frequency':
                note.frequency = float(value)
                return True
                
            elif param_id == 'amplitude':
                note.amplitude = float(value)
                return True
                
            # Handle filter parameters    
            elif hasattr(note, 'filter'):
                if param_id == 'frequency':
                    note.filter.frequency = float(value)
                    return True
                    
                elif param_id == 'resonance':
                    note.filter.q = float(value)  # Q factor for resonance
                    return True
                    
            return False
            
        except Exception as e:
            _log(f"[ERROR] Failed to update {param_id}: {str(e)}")
            return False