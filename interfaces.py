"""Clean interfaces for all synthio operations."""

import synthio
import array
import math
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT, STATIC_WAVEFORM_SAMPLES, MORPHED_WAVEFORM_SAMPLES
from logging import log, TAG_IFACE

class FilterMode:
    LOW_PASS = synthio.FilterMode.LOW_PASS
    HIGH_PASS = synthio.FilterMode.HIGH_PASS
    BAND_PASS = synthio.FilterMode.BAND_PASS
    NOTCH = synthio.FilterMode.NOTCH

class MathOperation:
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
    def __init__(self, operation, a, **kwargs):
        self._math = synthio.Math(operation=operation, a=a, **kwargs)
    
    @property
    def value(self):
        return self._math.value
    
    @property
    def a(self):
        return self._math.a
    
    @a.setter
    def a(self, value):
        self._math.a = value
    
    @property
    def b(self):
        return self._math.b
    
    @b.setter
    def b(self, value):
        self._math.b = value
    
    @property
    def c(self):
        return self._math.c
    
    @c.setter
    def c(self, value):
        self._math.c = value

class LFO:
    def __init__(self, **kwargs):
        self._lfo = synthio.LFO(**kwargs)
    
    def retrigger(self):
        self._lfo.retrigger()
    
    @property
    def phase(self):
        return self._lfo.phase
    
    @phase.setter
    def phase(self, value):
        self._lfo.phase = value
    
    @property
    def value(self):
        return self._lfo.value
    
    @property
    def rate(self):
        return self._lfo.rate
    
    @rate.setter
    def rate(self, value):
        self._lfo.rate = value
    
    @property
    def scale(self):
        return self._lfo.scale
    
    @scale.setter
    def scale(self, value):
        self._lfo.scale = value
    
    @property
    def offset(self):
        return self._lfo.offset
    
    @offset.setter
    def offset(self, value):
        self._lfo.offset = value
        
    @property
    def once(self):
        return self._lfo.once
    
    @once.setter
    def once(self, value):
        self._lfo.once = value
        
    @property
    def interpolate(self):
        return self._lfo.interpolate
    
    @interpolate.setter
    def interpolate(self, value):
        self._lfo.interpolate = value

