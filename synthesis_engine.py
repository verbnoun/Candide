"""Main synthesis engine with gate-based envelope control"""
import array
import math
import synthio
from fixed_point_math import FixedPoint
from synth_constants import Constants, FilterType

class WaveformManager:
    """Manages wavetable generation and morphing"""
    def __init__(self):
        self.waveforms = {}
        self._initialize_basic_waveforms()
    
    def _initialize_basic_waveforms(self):
        """Create standard waveforms"""
        self.generate_sine('sine')
        self.generate_saw('saw')
        self.generate_square('square')
        self.generate_triangle('triangle')
    
    def generate_sine(self, name, size=Constants.WAVE_TABLE_SIZE):
        """Generate sine waveform"""
        samples = array.array('h', [0] * size)
        for i in range(size):
            value = math.sin(2 * math.pi * i / size)
            samples[i] = int(value * 32767)
        self.waveforms[name] = samples
        return samples
    
    def generate_saw(self, name, size=Constants.WAVE_TABLE_SIZE):
        """Generate sawtooth waveform"""
        samples = array.array('h', [0] * size)
        for i in range(size):
            samples[i] = int(((i / size) * 2 - 1) * 32767)
        self.waveforms[name] = samples
        return samples
    
    def generate_square(self, name, duty=0.5, size=Constants.WAVE_TABLE_SIZE):
        """Generate square waveform with variable duty cycle"""
        samples = array.array('h', [0] * size)
        duty_point = int(size * duty)
        for i in range(size):
            samples[i] = 32767 if i < duty_point else -32767
        self.waveforms[name] = samples
        return samples
    
    def generate_triangle(self, name, size=Constants.WAVE_TABLE_SIZE):
        """Generate triangle waveform"""
        samples = array.array('h', [0] * size)
        half_size = size // 2
        for i in range(size):
            if i < half_size:
                value = (i / half_size) * 2 - 1
            else:
                value = 1 - ((i - half_size) / half_size) * 2
            samples[i] = int(value * 32767)
        self.waveforms[name] = samples
        return samples
    
    def get_waveform(self, name):
        """Get waveform by name"""
        return self.waveforms.get(name)

class EnvelopeManager:
    """Manages gate-based envelope generation"""
    def __init__(self):
        self.current_config = None
        
    def create_envelope(self, config=None):
        """Create envelope based on gate configuration"""
        self.current_config = config or {
            'attack': {
                'time': 0.01,
                'level': 1.0,
                'curve': 'linear'
            },
            'decay': {
                'time': 0.1,
                'level_scale': 1.0,
                'curve': 'exponential'
            },
            'sustain': {
                'level': 0.8,
                'curve': 'linear'
            },
            'release': {
                'time': 0.2,
                'level': 0.0,
                'curve': 'exponential'
            }
        }
        
        # Convert envelope config to synthio envelope
        return synthio.Envelope(
            attack_time=self.current_config['attack']['time'],
            decay_time=self.current_config['decay']['time'],
            sustain_level=self.current_config['sustain']['level'],
            release_time=self.current_config['release']['time']
        )

class FilterManager:
    """Manages filter configurations and gate-based updates"""
    def __init__(self, synth):
        self.synth = synth
        self.current_type = FilterType.LOW_PASS
        self.current_cutoff = 1000
        self.current_resonance = 0.7
        
    def create_filter(self, filter_type=None, cutoff=None, resonance=None):
        """Create new filter with current or specified parameters"""
        filter_type = filter_type or self.current_type
        cutoff = cutoff or self.current_cutoff
        resonance = resonance or self.current_resonance
        
        if filter_type == FilterType.LOW_PASS:
            return self.synth.low_pass_filter(cutoff, resonance)
        elif filter_type == FilterType.HIGH_PASS:
            return self.synth.high_pass_filter(cutoff, resonance)
        elif filter_type == FilterType.BAND_PASS:
            return self.synth.band_pass_filter(cutoff, resonance)
        return None
    
    def update_filter(self, note, cutoff=None, resonance=None):
        """Update filter parameters based on modulation"""
        if cutoff:
            self.current_cutoff = max(20, min(20000, cutoff))
        if resonance:
            self.current_resonance = max(0.1, min(2.0, resonance))
            
        if note.synth_note:
            note.synth_note.filter = self.create_filter()

class SynthesisEngine:
    """Main synthesis engine with gate-based envelope control"""
    def __init__(self, synth):
        self.synth = synth
        self.waveform_manager = WaveformManager()
        self.filter_manager = FilterManager(synth)
        self.envelope_manager = EnvelopeManager()
        self.current_instrument = None
        
    def create_note(self, frequency, amplitude=0.0, waveform_name='sine'):
        """Create new note with gate-based envelope"""
        waveform = self.waveform_manager.get_waveform(waveform_name)
        
        # Get envelope from current instrument config
        if self.current_instrument and 'envelope' in self.current_instrument:
            envelope = self.envelope_manager.create_envelope(
                self.current_instrument['envelope']
            )
        else:
            envelope = self.envelope_manager.create_envelope()
            
        note = synthio.Note(
            frequency=frequency,
            waveform=waveform,
            envelope=envelope,
            amplitude=amplitude,
            filter=self.filter_manager.create_filter()
        )
        
        if Constants.DEBUG:
            print(f"[SYNTH] Created note: freq={frequency:.2f}Hz, amp={amplitude:.2f}")
            print(f"[ENV] Starting attack stage: start={amplitude:.3f} target={amplitude:.3f}")
        
        return note
    
    def update_note_parameters(self, voice, params):
        """Update parameters based on modulation and gate states"""
        if not voice.synth_note:
            return

        if Constants.DEBUG:
            param_str = ", ".join(f"{k}={v:.2f}" for k, v in params.items())
            print(f"[SYNTH] Updating note params: {param_str}")

        # Basic parameter updates
        if 'frequency' in params:
            voice.synth_note.frequency = params['frequency']

        if 'amplitude' in params:
            # Get envelope configuration
            env_config = (self.current_instrument.get('envelope', {}) 
                        if self.current_instrument else {})
            
            # Update amplitude
            voice.synth_note.amplitude = params['amplitude']
            
            if Constants.DEBUG:
                print(f"[ENV] Updating amplitude: {params['amplitude']:.3f}")

        # Filter updates if needed
        if 'filter_cutoff' in params or 'filter_resonance' in params:
            self.filter_manager.update_filter(
                voice,
                params.get('filter_cutoff'),
                params.get('filter_resonance')
            )
