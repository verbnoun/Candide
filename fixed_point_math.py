import math

class FixedPoint:
    """Fixed-point math utilities for audio calculations"""
    SCALE = 1 << 16
    MAX_VALUE = (1 << 31) - 1
    MIN_VALUE = -(1 << 31)
    
    # Pre-calculated common values
    ONE = 1 << 16
    HALF = 1 << 15
    ZERO = 0
    
    # Scaling factors
    MIDI_SCALE = int((1 << 16) / 127)  # Corrected MIDI scaling
    PITCH_BEND_SCALE = 8  # 1/8192 in fixed point
    PITCH_BEND_CENTER = 8192 << 16
    
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
        return value * FixedPoint.MIDI_SCALE
    
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
