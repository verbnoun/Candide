"""Clean interfaces for all synthio operations."""

import synthio
import array
import math
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT, STATIC_WAVEFORM_SAMPLES, MORPHED_WAVEFORM_SAMPLES
from logging import log, TAG_SYNTH

class FilterMode:
    """The type of filter, matching synthio.FilterMode."""
    LOW_PASS = synthio.FilterMode.LOW_PASS
    HIGH_PASS = synthio.FilterMode.HIGH_PASS
    BAND_PASS = synthio.FilterMode.BAND_PASS
    NOTCH = synthio.FilterMode.NOTCH

class MathOperation:
    """Operation for a Math block, matching synthio.MathOperation."""
    SUM = synthio.MathOperation.SUM
    ADD_SUB = synthio.MathOperation.ADD_SUB
    PRODUCT = synthio.MathOperation.PRODUCT
    MUL_DIV = synthio.MathOperation.MUL_DIV
    SCALE_OFFSET = synthio.MathOperation.SCALE_OFFSET
    OFFSET_SCALE = synthio.MathOperation.OFFSET_SCALE
    LERP = synthio.MathOperation.LERP
    CONSTRAINED_LERP = synthio.MathOperation.CONSTRAINED_LERP
    DIV_ADD = synthio.MathOperation.DIV_ADD
    ADD_DIV = synthio.MathOperation.ADD_DIV
    MID = synthio.MathOperation.MID
    MAX = synthio.MathOperation.MAX
    MIN = synthio.MathOperation.MIN
    ABS = synthio.MathOperation.ABS

class Math:
    """An arithmetic block matching synthio.Math."""
    def __init__(self, operation, a=0.0, b=0.0, c=1.0):
        """Initialize Math block with operation and values."""
        self._math = synthio.Math(operation=operation, a=a, b=b, c=c)
    
    @property
    def value(self):
        """Current output value of the math block."""
        return self._math.value
    
    @property
    def a(self):
        """First input value."""
        return self._math.a
    
    @a.setter
    def a(self, value):
        self._math.a = value
    
    @property
    def b(self):
        """Second input value."""
        return self._math.b
    
    @b.setter
    def b(self, value):
        self._math.b = value
    
    @property
    def c(self):
        """Third input value."""
        return self._math.c
    
    @c.setter
    def c(self, value):
        self._math.c = value

class LFO:
    """A low-frequency oscillator block matching synthio.LFO."""
    def __init__(self, waveform=None, rate=1.0, scale=1.0, offset=0.0,
                 phase_offset=0.0, once=False, interpolate=True):
        """Initialize LFO with given parameters."""
        self._lfo = synthio.LFO(
            waveform=waveform,
            rate=rate,
            scale=scale,
            offset=offset,
            phase_offset=phase_offset,
            once=once,
            interpolate=interpolate
        )
    
    def retrigger(self):
        """Reset the LFO's internal phase to the start."""
        self._lfo.retrigger()
    
    @property
    def phase(self):
        """Current phase of the LFO (0.0 to 1.0)."""
        return self._lfo.phase
    
    @phase.setter
    def phase(self, value):
        """Set the phase directly (0.0 to 1.0)."""
        self._lfo.phase = value
    
    @property
    def value(self):
        """Current output value of the LFO."""
        return self._lfo.value
    
    @property
    def rate(self):
        """Oscillation rate in Hz."""
        return self._lfo.rate
    
    @rate.setter
    def rate(self, value):
        self._lfo.rate = value
    
    @property
    def scale(self):
        """Output amplitude scaling."""
        return self._lfo.scale
    
    @scale.setter
    def scale(self, value):
        self._lfo.scale = value
    
    @property
    def offset(self):
        """DC offset added to output."""
        return self._lfo.offset
    
    @offset.setter
    def offset(self, value):
        self._lfo.offset = value
        
    @property
    def once(self):
        """One-shot mode state."""
        return self._lfo.once
    
    @once.setter
    def once(self, value):
        """Set one-shot mode."""
        self._lfo.once = value
        
    @property
    def interpolate(self):
        """Sample interpolation state."""
        return self._lfo.interpolate
    
    @interpolate.setter
    def interpolate(self, value):
        """Set sample interpolation state."""
        self._lfo.interpolate = value

