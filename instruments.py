"""Instrument configuration management system defining synthesizer paths and parameter mappings."""

import sys
from logging import log, TAG_INST
from router import PathParser

OSCILLATOR_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off

# Basic oscillator control
synth/set_frequency/130.81-523.25/cc74
synth/set_waveform/triangle
'''
"""
# Frequency control
synth/set_frequency/130.81-523.25/cc74
synth/set_frequency/220

# Waveform control
synth/set_waveform/saw
synth/set_waveform/sine
synth/set_waveform/triangle
synth/set_waveform/square
synth/set_waveform/noise
synth/set_waveform/white_noise

# Waveform morphing
synth/set_waveform/sine-triangle-square-saw/cc72

# Bend control
channel/set_bend/n1-1/pitch_bend
synth/set_bend/n12-12/cc85
synth/set_bend/n2

# Ring modulation
synth/set_ring_frequency/0.5-2000/cc76
synth/set_ring_frequency/440

synth/set_ring_waveform/sine
synth/set_ring_waveform/sine-triangle-square-saw/cc78

channel/set_ring_bend/n1-1/pitch_bend
synth/set_ring_bend/n12-12/cc85
synth/set_ring_bend/n2
"""

ENVELOPE_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/0-127/note_number

# Basic waveform
synth/set_waveform/sine

# Envelope control
synth/set_envelope_param/attack_level/0.001-1/cc85
synth/set_envelope_param/attack_time/0.001-0.5/cc73
synth/set_envelope_param/decay_time/0.001-0.25/cc75
synth/set_envelope_param/sustain_level/0.001-1/cc66
synth/set_envelope_param/release_time/0.001-1/cc72
'''
"""
# Set envelope values
synth/set_envelope_param/attack_level/0.75
synth/set_envelope_param/attack_time/0.1
synth/set_envelope_param/decay_time/0.25
synth/set_envelope_param/sustain_level/0.3
synth/set_envelope_param/release_time/0.5
"""

FILTER_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/0-127/note_number

# Basic waveform
synth/set_waveform/saw

# Filter control
synth/set_synth_filter_notch_frequency/20-20000/cc70
synth/set_synth_filter_notch_resonance/0.1-2.0/cc71
'''
"""
# Filter types with explicit filter names
synth/set_synth_filter_low_pass_frequency/20-20000/cc70
synth/set_synth_filter_low_pass_resonance/0.1-2.0/cc71

synth/set_synth_filter_high_pass_frequency/20-20000/cc70
synth/set_synth_filter_high_pass_resonance/0.1-2.0/cc71

synth/set_synth_filter_band_pass_frequency/20-20000/cc70
synth/set_synth_filter_band_pass_resonance/0.1-2.0/cc71
"""

NOTE_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/0-127/note_number

# Amplitude control
channel/set_amplitude/0.001-1/pressure
'''
"""
# Additional amplitude controls
channel/set_amplitude/0.001-1/velocity
channel/set_ring_bend/n1-1/pitch_bend
channel/set_bend/n1-1/pitch_bend

# Pressure and CC control
channel/set_amplitude/0.001-1/pressure
synth/set_amplitude/0.001-1/cc24
"""

AMPLIFIER_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/0-127/note_number

# Amplitude control
channel/set_amplitude/0.001-1/velocity

# Basic waveform
synth/set_waveform/saw
'''
"""
# Additional amplitude controls
channel/set_amplitude/0.001-1/velocity
synth/set_amplitude/0.001-1/cc24
synth/set_amplitude/0.3
"""

BASIC_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/0-127/note_number

# Basic waveform
synth/set_waveform/saw

# Filter control
synth/set_synth_filter_high_pass_frequency/20-20000/cc70
synth/set_synth_filter_high_pass_resonance/0.1-2.0/cc71

# Envelope control
synth/set_envelope_param/attack_level/0.001-1/cc85
synth/set_envelope_param/attack_time/0.001-0.5/cc73
synth/set_envelope_param/decay_time/0.001-0.25/cc75
synth/set_envelope_param/sustain_level/0.001-1/cc66
synth/set_envelope_param/release_time/0.001-1/cc72
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
            
        # Create temporary PathParser to get CC configs
        parser = PathParser()
        parser.parse_paths(paths, config_name)
        return parser.get_cc_configs()

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
