"""
synthesizer.py - Synthesis Value Calculations

Provides value manipulation and calculations for voices.py.
Handles wave creation, envelope generation, filter calculations, etc.
All methods are stateless calculation tools.
"""
import sys
import ulab.numpy as np
import synthio
from constants import SYNTH_DEBUG

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
    
    def format_envelope_calc(params, env_type):
        """Format envelope calculation details."""
        lines = []
        lines.append(f"[{module}]")
        lines.append(f"Envelope calculation ({env_type}):")
        for param, value in params.items():
            lines.append(f"  {param}: {value}")
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
        elif 'envelope' in str(message):
            formatted = format_envelope_calc(
                message.get('params', {}),
                message.get('type', 'unknown')
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
        self.SAMPLE_SIZE = 512
        self.SAMPLE_VOLUME = 32000  # Max 32767
        _log("Synthesizer initialized")
        
    # Wave Generation
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
            
    # LFO Creation
    def create_lfo(self, rate, scale, offset=0, wave_type='sine'):
        """Create an LFO with specified parameters"""
        _log(f"Creating LFO: rate={rate}, scale={scale}, offset={offset}, type={wave_type}")
        try:
            waveform = self.create_wave(wave_type)
            if waveform is None:
                _log("[ERROR] Failed to create LFO waveform")
                return None
                
            return synthio.LFO(
                waveform=waveform,
                rate=rate, 
                scale=scale, 
                offset=offset
            )
        except Exception as e:
            _log(f"[ERROR] LFO creation failed: {str(e)}")
            return None
            
    # Filter Calculations
    def calculate_filter(self, frequency, resonance):
        """Create a filter with the given parameters"""
        if resonance is None:
            resonance = 0.7
            
        # Handle frequency bounds
        frequency = max(20, min(20000, frequency))
        
        filter_type = 'highpass' if frequency < 100 else 'lowpass'
        
        _log({
            'filter': True,
            'type': filter_type,
            'frequency': frequency,
            'resonance': resonance
        })
        
        try:
            # Create appropriate filter type based on frequency range
            if frequency < 100:  # High pass for very low frequencies
                return synthio.high_pass_filter(frequency, resonance)
            else:  # Low pass for most frequencies
                return synthio.low_pass_filter(frequency, resonance)
        except Exception as e:
            _log(f"[ERROR] Filter creation failed: {str(e)}")
            return None
            
    def calculate_filter_lfo(self, base_freq, resonance, lfo):
        """Calculate filter with LFO modulation"""
        # Ensure base frequency exists
        if base_freq is None:
            base_freq = 1000
            _log("Using default base frequency: 1000Hz")
            
        try:
            # Create filter using LFO for frequency modulation    
            return self.calculate_filter(base_freq * lfo.value, resonance)
        except Exception as e:
            _log(f"[ERROR] Filter LFO calculation failed: {str(e)}")
            return None
            
    # Envelope Calculations
    def calculate_envelope(self, params, env_type):
        """
        Create envelope from parameters.
        env_type: 'frequency', 'amplitude', 'filter', 'ring'
        """
        prefix = f"{env_type}_"
        
        envelope_params = {
            'attack_time': 0.1,    # Default values
            'decay_time': 0.05,
            'sustain_level': 0.8,
            'release_time': 0.2,
            'attack_level': 1.0
        }
        
        # Update with any provided params
        for param, default in envelope_params.items():
            key = prefix + param
            if key in params:
                envelope_params[param] = params[key]
                
        _log({
            'envelope': True,
            'type': env_type,
            'params': envelope_params
        })
        
        try:
            return synthio.Envelope(
                attack_time=envelope_params['attack_time'],
                decay_time=envelope_params['decay_time'],
                sustain_level=envelope_params['sustain_level'],
                release_time=envelope_params['release_time'],
                attack_level=envelope_params['attack_level']
            )
        except Exception as e:
            _log(f"[ERROR] Envelope creation failed: {str(e)}")
            return None
            
    def calculate_filter_envelope(self, params):
        """Calculate filter parameters modulated by envelope"""
        freq = params.get('filter_frequency', 1000)
        res = params.get('filter_resonance', 0.7)
        
        _log(f"Calculating filter envelope: freq={freq}, res={res}")
        
        try:
            env = self.calculate_envelope(params, 'filter')
            return self.calculate_filter(freq, res)
        except Exception as e:
            _log(f"[ERROR] Filter envelope calculation failed: {str(e)}")
            return None

    # Amplitude Calculations
    def calculate_pressure_amplitude(self, pressure, current_amp):
        """Calculate amplitude based on pressure value"""
        _log(f"Calculating pressure amplitude: pressure={pressure}, current={current_amp}")
        return max(0.0, min(1.0, current_amp * pressure))
        
    def calculate_expression(self, expression, current_amp):
        """Calculate amplitude based on expression value"""
        _log(f"Calculating expression amplitude: expression={expression}, current={current_amp}")
        return max(0.0, min(1.0, current_amp * expression))

    # Timbre Calculations    
    def calculate_timbre(self, cc74_value):
        """Calculate ring modulation frequency from CC74 value"""
        # Map CC74 0-1 to frequency range 100Hz-8000Hz
        freq = 100 + (cc74_value * 7900)
        _log(f"Calculating timbre frequency: cc74={cc74_value}, freq={freq}")
        return freq

    # Value Combination/Scaling
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
