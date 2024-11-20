"""
Synthesis Module

Provides core synthesis parameter manipulation for the voice management system.
Currently implements piano functionality, with more features to be added later.

Key Features:
- Waveform generation for triangle wave
- Note parameter modulation for frequency and amplitude
"""

import array
import math

class WaveformManager:
    """Creates and manages waveforms for synthesis"""
    def __init__(self):
        self.waveforms = {}
        
    def create_waveform(self, config):
        """Create waveform from configuration"""
        if not isinstance(config, dict):
            return None
            
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
            print(f"[ERROR] Failed to create waveform: {str(e)}")
            return None
            
    def get_waveform(self, name, config=None):
        """Get or create waveform by name"""
        if name in self.waveforms:
            return self.waveforms[name]
            
        if config:
            waveform = self.create_waveform(config)
            if waveform:
                self.waveforms[name] = waveform
                return waveform
                
        return None

class Synthesis:
    """Core synthesis parameter manipulation"""
    def __init__(self):
        self.waveform_manager = WaveformManager()
            
    def update_note(self, note, param_id, value):
        """Update note parameter"""
        if not note:
            return False
            
        try:
            # Only implement piano parameters for now
            # More parameters will be added as needed
            if param_id == 'frequency':
                note.frequency = float(value)
                return True
            elif param_id == 'amplitude':
                note.amplitude = float(value)
                return True
            return False
            
        except Exception as e:
            print(f"[ERROR] Failed to update note parameter: {str(e)}")
            return False
