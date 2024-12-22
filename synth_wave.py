"""Wave and LFO management for synthesizer."""

import synthio
import array
import math
from logging import log, TAG_WAVE, format_value

# Shared waveform cache
_WAVEFORM_CACHE = {}

class WaveManager:
    """Manages waveform creation and manipulation."""
    
    def __init__(self, store=None):
        self.store = store
        
    @staticmethod
    def midi_to_hz(note):
        """Convert MIDI note to frequency in Hz."""
        return synthio.midi_to_hz(note)
        
    def create_waveform(self, waveform_type, samples=64):
        """Create a waveform buffer.
        
        Args:
            waveform_type: Type of waveform ('sine', 'triangle', 'square', 'saw')
            samples: Number of samples in waveform
            
        Returns:
            array.array of signed 16-bit integers
        """
        cache_key = f"{waveform_type}_{samples}"
        if cache_key in _WAVEFORM_CACHE:
            log(TAG_WAVE, f"Using cached {waveform_type} waveform")
            return _WAVEFORM_CACHE[cache_key]
            
        buffer = array.array('h')
        
        try:
            if waveform_type == 'sine':
                for i in range(samples):
                    value = int(32767 * math.sin(2 * math.pi * i / samples))
                    buffer.append(value)
                    
            elif waveform_type == 'triangle':
                quarter = samples // 4
                for i in range(samples):
                    if i < quarter:  # Rising 0 to 1
                        value = i / quarter
                    elif i < 3 * quarter:  # Falling 1 to -1
                        value = 1 - 2 * (i - quarter) / (quarter * 2)
                    else:  # Rising -1 to 0
                        value = -1 + (i - 3 * quarter) / quarter
                    buffer.append(int(32767 * value))
                    
            elif waveform_type == 'square':
                half = samples // 2
                buffer.extend([32767] * half)
                buffer.extend([-32767] * (samples - half))
                
            elif waveform_type == 'saw':
                for i in range(samples):
                    value = int(32767 * (2 * i / samples - 1))
                    buffer.append(value)
                    
            else:
                raise ValueError(f"Unknown waveform type: {waveform_type}")
                
            _WAVEFORM_CACHE[cache_key] = buffer
            log(TAG_WAVE, f"Created {waveform_type} waveform")
            return buffer
            
        except Exception as e:
            log(TAG_WAVE, f"Error creating waveform: {str(e)}", is_error=True)
            raise
            
    def create_morphed_waveform(self, waveform_sequence, morph_position, samples=64):
        """Create a morphed waveform between sequence of waveforms.
        
        Args:
            waveform_sequence: List of waveform types to morph between
            morph_position: Position in morph sequence (0-1)
            samples: Number of samples in output waveform
            
        Returns:
            array.array of morphed waveform
        """
        try:
            num_transitions = len(waveform_sequence) - 1
            if num_transitions == 0:
                return self.create_waveform(waveform_sequence[0], samples)
                
            scaled_pos = morph_position * num_transitions
            transition_index = int(scaled_pos)
            
            if transition_index >= num_transitions:
                return self.create_waveform(waveform_sequence[-1], samples)
            
            # Get or create source waveforms
            waveform1 = self.create_waveform(waveform_sequence[transition_index], samples)
            waveform2 = self.create_waveform(waveform_sequence[transition_index + 1], samples)
            
            # Calculate interpolation factor
            t = scaled_pos - transition_index
            
            # Create morphed waveform
            morphed = array.array('h')
            for i in range(samples):
                value = int(waveform1[i] * (1-t) + waveform2[i] * t)
                morphed.append(value)
            
            log(TAG_WAVE, "Created morphed waveform")
            return morphed
            
        except Exception as e:
            log(TAG_WAVE, f"Error creating morphed waveform: {str(e)}", is_error=True)
            raise
