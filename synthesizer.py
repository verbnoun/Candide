"""
synthesizer.py - Synthesis Value Calculations

Provides value manipulation and calculations for voices.py.
All methods are stateless calculation tools.
"""
import sys
import ulab.numpy as np
import synthio
from constants import SYNTH_DEBUG, SAMPLE_RATE, AUDIO_CHANNEL_COUNT

def _log(message, module="SYNTH"):
    """Enhanced logging for synthesis operations"""
    if not SYNTH_DEBUG:
        return
        
    GREEN = "\033[32m"  # Green for synthesis operations
    RED = "\033[31m"    # Red for errors
    RESET = "\033[0m"
    
    def format_wave_creation(wave_type, size, volume):
        """Format wave creation details."""
        lines = []
        lines.append(f"[{module}]")
        lines.append("Wave creation:")
        lines.append(f"  type: {wave_type}")
        lines.append(f"  size: {size}")
        lines.append(f"  volume: {volume}")
        return "\n".join(lines)
    
    def format_filter_calc(frequency, resonance, filter_type="lowpass"):
        """Format filter calculation details."""
        lines = []
        lines.append(f"[{module}]")
        lines.append("Filter calculation:")
        lines.append(f"  type: {filter_type}")
        lines.append(f"  frequency: {frequency}")
        lines.append(f"  resonance: {resonance}")
        return "\n".join(lines)

    if isinstance(message, dict):
        if 'wave' in str(message):
            formatted = format_wave_creation(
                message.get('type', 'unknown'),
                message.get('size', 0),
                message.get('volume', 0)
            )
        elif 'filter' in str(message):
            formatted = format_filter_calc(
                message.get('frequency', 0),
                message.get('resonance', 0),
                message.get('type', 'lowpass')
            )
        else:
            formatted = f"[{module}] {message}"
        print(f"{GREEN}{formatted}{RESET}\n", file=sys.stderr)
    else:
        color = RED if "[ERROR]" in str(message) else GREEN
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class Synthesizer:
    """Synthesis calculation tools and value manipulation"""
    
    def __init__(self):
        _log("Initializing Synthesizer class...")
        _log("Setting up sample parameters...")
        self.SAMPLE_SIZE = 512
        self.SAMPLE_VOLUME = 32000  # Max 32767
        
        _log("Creating synthio.Synthesizer instance...")
        _log(f"Using SAMPLE_RATE={SAMPLE_RATE}, AUDIO_CHANNEL_COUNT={AUDIO_CHANNEL_COUNT}")
        self.synth = synthio.Synthesizer(sample_rate=SAMPLE_RATE, channel_count=AUDIO_CHANNEL_COUNT)
        _log("Synthesizer initialization complete")
        
    def create_wave(self, wave_type):
        """Generate waveform buffer of specified type"""
        _log({
            'wave': True,
            'type': wave_type,
            'size': self.SAMPLE_SIZE,
            'volume': self.SAMPLE_VOLUME
        })
        
        try:
            if wave_type == 'sine':
                return np.array(
                    np.sin(np.linspace(0, 2*np.pi, self.SAMPLE_SIZE, endpoint=False)) 
                    * self.SAMPLE_VOLUME, 
                    dtype=np.int16
                )
            elif wave_type == 'square':
                return np.array(
                    [self.SAMPLE_VOLUME] * (self.SAMPLE_SIZE//2) + 
                    [-self.SAMPLE_VOLUME] * (self.SAMPLE_SIZE//2), 
                    dtype=np.int16
                )
            elif wave_type == 'saw':
                return np.linspace(
                    self.SAMPLE_VOLUME, 
                    -self.SAMPLE_VOLUME, 
                    num=self.SAMPLE_SIZE, 
                    dtype=np.int16
                )
            elif wave_type == 'triangle':
                return np.concatenate([
                    np.linspace(-self.SAMPLE_VOLUME, self.SAMPLE_VOLUME, self.SAMPLE_SIZE//2, dtype=np.int16),
                    np.linspace(self.SAMPLE_VOLUME, -self.SAMPLE_VOLUME, self.SAMPLE_SIZE//2, dtype=np.int16)
                ])
            else:
                _log(f"[ERROR] Unknown wave type: {wave_type}")
                return None
        except Exception as e:
            _log(f"[ERROR] Wave creation failed: {str(e)}")
            return None

    def note_to_frequency(self, note_number):
        """Convert MIDI note number to frequency using synthio"""
        return synthio.midi_to_hz(note_number)
            
    def create_lfo(self, rate, scale, offset=0, wave_type='sine'):
        """Create an LFO with specified parameters"""
        _log(f"Creating LFO: rate={rate}, scale={scale}, offset={offset}, type={wave_type}")
        try:
            waveform = self.create_wave(wave_type)
            if waveform is None:
                _log("[ERROR] Failed to create LFO waveform")
                return None
                
            return synthio.LFO(waveform, rate, scale, offset)
        except Exception as e:
            _log(f"[ERROR] LFO creation failed: {str(e)}")
            return None
            
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
                return self.synth.high_pass_filter(frequency, resonance)
            else:  # Low pass for most frequencies
                return self.synth.low_pass_filter(frequency, resonance)
        except Exception as e:
            _log(f"[ERROR] Filter creation failed: {str(e)}")
            return None

    def calculate_filter_lfo(self, base_freq, resonance, lfo):
        """Calculate filter with LFO modulation"""
        if base_freq is None:
            base_freq = 1000
            _log("Using default base frequency: 1000Hz")
            
        try:
            return self.calculate_filter(base_freq * lfo.value, resonance)
        except Exception as e:
            _log(f"[ERROR] Filter LFO calculation failed: {str(e)}")
            return None

    def calculate_pressure_amplitude(self, pressure, current_amp):
        """Calculate amplitude based on pressure value"""
        _log(f"Calculating pressure amplitude: pressure={pressure}, current={current_amp}")
        return max(0.0, min(1.0, current_amp * pressure))
        
    def calculate_timbre(self, cc74_value):
        """Calculate ring modulation frequency from CC74 value"""
        # Map CC74 0-1 to frequency range 100Hz-8000Hz
        freq = 100 + (cc74_value * 7900)
        _log(f"Calculating timbre frequency: cc74={cc74_value}, freq={freq}")
        return freq

    def combine_values(self, val1, val2, mode='multiply'):
        """Combine two normalized values"""
        _log(f"Combining values: {val1} {mode} {val2}")
        if mode == 'multiply':
            return val1 * val2
        elif mode == 'add':
            return min(1.0, max(0.0, val1 + val2))
        elif mode == 'max':
            return max(val1, val2)
        return val1  # Default to first value