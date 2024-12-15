"""Instrument configuration management system defining synthesizer paths and parameter mappings."""

import sys
from logging import log, TAG_INST
from router import PathParser

RICH_SAW_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/note_number/note_on

# Base waveform
synth/set_waveform/saw

# Ring modulation for harmonic richness
synth/set_ring_frequency/2-22/cc22
synth/set_ring_waveform/triangle

# Dynamic amplitude control
channel/set_amplitude/0.001-1/velocity
channel/set_amplitude/0.001-1/pressure

# Envelope shaping
synth/set_envelope_attack_time/0.05
synth/set_envelope_attack_level/1
synth/set_envelope_decay_time/0.2
synth/set_envelope_sustain_level/1
synth/set_envelope_release_time/0.5

# Filter for tone shaping
synth/set_synth_filter_low_pass_frequency/200-2000/cc23
synth/set_synth_filter_low_pass_resonance/1.2-5/cc24
'''

WORKING_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/note_number/note_on

channel/set_amplitude/0.1-1/pressure


# Envelope control
synth/set_envelope_attack_level/0.3-1/velocity
synth/set_envelope_attack_time/0.001-0.5/cc73
synth/set_envelope_decay_time/0.001-0.25/cc75
synth/set_envelope_sustain_level/0.001-1/cc66
synth/set_envelope_release_time/0.001-2/cc72

'''

NOTE_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/note_number/note_on

# Amplitude control
channel/set_amplitude/0.001-1/velocity
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

OSCILLATOR_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off

channel/set_amplitude/0.01-1/release_velocity

# Basic oscillator control
channel/set_frequency/note_number/note_on
synth/set_waveform/sine-triangle-square-saw/cc72

synth/set_ring_frequency/0.001-10/cc23
synth/set_ring_waveform/sine-triangle-square-saw/cc78
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

BASIC_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/note_number/note_on

# Basic waveform
synth/set_waveform/sine

channel/set_amplitude/0.6

synth/set_panning/n1-1/cc24

'''
"""
synth/set_ring_frequency/1
synth/set_ring_waveform/sine
channel/set_ring_bend/n12-12/pitch_bend

channel/set_amplitude/0.7
channel/set_panning/n1-1/pitch_bend

synth/set_panning/n1-1/cc24

channel/set_bend/n0.1-0.1/pitch_bend

channel/set_amplitude/0.001-1/pressure

# Filter control
synth/set_synth_filter_high_pass_frequency/20-20000/cc70
synth/set_synth_filter_high_pass_resonance/0.1-2.0/cc71
# Envelope control
synth/set_envelope_attack_level/0.001-1/cc85
synth/set_envelope_attack_time/0.001-0.5/cc73
synth/set_envelope_decay_time/0.001-0.25/cc75
synth/set_envelope_sustain_level/0.001-1/cc66
synth/set_envelope_release_time/0.001-1/cc72

"""
AMPLIFIER_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/note_number/note_on

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




ENVELOPE_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/note_number/note_on

# Basic waveform
synth/set_waveform/sine

# Envelope control
synth/set_envelope_attack_level/0.001-1/cc85
synth/set_envelope_attack_time/0.001-0.5/cc73
synth/set_envelope_decay_time/0.001-0.25/cc75
synth/set_envelope_sustain_level/0.001-1/cc66
synth/set_envelope_release_time/0.001-1/cc72
'''
"""
# Set envelope values
synth/set_envelope_attack_level/0.75
synth/set_envelope_attack_time/0.1
synth/set_envelope_decay_time/0.25
synth/set_envelope_sustain_level/0.3
synth/set_envelope_release_time/0.5
"""

FILTER_PATHS = '''
# Note handling
channel/press_voice/note_on
channel/release_voice/note_off
channel/set_frequency/note_number/note_on

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



class InstrumentManager:
    def __init__(self):
        self.instruments = {}
        self.instrument_order = []  # Maintain order of instruments
        self.current_instrument = None
        self.connection_manager = None
        self.synthesizer = None
        self.setup = None
        self.current_cc_config = None  # Cache for current CC config
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
            
            # Register ready callback to send new CC config when instrument changes
            if self.connection_manager:
                self.synthesizer.register_ready_callback(
                    lambda: self.connection_manager.send_config()
                )
                log(TAG_INST, "Connected synth ready callback for CC config updates")

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

    def _update_cc_config(self):
        """Update cached CC configuration from current synth state."""
        if self.synthesizer and self.synthesizer.path_parser:
            self.current_cc_config = self.synthesizer.path_parser.get_cc_configs()
        else:
            self.current_cc_config = []

    def get_current_cc_configs(self):
        """Get cached CC configurations for the current instrument."""
        return self.current_cc_config if self.current_cc_config is not None else []

    def set_instrument(self, instrument_name):
        """Set current instrument and update components."""
        if instrument_name not in self.instruments:
            log(TAG_INST, f"Invalid instrument name: {instrument_name}", is_error=True)
            return False
            
        log(TAG_INST, f"Setting instrument to: {instrument_name}")
        self.current_instrument = instrument_name
        config_name, paths = self.instruments[instrument_name]

        # Update synthesizer configuration through setup first
        if self.setup:
            log(TAG_INST, "Updating synthesizer configuration")
            self.setup.update_instrument(paths, config_name)  # Use setup directly
            # After synth is updated, get CC config from its parsed paths
            self._update_cc_config()
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
        self.current_cc_config = None
