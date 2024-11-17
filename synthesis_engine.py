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
    
    def morph_waveforms(self, wave1, wave2, amount):
        """Create new waveform by morphing between two others"""
        if not isinstance(wave1, array.array):
            wave1 = self.get_waveform(wave1)
        if not isinstance(wave2, array.array):
            wave2 = self.get_waveform(wave2)
        
        if not wave1 or not wave2:
            return None
            
        size = len(wave1)
        if len(wave2) != size:
            return None
            
        result = array.array('h', [0] * size)
        for i in range(size):
            result[i] = int(wave1[i] * (1 - amount) + wave2[i] * amount)
        return result

class FilterManager:
    """Manages filter configurations and updates
    
    MPE Signal Flow:
    1. Receives filter parameters from modulation matrix
    2. Timbre (CC74) often maps to filter cutoff
    3. Pressure can affect filter resonance
    """
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
        """Update filter parameters for a note based on MPE modulation"""
        if cutoff:
            self.current_cutoff = max(20, min(20000, cutoff))
        if resonance:
            self.current_resonance = max(0.1, min(2.0, resonance))
            
        if note.synth_note:
            note.synth_note.filter = self.create_filter()

class EnvelopeManager:
    """Manages envelope generation and updates"""
    def __init__(self):
        self.default_envelope = {
            'attack': 0.01,
            'decay': 0.1,
            'sustain': 0.8,
            'release': 0.2
        }
    
    def create_envelope(self, params=None):
        """Create new envelope with given or default parameters"""
        if params is None:
            params = self.default_envelope
        
        return synthio.Envelope(
            attack_time=max(0.001, params.get('attack', self.default_envelope['attack'])),
            decay_time=max(0.001, params.get('decay', self.default_envelope['decay'])),
            sustain_level=max(0.0, min(1.0, params.get('sustain', self.default_envelope['sustain']))),
            release_time=max(0.001, params.get('release', self.default_envelope['release']))
        )

class SynthesisEngine:
    """Main synthesis engine coordinating voices and parameters
    
    MPE Signal Flow:
    1. Receives modulated parameters from modulation matrix
    2. Note number -> oscillator frequency
    3. Velocity -> initial amplitude
    4. Pressure -> ongoing amplitude modulation
    5. Pitch bend -> frequency modulation
    6. Timbre (CC74) -> filter cutoff modulation
    """
    def __init__(self, synth):
        self.synth = synth
        self.waveform_manager = WaveformManager()
        self.filter_manager = FilterManager(synth)
        self.envelope_manager = EnvelopeManager()
        
    def create_note(self, frequency, velocity=1.0, waveform_name='sine'):
        """Create new synthio Note with current parameters
        
        MPE parameters affect:
        - frequency: Base pitch + pitch bend modulation
        - velocity: Initial amplitude scaling
        """
        waveform = self.waveform_manager.get_waveform(waveform_name)
        envelope = self.envelope_manager.create_envelope()
        
        note = synthio.Note(
            frequency=frequency,
            waveform=waveform,
            envelope=envelope,
            amplitude=velocity,
            filter=self.filter_manager.create_filter()
        )
        
        if Constants.DEBUG:
            print("[SYNTH] Created note: freq={0:.2f}Hz, vel={1:.2f}".format(frequency, velocity))
        
        return note
    
    def create_ring_modulated_note(self, frequency, ring_freq, velocity=1.0,
                                 carrier_wave='sine', modulator_wave='sine'):
        """Create note with ring modulation"""
        carrier = self.waveform_manager.get_waveform(carrier_wave)
        modulator = self.waveform_manager.get_waveform(modulator_wave)
        envelope = self.envelope_manager.create_envelope()
        
        note = synthio.Note(
            frequency=frequency,
            waveform=carrier,
            envelope=envelope,
            amplitude=velocity,
            filter=self.filter_manager.create_filter(),
            ring_frequency=ring_freq,
            ring_waveform=modulator
        )
        
        if Constants.DEBUG:
            print("[SYNTH] Created ring mod note: freq={0:.2f}Hz, ring={1:.2f}Hz".format(frequency, ring_freq))
        
        return note
    
    def update_note_parameters(self, note, params):
        """Update parameters for an existing note based on MPE modulation
        
        MPE Signal Flow:
        1. Receives continuous MPE updates from modulation matrix
        2. Updates note parameters in real-time:
           - Pitch bend -> frequency
           - Pressure -> amplitude
           - Timbre -> filter cutoff
        """
        if not note.synth_note:
            return
            
        if Constants.DEBUG:
            param_str = ", ".join("{0}={1:.2f}".format(k, v) for k, v in params.items())
            print("[SYNTH] Updating note params: {0}".format(param_str))
            
        if 'frequency' in params:
            note.synth_note.frequency = params['frequency']
        
        if 'amplitude' in params:
            note.synth_note.amplitude = params['amplitude']
        
        if 'bend' in params:
            note.synth_note.bend = params['bend']
        
        if 'filter_cutoff' in params or 'filter_resonance' in params:
            self.filter_manager.update_filter(
                note,
                params.get('filter_cutoff'),
                params.get('filter_resonance')
            )
        
        if 'ring_frequency' in params:
            note.synth_note.ring_frequency = params['ring_frequency']
        
        if 'ring_bend' in params:
            note.synth_note.ring_bend = params['ring_bend']
