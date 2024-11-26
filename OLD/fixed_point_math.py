"""
Fixed-Point Mathematics Module

This module provides robust fixed-point arithmetic 
capabilities for high-performance, low-overhead numerical 
computations in the Candide Synthesizer.

Key Responsibilities:
- Implement efficient fixed-point mathematical operations
- Provide precise numerical computations with controlled precision
- Support complex mathematical transformations
- Enable consistent numerical representation across system
- Handle MIDI and audio-specific numerical conversions

Primary Class:
- FixedPoint:
  * Represents fixed-point numerical values
  * Supports arithmetic operations with controlled precision
  * Enables efficient mathematical computations
  * Minimizes floating-point overhead
  * Provides specialized audio and MIDI conversion methods

Key Features:
- Precise numerical representation
- Efficient mathematical operations
- Low computational overhead
- Consistent numerical behavior
- Specialized MIDI and audio conversions
- Robust error handling and bounds checking

Conversion Methods:
- from_float: Convert floating-point to fixed-point
- to_float: Convert fixed-point to floating-point
- normalize_midi_value: Convert MIDI values to normalized range
- normalize_pitch_bend: Convert pitch bend values
- midi_note_to_frequency: Convert MIDI notes to frequencies
"""

import math
from constants import *

class FixedPoint:
    """Fixed-point math utilities for audio calculations"""
    SCALE = FIXED_POINT_SCALE
    MAX_VALUE = FIXED_POINT_MAX_VALUE
    MIN_VALUE = FIXED_POINT_MIN_VALUE
    
    # Pre-calculated common values
    ONE = FIXED_POINT_ONE
    HALF = FIXED_POINT_HALF
    ZERO = FIXED_POINT_ZERO
    
    # Scaling factors
    MIDI_SCALE = MIDI_SCALE
    PITCH_BEND_SCALE = PITCH_BEND_SCALE
    PITCH_BEND_CENTER = PITCH_BEND_CENTER
    
    @staticmethod
    def from_float(value):
        """Convert float to fixed-point with bounds checking"""
        try:
            value = max(min(value, 32767.0), -32768.0)
            return int(value * FixedPoint.SCALE)
        except (TypeError, OverflowError):
            return 0
    
    @staticmethod
    def to_float(fixed):
        """Convert fixed-point to float with safety checks"""
        try:
            return float(fixed) / float(FixedPoint.SCALE)
        except (TypeError, OverflowError):
            return 0.0
    
    @staticmethod
    def multiply(a, b):
        """Multiply two fixed-point numbers"""
        if not isinstance(a, int):
            a = FixedPoint.from_float(float(a))
        if not isinstance(b, int):
            b = FixedPoint.from_float(float(b))
        return (a * b) >> 16
    
    @staticmethod 
    def normalize_midi_value(value):
        """Normalize MIDI value (0-127) to 0-1 range"""
        # First normalize to 0-1 range in floating point
        normalized = value * FixedPoint.MIDI_SCALE  
        # Then convert normalized float to fixed-point format
        return FixedPoint.from_float(normalized)
    
    @staticmethod
    def normalize_pitch_bend(value):
        """Normalize pitch bend value (0-16383) to -1 to 1 range"""
        return ((value << 16) - FixedPoint.PITCH_BEND_CENTER) * FixedPoint.PITCH_BEND_SCALE
    
    @staticmethod
    def midi_note_to_frequency(note):
        """Convert MIDI note number to frequency"""
        # Clamp note to reasonable range
        note = max(0, min(note, 127))
        # Standard MIDI note to frequency formula
        return 440.0 * (2.0 ** ((note - 69) / 12.0))
    
    @staticmethod
    def midi_note_to_fixed(note):
        """Convert MIDI note number to fixed-point frequency"""
        # Clamp note to reasonable range
        note = max(0, min(note, 127))
        # Standard MIDI note to frequency formula
        freq = 440.0 * (2.0 ** ((note - 69) / 12.0))
        # Convert to fixed point
        return FixedPoint.from_float(freq)
