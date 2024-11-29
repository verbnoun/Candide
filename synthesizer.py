"""
synthesizer.py - Synthesis Value Calculations

Provides value manipulation and calculations for voices.py.
All methods are stateless calculation tools.
"""
import time
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

class Timer:
    """
    A generic timer class that calls a provided callback when the timer expires.
    """
    def __init__(self):
        self._start_time = None
        self._duration = None
        self._callback = None

    def start(self, duration, callback):
        """
        Start the timer with the given duration and callback.
        
        Parameters:
        duration (float): The duration of the timer in seconds.
        callback (callable): The function to be called when the timer expires.
        """
        self._start_time = time.monotonic()
        self._duration = duration
        self._callback = callback

    def update(self):
        """
        Check if the timer has expired and call the provided callback if so.
        """
        if self._start_time is not None:
            if time.monotonic() - self._start_time >= self._duration:
                self._callback()
                self.reset()

    def reset(self):
        """
        Reset the timer, clearing the start time, duration, and callback.
        """
        self._start_time = None
        self._duration = None
        self._callback = None

class Synthesizer:
    """Synthesis calculation tools and value manipulation"""
    
    def __init__(self):
        # Cache for storing generated waveforms
        self._waveforms = {}
        
    def note_to_frequency(self, note_number):
        """Convert MIDI note number to frequency using synthio"""
        return synthio.midi_to_hz(note_number)
        
    def calculate_pressure_amplitude(self, pressure, current_amp):
        """Calculate amplitude based on pressure value"""
        _log(f"Calculating pressure amplitude: pressure={pressure}, current={current_amp}")
        return max(0.0, min(1.0, current_amp * pressure))
    
    def get_waveform(self, wave_type):
        """Get waveform data, generating if needed"""
        if wave_type not in self._waveforms:
            _log(f"Generating waveform: {wave_type}")
            try:
                if wave_type == 'square':
                    # Generate square wave - simple high/low values
                    import array
                    length = 512
                    square = array.array('h')
                    for i in range(length):
                        if i < length/2:
                            square.append(32000)  # Max positive value
                        else:
                            square.append(-32000)  # Max negative value
                    self._waveforms[wave_type] = square
                else:
                    _log(f"[ERROR] Unknown waveform type: {wave_type}")
                    return None
                    
            except Exception as e:
                _log(f"[ERROR] Failed to generate waveform: {str(e)}")
                return None
                
        _log(f"Retrieved waveform: {wave_type}")
        return self._waveforms[wave_type]
            
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