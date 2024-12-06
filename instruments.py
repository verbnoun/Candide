"""Instrument configuration management system defining synthesizer paths and parameter mappings."""

import sys
from constants import LOG_INST, LOG_LIGHT_YELLOW, LOG_RED, LOG_RESET

def _log(message, is_error=False):
    """Simple logging function for instrument events."""
    color = LOG_RED if is_error else LOG_LIGHT_YELLOW
    if is_error:
        print(f"{color}{LOG_INST} [ERROR] {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{LOG_INST} {message}{LOG_RESET}", file=sys.stderr)

BASIC_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/sine/note_on

filter/band_pass/resonance/global/0.1-2.0/cc71
filter/band_pass/frequency/global/20-20000/cc70

amplifier/envelope/attack_level/global/0.001-1/cc85
amplifier/envelope/attack_time/global/0.001-0.5/cc73
amplifier/envelope/decay_time/global/0.001-0.25/cc75
amplifier/envelope/sustain_level/global/0.001-1/cc66
amplifier/envelope/release_time/global/0.001-1/cc72
'''

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
        self.connection_manager = None
        self.synthesizer = None
        self._discover_instruments()
        _log("Instrument manager initialized")

    def register_components(self, connection_manager=None, synthesizer=None):
        """Register ConnectionManager and Synthesizer components."""
        if connection_manager:
            self.connection_manager = connection_manager
            _log("Registered connection manager")
            
        if synthesizer:
            self.synthesizer = synthesizer
            _log("Registered synthesizer")
            
        # Register connection manager's callback with synthesizer
        if self.synthesizer and self.connection_manager:
            self.synthesizer.register_ready_callback(self.connection_manager.on_synth_ready)
            _log("Connected synth ready callback")

    def _discover_instruments(self):
        """Discover available instruments from module constants."""
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
            
        _log(f"Discovered instruments: {', '.join(self.instruments.keys())}")

    def get_current_cc_configs(self):
        """Get all CC numbers and parameter names for the current instrument."""
        paths = self.get_current_config()
        if not paths:
            return []
            
        cc_configs = []
        seen_ccs = set()
        
        for line in paths.strip().split('\n'):
            if not line:
                continue
                
            parts = line.strip().split('/')
            
            # Check all parts for CC numbers
            cc_part = None
            for part in parts:
                if part.startswith('cc'):
                    cc_part = part
                    break
                    
            if not cc_part:
                continue
                
            try:
                cc_num = int(cc_part[2:])  # Extract number after 'cc'
                if cc_num not in seen_ccs:
                    # Find parameter name (part before global/per_key)
                    param_name = None
                    for i, part in enumerate(parts):
                        if part in ('global', 'per_key'):
                            if i > 0:
                                param_name = parts[i-1]
                            break
                    
                    if param_name:
                        cc_configs.append((cc_num, param_name))
                        seen_ccs.add(cc_num)
            except ValueError:
                continue
                
        return cc_configs

    def set_instrument(self, instrument_name):
        """Set current instrument and update components."""
        if instrument_name not in self.instruments:
            _log(f"Invalid instrument name: {instrument_name}", is_error=True)
            return False
            
        _log(f"Setting instrument to: {instrument_name}")
        self.current_instrument = instrument_name
        paths = self.get_current_config()

        # Update synthesizer configuration
        if self.synthesizer:
            _log("Updating synthesizer configuration")
            self.synthesizer.update_instrument(paths)
            # Synthesizer will signal ready to connection manager
            return True
            
        return False

    def get_current_config(self):
        """Get the current instrument's configuration paths."""
        return self.instruments.get(self.current_instrument)

    def get_available_instruments(self):
        """Get list of available instrument names."""
        return list(self.instruments.keys())

    def cleanup(self):
        """Clean up component references."""
        _log("Cleaning up instrument manager")
        self.connection_manager = None
        self.synthesizer = None
