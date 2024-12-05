"""Instrument configuration management system defining synthesizer paths and parameter mappings."""

NOTE_MINIMUM_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/triangle/note_on
'''

FILTER_MINIMUM_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/saw/note_on

filter/band_pass/resonance/global/0.1-2.0/cc71
filter/band_pass/frequency/global/20-20000/cc70
'''

ENVELOPE_MINIMUM_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/sine/note_on

amplifier/envelope/attack_level/global/0.001-1/cc85
amplifier/envelope/attack_time/global/0.001-0.5/cc73
amplifier/envelope/decay_time/global/0.001-0.25/cc75
amplifier/envelope/sustain_level/global/0.001-1/cc66
amplifier/envelope/release_time/global/0.001-1/cc72
'''

ALL_SYNTHIO_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
note/panning/per_key/-1-1/pitch_bend

oscilator/amplitude/per_key/0.001-1/velocity/note_on
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/saw/note_on
oscillator/bend/per_key/-12-12/pitch_bend
oscillator/ring/frequency/global/20-2000/cc74
oscillator/ring/waveform/global/triangle/note_on
oscillator/ring/bend/per_key/-12-12/pitch_bend

filter/band_pass/resonance/global/0.1-2.0/cc71
filter/band_pass/frequency/global/20-20000/cc70

amplifier/envelope/attack_level/per_key/0.001-1/velocity/note_on
amplifier/envelope/attack_time/global/0.001-0.5/cc73
amplifier/envelope/decay_time/global/0.001-0.25/cc75
amplifier/envelope/sustain_level/per_key/0-1/pressure
amplifier/envelope/release_time/global/0.001-3/cc72

lfo/rate/tremolo_lfo/global/0.1-10/cc102
lfo/scale/tremolo_lfo/global/0-1/cc103
lfo/offset/tremolo_lfo/global/-1-1/cc104
lfo/phase_offset/tremolo_lfo/global/0-1/cc105
lfo/once/tremolo_lfo/global/0-1/cc106
lfo/interpolate/tremolo_lfo/global/0-1/cc107
'''

class InstrumentManager:
    def __init__(self):
        self.instruments = {}
        self.current_instrument = None
        self._discover_instruments()

    def _discover_instruments(self):
        self.instruments.clear()
        
        import sys
        current_module = sys.modules[__name__]
        for name in dir(current_module):
            if name.endswith('_PATHS'):
                instrument_name = name[:-6].lower()
                paths = getattr(current_module, name)
                if isinstance(paths, str):
                    self.instruments[instrument_name] = paths
        
        if not self.instruments:
            raise RuntimeError("No instruments found in config")
            
        if not self.current_instrument:
            self.current_instrument = next(iter(self.instruments))

    def set_instrument(self, instrument_name):
        try:
            if instrument_name not in self.instruments:
                return False
            
            self.current_instrument = instrument_name
            return True
            
        except Exception as e:
            return False

    def get_current_config(self):
        return self.instruments.get(self.current_instrument)

    def get_available_instruments(self):
        return list(self.instruments.keys())