class SynthioInterfaces:
    _waveform_cache = {}
    _morphed_waveform_cache = {}
    
    @staticmethod
    def midi_to_hz(note):
        return synthio.midi_to_hz(note)
    
    @staticmethod
    def create_note(**kwargs):
        try:
            if 'frequency' not in kwargs:
                raise ValueError("frequency is required")
                
            if 'waveform' in kwargs and 'waveform_loop_end' not in kwargs:
                kwargs['waveform_loop_end'] = len(kwargs['waveform'])
            
            if 'ring_waveform' in kwargs and 'ring_waveform_loop_end' not in kwargs:
                kwargs['ring_waveform_loop_end'] = len(kwargs['ring_waveform'])

            note = synthio.Note(**kwargs)
            return note
        except Exception as e:
            log(TAG_IFACE, f"Error creating note: {str(e)}", is_error=True)
            raise

    @staticmethod
    def create_envelope(**kwargs):
        try:
            for param, value in kwargs.items():
                if not isinstance(value, float):
                    raise TypeError(f"Envelope parameter {param} must be float")
            
            envelope = synthio.Envelope(**kwargs)
            return envelope
        except Exception as e:
            log(TAG_IFACE, f"Error creating envelope: {str(e)}", is_error=True)
            raise

    @staticmethod
    def create_filter(filter_type, frequency, resonance):
        try:
            mode = getattr(FilterMode, filter_type.upper())
            filter = synthio.BlockBiquad(mode=mode, frequency=frequency, Q=resonance)
            return filter
        except Exception as e:
            log(TAG_IFACE, f"Error creating filter: {str(e)}", is_error=True)
            raise

    @staticmethod
    def get_cached_waveform(waveform_type):
        if waveform_type not in SynthioInterfaces._waveform_cache:
            SynthioInterfaces._waveform_cache[waveform_type] = SynthioInterfaces.create_waveform(waveform_type, STATIC_WAVEFORM_SAMPLES)
            log(TAG_IFACE, f"Created and cached {waveform_type} waveform")
        return SynthioInterfaces._waveform_cache[waveform_type]

    @staticmethod
    def create_waveform(waveform_type, samples):
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
                    value = int((prev + curr) / 2)
                    buffer.append(value)
                    prev = curr
            else:
                raise ValueError(f"Invalid waveform type: {waveform_type}")
            
            return buffer
        except Exception as e:
            log(TAG_IFACE, f"Error creating waveform: {str(e)}", is_error=True)
            raise

    @staticmethod
    def create_synthesizer(**kwargs):
        try:
            synth = synthio.Synthesizer(**kwargs)
            return synth
        except Exception as e:
            log(TAG_IFACE, f"Error creating synthesizer: {str(e)}", is_error=True)
            raise

    @staticmethod
    def create_morphed_waveform(morph_position, waveform_sequence):
        try:
            num_transitions = len(waveform_sequence) - 1
            if num_transitions == 0:
                return SynthioInterfaces.get_cached_waveform(waveform_sequence[0])
                
            scaled_pos = morph_position * num_transitions
            transition_index = int(scaled_pos)
            
            if transition_index >= num_transitions:
                return SynthioInterfaces.get_cached_waveform(waveform_sequence[-1])
            
            waveform1 = SynthioInterfaces.get_cached_waveform(waveform_sequence[transition_index])
            waveform2 = SynthioInterfaces.get_cached_waveform(waveform_sequence[transition_index + 1])
            
            t = scaled_pos - transition_index
            
            samples = MORPHED_WAVEFORM_SAMPLES
            morphed = array.array('h')
            for i in range(samples):
                idx1 = (i * len(waveform1)) // samples
                idx2 = (i * len(waveform2)) // samples
                value = int(waveform1[idx1] * (1-t) + waveform2[idx2] * t)
                morphed.append(value)
            
            return morphed
            
        except Exception as e:
            log(TAG_IFACE, f"Error creating morphed waveform: {str(e)}", is_error=True)
            raise

    @staticmethod
    def update_amplifier_amplitude(voice_pool, amplitude):
        amplitude = max(0.001, min(1.0, amplitude))
        voice_pool.base_amplitude = amplitude
        log(TAG_IFACE, f"Updated global amplifier amplitude: {amplitude}")

class WaveformMorph:
    def __init__(self, name, waveform_sequence):
        self.name = name
        self.waveform_sequence = waveform_sequence
        self.lookup_table = []
        self._build_lookup()
        log(TAG_IFACE, f"Created waveform morph: {name}")
        
    def _build_lookup(self):
        cache_key = '-'.join(self.waveform_sequence)
        if cache_key in SynthioInterfaces._morphed_waveform_cache:
            self.lookup_table = SynthioInterfaces._morphed_waveform_cache[cache_key]
            log(TAG_IFACE, f"Using cached morph table for {cache_key}")
            return
            
        samples = MORPHED_WAVEFORM_SAMPLES
        num_transitions = len(self.waveform_sequence) - 1
        
        # Build lookup table without logging each step
        self.lookup_table = []
        for midi_value in range(128):
            morph_position = midi_value / 127.0
            self.lookup_table.append(
                SynthioInterfaces.create_morphed_waveform(
                    morph_position, 
                    self.waveform_sequence
                )
            )
            
        SynthioInterfaces._morphed_waveform_cache[cache_key] = self.lookup_table
        log(TAG_IFACE, f"Successfully created morph table for {cache_key}")
    
    def get_waveform(self, midi_value):
        if not 0 <= midi_value <= 127:
            log(TAG_IFACE, f"Invalid MIDI value {midi_value}", is_error=True)
            raise ValueError(f"MIDI value must be between 0 and 127")
        return self.lookup_table[midi_value]