class SynthioInterfaces:
    """Clean interfaces for all synthio operations."""
    
    # Cache for pre-computed waveforms
    _waveform_cache = {}
    _morphed_waveform_cache = {}
    
    @staticmethod
    def create_note(frequency, **kwargs):
        """Create a synthio note with the given parameters.
        
        Required:
        - frequency: Note frequency in Hz
        
        Optional keyword arguments:
        - amplitude: Note amplitude (0.0 to 1.0)
        - panning: Stereo panning (-1.0 to 1.0)
        - waveform: Waveform buffer
        - waveform_loop_start: Start index for waveform loop
        - waveform_loop_end: End index for waveform loop
        - envelope: Envelope object
        - filter: Filter object
        - ring_frequency: Ring modulation frequency in Hz
        - ring_waveform: Ring modulation waveform buffer
        - ring_waveform_loop_start: Start index for ring waveform loop
        - ring_waveform_loop_end: End index for ring waveform loop
        - ring_bend: Ring modulation frequency bend
        """
        try:
            # Handle waveform loop end if waveform is provided
            if 'waveform' in kwargs and 'waveform_loop_end' not in kwargs:
                kwargs['waveform_loop_end'] = len(kwargs['waveform'])
            
            # Handle ring waveform loop end if ring waveform is provided
            if 'ring_waveform' in kwargs and 'ring_waveform_loop_end' not in kwargs:
                kwargs['ring_waveform_loop_end'] = len(kwargs['ring_waveform'])

            # Add required frequency parameter
            kwargs['frequency'] = frequency

            note = synthio.Note(**kwargs)
            return note
        except Exception as e:
            log(TAG_SYNTH, f"Error creating note: {str(e)}", is_error=True)
            raise

    @staticmethod
    def create_envelope(attack_time=0.1, decay_time=0.05, release_time=0.2, 
                       attack_level=1.0, sustain_level=0.8):
        """Create a synthio envelope with the given parameters."""
        try:
            envelope = synthio.Envelope(
                attack_time=attack_time,
                decay_time=decay_time, 
                release_time=release_time,
                attack_level=attack_level,
                sustain_level=sustain_level
            )
            return envelope
        except Exception as e:
            log(TAG_SYNTH, f"Error creating envelope: {str(e)}", is_error=True)
            raise

    @staticmethod
    def create_filter(synth, filter_type, frequency, Q=0.7071067811865475):
        """Create a synthio filter with the given parameters."""
        try:
            filter_mode = filter_type
            if hasattr(filter_type, 'value'):  # For backward compatibility
                filter_mode = filter_type.value
            
            filter = synthio.Filter(mode=filter_mode, frequency=frequency, Q=Q)
            
            # Add resonance alias for Q
            filter.resonance = filter.Q
            
            # Add property getters/setters
            @property
            def get_frequency(self):
                return self.frequency
                
            @frequency.setter
            def set_frequency(self, value):
                self.frequency = value
                
            filter.get_frequency = get_frequency
            filter.set_frequency = set_frequency
            
            return filter
        except Exception as e:
            log(TAG_SYNTH, f"Error creating filter: {str(e)}", is_error=True)
            raise

    @staticmethod
    def get_cached_waveform(waveform_type):
        """Get or create a waveform from cache."""
        if waveform_type not in SynthioInterfaces._waveform_cache:
            SynthioInterfaces._waveform_cache[waveform_type] = SynthioInterfaces.create_waveform(waveform_type)
            log(TAG_SYNTH, f"Created and cached {waveform_type} waveform")
        return SynthioInterfaces._waveform_cache[waveform_type]

    @staticmethod
    def create_waveform(waveform_type, samples=STATIC_WAVEFORM_SAMPLES):
        """Create a waveform buffer based on type."""
        try:
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
            elif waveform_type == 'noise':
                import random
                for _ in range(samples):
                    value = int(random.uniform(-32767, 32767))
                    buffer.append(value)
            elif waveform_type == 'white_noise':
                import random
                prev = 0
                for _ in range(samples):
                    curr = random.uniform(-32767, 32767)
                    value = int((prev + curr) / 2)  # Simple 1-pole filter
                    buffer.append(value)
                    prev = curr
            else:
                raise ValueError(f"Invalid waveform type: {waveform_type}")
            
            return buffer
        except Exception as e:
            log(TAG_SYNTH, f"Error creating waveform: {str(e)}", is_error=True)
            raise

    @staticmethod
    def create_synthesizer(sample_rate=SAMPLE_RATE, channel_count=AUDIO_CHANNEL_COUNT,
                          waveform=None, envelope=None, **kwargs):
        """Create a synthio synthesizer with the given parameters.
        
        Required:
        - sample_rate: Audio sample rate (default from constants)
        - channel_count: Number of audio channels (default from constants)
        
        Optional:
        - waveform: Default waveform buffer
        - envelope: Default envelope object
        
        Optional keyword arguments:
        - bend_range: Pitch bend range in semitones
        - midi_channel: MIDI channel (None for all channels)
        - block_size: Audio block processing size
        """
        try:
            params = {
                'sample_rate': sample_rate,
                'channel_count': channel_count
            }
            
            # Add optional parameters if provided
            if waveform is not None:
                params['waveform'] = waveform
            if envelope is not None:
                params['envelope'] = envelope
                
            # Add any additional keyword arguments
            params.update(kwargs)
            
            synth = synthio.Synthesizer(**params)
            return synth
        except Exception as e:
            log(TAG_SYNTH, f"Error creating synthesizer: {str(e)}", is_error=True)
            raise

    @staticmethod
    def create_morphed_waveform(morph_position, waveform_sequence=None):
        """Create a morphed waveform based on position and sequence."""
        if waveform_sequence is None:
            waveform_sequence = ['sine', 'triangle', 'square', 'saw']
        
        try:
            # Calculate which waveforms to blend between
            num_transitions = len(waveform_sequence) - 1
            if num_transitions == 0:
                return SynthioInterfaces.get_cached_waveform(waveform_sequence[0])
                
            # Scale position to total number of transitions
            scaled_pos = morph_position * num_transitions
            transition_index = int(scaled_pos)
            
            # Clamp to valid range
            if transition_index >= num_transitions:
                return SynthioInterfaces.get_cached_waveform(waveform_sequence[-1])
            
            # Get the two waveforms to blend
            waveform1 = SynthioInterfaces.get_cached_waveform(waveform_sequence[transition_index])
            waveform2 = SynthioInterfaces.get_cached_waveform(waveform_sequence[transition_index + 1])
            
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
            
            log(TAG_SYNTH, f"Created morphed waveform at position {morph_position}")
            return morphed
            
        except Exception as e:
            log(TAG_SYNTH, f"Error creating morphed waveform: {str(e)}", is_error=True)
            raise

