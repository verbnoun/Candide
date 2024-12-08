"""Low-level synthesis module containing waveform generation and morphing functionality."""

import array
import sys
import math
from constants import STATIC_WAVEFORM_SAMPLES, MORPHED_WAVEFORM_SAMPLES
from logging import log, TAG_MODU

# Cache for pre-computed waveforms
_waveform_cache = {}
_morphed_waveform_cache = {}  # Cache for morphed waveforms

def get_cached_waveform(waveform_type):
    """Get or create a waveform from cache."""
    if waveform_type not in _waveform_cache:
        _waveform_cache[waveform_type] = create_waveform(waveform_type)
        log(TAG_MODU, f"Created and cached {waveform_type} waveform")
    return _waveform_cache[waveform_type]

def create_waveform(waveform_type):
    """Create a waveform buffer based on type."""
    samples = STATIC_WAVEFORM_SAMPLES
    buffer = array.array('h')
    
    if waveform_type == 'sine':
        for i in range(samples):
            value = int(32767 * math.sin(2 * math.pi * i / samples))
            buffer.append(value)
    elif waveform_type == 'square':
        half_samples = samples // 2
        buffer.extend([32767] * half_samples)
        buffer.extend([-32767] * (samples - half_samples))
    elif waveform_type == 'saw':
        for i in range(samples):
            value = int(32767 * (2 * i / samples - 1))
            buffer.append(value)
    elif waveform_type == 'triangle':
        quarter_samples = samples // 4
        for i in range(samples):
            pos = (4 * i) / samples
            if pos < 1:
                value = pos
            elif pos < 3:
                value = 1 - (pos - 1)
            else:
                value = -1 + (pos - 3)
            buffer.append(int(32767 * value))
    else:
        raise ValueError("Invalid waveform type: " + waveform_type)
    
    return buffer

class WaveformMorph:
    """Handles pre-calculated morphed waveforms for MIDI control."""
    def __init__(self, name, waveform_sequence=None):
        self.name = name
        self.waveform_sequence = waveform_sequence or ['sine', 'triangle', 'square', 'saw']
        self.lookup_table = []  # Will be 128 morphed waveforms
        self._build_lookup()
        log(TAG_MODU, f"Created waveform morph: {name} sequence: {'-'.join(self.waveform_sequence)}")
        
    def _build_lookup(self):
        """Build lookup table of 128 morphed waveforms for MIDI control."""
        cache_key = '-'.join(self.waveform_sequence)
        if cache_key in _morphed_waveform_cache:
            self.lookup_table = _morphed_waveform_cache[cache_key]
            log(TAG_MODU, f"Using cached morph table for {cache_key}")
            return
            
        # Get sample length from first waveform
        first_wave = get_cached_waveform(self.waveform_sequence[0])
        samples = MORPHED_WAVEFORM_SAMPLES
        
        # Pre-calculate all possible morphed waveforms
        num_transitions = len(self.waveform_sequence) - 1
        
        # Log sample values for debugging
        log(TAG_MODU, f"Building morph table for {self.name}:")
        log(TAG_MODU, f"  0: {self.waveform_sequence[0]}")
        log(TAG_MODU, f" 64: Between {self.waveform_sequence[len(self.waveform_sequence)//2-1]} and {self.waveform_sequence[len(self.waveform_sequence)//2]}")
        log(TAG_MODU, f"127: {self.waveform_sequence[-1]}")
        
        # Create array to hold all morphed waveforms
        self.lookup_table = []
        
        for midi_value in range(128):
            # Convert MIDI value to morph position
            morph_position = midi_value / 127.0
            
            # Scale position to total number of transitions
            scaled_pos = morph_position * num_transitions
            transition_index = int(scaled_pos)
            
            # Clamp to valid range
            if transition_index >= num_transitions:
                self.lookup_table.append(get_cached_waveform(self.waveform_sequence[-1]))
                continue
                
            # Get the two waveforms to blend
            waveform1 = get_cached_waveform(self.waveform_sequence[transition_index])
            waveform2 = get_cached_waveform(self.waveform_sequence[transition_index + 1])
            
            # Calculate blend amount within this transition
            t = scaled_pos - transition_index
            
            # Create morphed buffer
            morphed = array.array('h')
            for i in range(samples):
                # Scale indices for potentially different sample counts
                idx1 = (i * len(waveform1)) // samples
                idx2 = (i * len(waveform2)) // samples
                value = int(waveform1[idx1] * (1-t) + waveform2[idx2] * t)
                morphed.append(value)
                
            self.lookup_table.append(morphed)
            
        # Cache the computed morph table
        _morphed_waveform_cache[cache_key] = self.lookup_table
        log(TAG_MODU, f"Cached morph table for {cache_key}")
    
    def get_waveform(self, midi_value):
        """Get pre-calculated morphed waveform for MIDI value."""
        if not 0 <= midi_value <= 127:
            log(TAG_MODU, f"Invalid MIDI value {midi_value} for {self.name}", is_error=True)
            raise ValueError(f"MIDI value must be between 0 and 127, got {midi_value}")
        return self.lookup_table[midi_value]

def create_morphed_waveform(morph_position, waveform_sequence=None):
    """
    Create a morphed waveform based on position and sequence.
    
    Args:
        morph_position: Value 0-1 representing position in morph sequence
        waveform_sequence: List of waveform types to morph between.
                         Defaults to ['sine', 'triangle', 'square', 'saw']
    """
    if waveform_sequence is None:
        waveform_sequence = ['sine', 'triangle', 'square', 'saw']
    
    # Calculate which waveforms to blend between
    num_transitions = len(waveform_sequence) - 1
    if num_transitions == 0:
        return get_cached_waveform(waveform_sequence[0])
        
    # Scale position to total number of transitions
    scaled_pos = morph_position * num_transitions
    transition_index = int(scaled_pos)
    
    # Clamp to valid range
    if transition_index >= num_transitions:
        return get_cached_waveform(waveform_sequence[-1])
    
    # Get the two waveforms to blend
    waveform1 = get_cached_waveform(waveform_sequence[transition_index])
    waveform2 = get_cached_waveform(waveform_sequence[transition_index + 1])
    
    # Calculate blend amount within this transition
    t = scaled_pos - transition_index
    
    # Create morphed buffer
    samples = MORPHED_WAVEFORM_SAMPLES
    morphed = array.array('h')
    for i in range(samples):
        # Scale indices for potentially different sample counts
        idx1 = (i * len(waveform1)) // samples
        idx2 = (i * len(waveform2)) // samples
        value = int(waveform1[idx1] * (1-t) + waveform2[idx2] * t)
        morphed.append(value)
    
    log(TAG_MODU, f"Created morphed waveform at position {morph_position} between {waveform_sequence[transition_index]} and {waveform_sequence[transition_index + 1]}")
    return morphed
