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
    
    # Map filter type strings to synthio FilterMode enums
    FILTER_MODES = {
        'lowpass': synthio.FilterMode.LOW_PASS,
        'highpass': synthio.FilterMode.HIGH_PASS,
        'bandpass': synthio.FilterMode.BAND_PASS,
        'notch': synthio.FilterMode.NOTCH
    }
    
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
            
    def calculate_filter(self, frequency, resonance, filter_type='lowpass'):
        """Create a filter with the given parameters using synthio.BlockBiquad
        
        Args:
            frequency (float): Filter frequency in Hz (20-20000)
            resonance (float): Filter resonance/Q (0.1-2.0)
            filter_type (str): One of 'lowpass', 'highpass', 'bandpass', 'notch'
            
        Returns:
            synthio.BlockBiquad: Configured filter object
            
        The filter types correspond to synthio.FilterMode:
        - lowpass: Attenuates frequencies above cutoff (LOW_PASS)
        - highpass: Attenuates frequencies below cutoff (HIGH_PASS)
        - bandpass: Passes frequencies within a range around cutoff (BAND_PASS)
        - notch: Attenuates frequencies within a range around cutoff (NOTCH)
        """
        if resonance is None:
            resonance = 0.7
            
        # Clamp frequency and resonance to valid ranges
        frequency = max(20, min(20000, frequency))
        resonance = max(0.1, min(2.0, resonance))
        
        # Convert filter type string to synthio FilterMode
        filter_mode = self.FILTER_MODES.get(filter_type.lower())
        if filter_mode is None:
            _log(f"[ERROR] Unknown filter type: {filter_type}, defaulting to lowpass")
            filter_mode = synthio.FilterMode.LOW_PASS
        
        _log({
            'filter': True,
            'type': filter_type,
            'mode': str(filter_mode),
            'frequency': frequency,
            'resonance': resonance
        })
        
        try:
            # Create filter using synthio.BlockBiquad with appropriate FilterMode
            return synthio.BlockBiquad(filter_mode, frequency, resonance)
        except Exception as e:
            _log(f"[ERROR] Filter creation failed: {str(e)}")
            return None
