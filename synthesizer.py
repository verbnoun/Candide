"""
synthesizer.py - Synthesis Value Calculations

Provides value manipulation and calculations for voices.py.
All methods are stateless calculation tools.
"""
import sys
import synthio
from constants import SYNTH_DEBUG

def _log(message, module="SYNTH"):
    """Enhanced logging for synthesis operations"""
    if not SYNTH_DEBUG:
        return
        
    GREEN = "\033[32m"  # Green for synthesis operations
    RED = "\033[31m"    # Red for errors
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        color = RED if "[ERROR]" in str(message) else GREEN
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)
    else:
        color = RED if "[ERROR]" in str(message) else GREEN
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class Synthesizer:
    """Synthesis calculation tools and value manipulation"""
    
    def note_to_frequency(self, note_number):
        """Convert MIDI note number to frequency using synthio"""
        return synthio.midi_to_hz(note_number)
        
    def calculate_pressure_amplitude(self, pressure, current_amp):
        """Calculate amplitude based on pressure value"""
        _log(f"Calculating pressure amplitude: pressure={pressure}, current={current_amp}")
        return max(0.0, min(1.0, current_amp * pressure))
            
    def calculate_filter(self, frequency, resonance):
        """Create a filter with the given parameters"""
        if resonance is None:
            resonance = 0.7
            
        frequency = max(20, min(20000, frequency))
        filter_type = 'highpass' if frequency < 100 else 'lowpass'
        
        _log({
            'filter': True,
            'type': filter_type,
            'frequency': frequency,
            'resonance': resonance
        })
        
        try:
            if frequency < 100:  # High pass for very low frequencies
                return synthio.HighPassFilter(frequency, resonance)
            else:  # Low pass for most frequencies
                return synthio.LowPassFilter(frequency, resonance)
        except Exception as e:
            _log(f"[ERROR] Filter creation failed: {str(e)}")
            return None