class WaveformMorph:
    """Handles pre-calculated morphed waveforms for MIDI control."""
    def __init__(self, name, waveform_sequence=None):
        self.name = name
        self.waveform_sequence = waveform_sequence or ['sine', 'triangle', 'square', 'saw']
        self.lookup_table = []  # Will be 128 morphed waveforms
        self._build_lookup()
        log(TAG_SYNTH, f"Created waveform morph: {name}")
        
    def _build_lookup(self):
        """Build lookup table of 128 morphed waveforms for MIDI control."""
        cache_key = '-'.join(self.waveform_sequence)
        if cache_key in SynthioInterfaces._morphed_waveform_cache:
            self.lookup_table = SynthioInterfaces._morphed_waveform_cache[cache_key]
            log(TAG_SYNTH, f"Using cached morph table for {cache_key}")
            return
            
        samples = MORPHED_WAVEFORM_SAMPLES
        num_transitions = len(self.waveform_sequence) - 1
        
        self.lookup_table = []
        for midi_value in range(128):
            morph_position = midi_value / 127.0
            self.lookup_table.append(
                SynthioInterfaces.create_morphed_waveform(
                    morph_position, 
                    self.waveform_sequence
                )
            )
            
        # Cache the computed morph table
        SynthioInterfaces._morphed_waveform_cache[cache_key] = self.lookup_table
        log(TAG_SYNTH, f"Cached morph table for {cache_key}")
    
    def get_waveform(self, midi_value):
        """Get pre-calculated morphed waveform for MIDI value."""
        if not 0 <= midi_value <= 127:
            log(TAG_SYNTH, f"Invalid MIDI value {midi_value}", is_error=True)
            raise ValueError(f"MIDI value must be between 0 and 127")
        return self.lookup_table[midi_value]
