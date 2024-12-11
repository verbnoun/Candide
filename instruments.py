"""Instrument configuration management system defining synthesizer paths and parameter mappings.
"""

import sys
from logging import log, TAG_INST

VELOCITY_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

amplifier/amplitude/0.001-1/cc24

oscillator/waveform/triangle/set
'''
"""
note/amplifier/amplitude/0.001-1/velocity/note_on
amplifier/amplitude/0.001-1/cc24
amplifier/amplitude/0.5/set
"""

BASIC_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

oscillator/waveform/sine/set

filter/band_pass/resonance/0.1-2.0/cc71
filter/band_pass/frequency/20-20000/cc70

amplifier/envelope/attack_level/0.001-1/cc85
amplifier/envelope/attack_time/0.001-0.5/cc73
amplifier/envelope/decay_time/0.001-0.25/cc75
amplifier/envelope/sustain_level/0.001-1/cc66
amplifier/envelope/release_time/0.001-1/cc72
'''

PLAY_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

oscillator/waveform/triangle/set

oscillator/ring/frequency/20-2000/cc2
oscillator/ring/waveform/sine-triangle-square-saw/cc4
oscillator/ring/bend/n12-12/cc6

filter/band_pass/resonance/0.1-2.0/cc3
filter/band_pass/frequency/20-20000/cc5

amplifier/envelope/attack_level/0.001-1/cc11
amplifier/envelope/attack_time/0.001-0.5/cc13
amplifier/envelope/decay_time/0.001-0.25/cc15
amplifier/envelope/sustain_level/0.001-1/cc17
amplifier/envelope/release_time/0.001-1/cc19
'''

FILTER_MINIMUM_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

oscillator/waveform/saw/set

filter/notch/resonance/0.1-2.0/cc71
filter/notch/frequency/20-20000/cc70
'''

NOTE_MINIMUM_PATHS = '''
note/press/note_on
note/release/note_off

note/oscillator/frequency/note_number/note_on
oscillator/waveform/triangle/set
'''

SET_PATHS = '''
note/press/note_on
note/release/note_off

oscillator/frequency/220/set
oscillator/waveform/saw/set
'''

ENVELOPE_SET_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

oscillator/waveform/square/set

amplifier/envelope/attack_level/0.75/set
amplifier/envelope/attack_time/0.1/set
amplifier/envelope/decay_time/0.25/set
amplifier/envelope/sustain_level/0.3/set
amplifier/envelope/release_time/0.5/set
'''

ENVELOPE_CC_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

oscillator/waveform/sine/set

amplifier/envelope/attack_level/0.001-1/cc85
amplifier/envelope/attack_time/0.001-0.5/cc73
amplifier/envelope/decay_time/0.001-0.25/cc75
amplifier/envelope/sustain_level/0.001-1/cc66
amplifier/envelope/release_time/0.001-1/cc72
'''

MORPH_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

oscillator/waveform/sine-triangle-square-saw/cc72
'''

RING_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

oscillator/waveform/saw/set

oscillator/ring/frequency/20-2000/cc74
oscillator/ring/waveform/sine/set
oscillator/ring/bend/n12-12/cc85
'''

WAVY_PATHS = '''
note/press/note_on
note/release/note_off
note/oscillator/frequency/note_number/note_on

oscillator/waveform/sine-triangle-square-saw/cc72

oscillator/ring/frequency/20-2000/cc74
oscillator/ring/waveform/sine-triangle-square-saw/cc76
oscillator/ring/bend/n12-12/cc85
'''

class InstrumentManager:
    def __init__(self):
        self.instruments = {}
        self.instrument_order = []  # Maintain order of instruments
        self.current_instrument = None
        self.connection_manager = None
        self.synthesizer = None
        self.setup = None
        self._discover_instruments()
        log(TAG_INST, "Instrument manager initialized")

    def register_components(self, connection_manager=None, synthesizer=None):
        """Register ConnectionManager and Synthesizer components."""
        if connection_manager:
            self.connection_manager = connection_manager
            log(TAG_INST, "Registered connection manager")
            
        if synthesizer:
            self.synthesizer = synthesizer
            self.setup = synthesizer.setup  # Store setup reference
            log(TAG_INST, "Registered synthesizer and setup")
            
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
            log(TAG_INST, "No paths found for current instrument", is_error=True)
            return []
            
        cc_configs = []
        seen_ccs = set()
        
        for line in paths.strip().split('\n'):
            if not line:
                continue
                
            parts = line.strip().split('/')
            
            # Check if last part is a CC number
            if not parts[-1].startswith('cc'):
                continue
                
            try:
                cc_num = int(parts[-1][2:])  # Extract number after 'cc'
                if cc_num in seen_ccs:
                    continue
                    
                # Build parameter name based on path components
                param_name = None
                if parts[0] == 'filter':
                    param_name = f"filter_{parts[2]}"  # e.g., filter_resonance
                elif parts[0] == 'amplifier' and parts[1] == 'envelope':
                    param_name = parts[2]  # e.g., attack_time
                elif parts[0] == 'oscillator':
                    if parts[1] == 'ring':
                        param_name = f"ring_{parts[2]}"  # e.g., ring_frequency
                    elif parts[1] == 'waveform':
                        param_name = 'waveform'
                    else:
                        param_name = parts[1]  # e.g., frequency
                elif parts[0] == 'amplifier':
                    param_name = parts[1]  # e.g., amplitude
                
                if param_name:
                    cc_configs.append((cc_num, param_name))
                    seen_ccs.add(cc_num)
                    log(TAG_INST, f"Found CC mapping: cc{cc_num} -> {param_name}")
                
            except (ValueError, IndexError) as e:
                log(TAG_INST, f"Error parsing CC config line '{line}': {str(e)}", is_error=True)
                continue
                
        if not cc_configs:
            log(TAG_INST, "No CC configurations found in current instrument paths")
            
        return cc_configs

    def set_instrument(self, instrument_name):
        """Set current instrument and update components."""
        if instrument_name not in self.instruments:
            log(TAG_INST, f"Invalid instrument name: {instrument_name}", is_error=True)
            return False
            
        log(TAG_INST, f"Setting instrument to: {instrument_name}")
        self.current_instrument = instrument_name
        config_name, paths = self.instruments[instrument_name]

        # Update synthesizer configuration through setup
        if self.setup:
            log(TAG_INST, "Updating synthesizer configuration")
            self.setup.update_instrument(paths, config_name)  # Use setup directly
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
        self.setup = None
        """Clean up component references."""
        log(TAG_INST, "Cleaning up instrument manager")
        self.connection_manager = None
        self.synthesizer = None
        self.setup = None
