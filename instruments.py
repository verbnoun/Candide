"""Instrument configuration management system defining synthesizer paths and parameter mappings.
"""

import sys
from logging import log, TAG_INST

NOTE_MINIMUM_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/square/note_on
'''

FILTER_MINIMUM_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/saw/note_on

filter/high_pass/resonance/global/0.1-2.0/cc71
filter/high_pass/frequency/global/20-20000/cc70
'''

ENVELOPE_MINIMUM_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/morph/global/sine-triangle-square-saw/cc2

amplifier/envelope/attack_level/global/0.001-1/cc85
amplifier/envelope/attack_time/global/0.001-0.5/cc73
amplifier/envelope/decay_time/global/0.001-0.25/cc75
amplifier/envelope/sustain_level/global/0.001-1/cc66
amplifier/envelope/release_time/global/0.001-1/cc72
'''

PUSH_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/morph/global/sine-triangle-square-saw/cc72

'''

PLAY_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off

oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/triangle/note_on

oscillator/ring/frequency/global/20-2000/cc2
oscillator/ring/waveform/morph/global/sine-triangle-square-saw/cc4
oscillator/ring/bend/global/n12-12/cc6

filter/band_pass/resonance/global/0.1-2.0/cc3
filter/band_pass/frequency/global/20-20000/cc5

amplifier/envelope/attack_level/global/0.001-1/cc11
amplifier/envelope/attack_time/global/0.001-0.5/cc13
amplifier/envelope/decay_time/global/0.001-0.25/cc15
amplifier/envelope/sustain_level/global/0.001-1/cc17
amplifier/envelope/release_time/global/0.001-1/cc19
'''

WAVY_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/morph/global/sine-triangle-square-saw/cc72

oscillator/ring/frequency/global/20-2000/cc74
oscillator/ring/waveform/morph/global/sine-triangle-square-saw/cc76
oscillator/ring/bend/global/n12-12/cc85
'''

RING_PATHS = '''
note/press/per_key/note_on
note/release/per_key/note_off
oscillator/frequency/per_key/note_number/note_on
oscillator/waveform/global/saw/note_on

oscillator/ring/frequency/global/20-2000/cc74
oscillator/ring/waveform/global/sine/note_on
oscillator/ring/bend/global/n12-12/cc85
'''

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

class InstrumentManager:
    def __init__(self):
        self.instruments = {}
        self.instrument_order = []  # Maintain order of instruments
        self.current_instrument = None
        self.connection_manager = None
        self.synthesizer = None
        self._discover_instruments()
        log(TAG_INST, "Instrument manager initialized")

    def register_components(self, connection_manager=None, synthesizer=None):
        """Register ConnectionManager and Synthesizer components."""
        if connection_manager:
            self.connection_manager = connection_manager
            log(TAG_INST, "Registered connection manager")
            
        if synthesizer:
            self.synthesizer = synthesizer
            log(TAG_INST, "Registered synthesizer")
            
        # Register connection manager's callback with synthesizer
        if self.synthesizer and self.connection_manager:
            self.synthesizer.register_ready_callback(self.connection_manager.on_synth_ready)
            log(TAG_INST, "Connected synth ready callback")

    def _discover_instruments(self):
        """Discover available instruments from module constants."""
        self.instruments.clear()
        self.instrument_order.clear()
        
        import sys
        current_module = sys.modules[__name__]
        
        # Find all instrument paths in order of definition
        for name in dir(current_module):
            if name.endswith('_PATHS'):
                instrument_name = name[:-6].lower()
                paths = getattr(current_module, name)
                if isinstance(paths, str):
                    self.instruments[instrument_name] = (name, paths)  # Store both name and paths
                    self.instrument_order.append(instrument_name)
        
        if not self.instruments:
            raise RuntimeError("No instruments found in config")
            
        # Always select the first instrument in order
        if not self.current_instrument or self.current_instrument not in self.instruments:
            self.current_instrument = self.instrument_order[0]
            
        log(TAG_INST, f"Discovered instruments in order: {', '.join(self.instrument_order)}")

    def get_current_cc_configs(self):
        """Get all CC numbers and parameter names for the current instrument."""
        config_name, paths = self.instruments.get(self.current_instrument, (None, None))
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
            log(TAG_INST, f"Invalid instrument name: {instrument_name}", is_error=True)
            return False
            
        log(TAG_INST, f"Setting instrument to: {instrument_name}")
        self.current_instrument = instrument_name
        config_name, paths = self.instruments[instrument_name]

        # Update synthesizer configuration
        if self.synthesizer:
            log(TAG_INST, "Updating synthesizer configuration")
            self.synthesizer.update_instrument(paths, config_name)  # Pass config_name to update_instrument
            # Synthesizer will signal ready to connection manager
            return True
            
        return False

    def get_current_config(self):
        """Get the current instrument's configuration paths."""
        return self.instruments.get(self.current_instrument, (None, None))[1]

    def get_available_instruments(self):
        """Get list of available instrument names in order."""
        return self.instrument_order.copy()

    def get_next_instrument(self):
        """Get the next instrument in the ordered list."""
        if not self.current_instrument or not self.instrument_order:
            return None
            
        current_index = self.instrument_order.index(self.current_instrument)
        next_index = (current_index + 1) % len(self.instrument_order)
        return self.instrument_order[next_index]

    def cleanup(self):
        """Clean up component references."""
        log(TAG_INST, "Cleaning up instrument manager")
        self.connection_manager = None
        self.synthesizer = None
