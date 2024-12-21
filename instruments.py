"""Instrument configuration management system defining synthesizer paths and parameter mappings."""

import sys
import time
from logging import log, TAG_INST
from router import get_router

TEST_PATHS = '''
# Note handling
channel/press_note/note_on
channel/release_note/note_off
channel/frequency/note_number/note_on


# Base waveform
synth/waveform/triangle

synth/filter_frequency:band_pass/220-2000/cc21
synth/filter_resonance:band_pass/0.01-1/cc33

'''

"""


channel/amplitude/0.001-1/pressure

# Basic Value Modulator LFO (Tremolo)
synth/lfo/rate/tremolo:0.1-10/cc77
synth/lfo/scale/tremolo:0-1/cc75
synth/lfo/offset/tremolo:0.5
synth/amplitude/lfo:tremolo

# synth/ring_waveform/sine|triangle|square|saw/cc78


channel/bend/n0.01-0.01/pitch_bend
channel/amplitude/0.1-1/pressure

## working
channel/amplitude/0.001-1/velocity

# Filter
synth/filter_frequency:band_pass/220-2000/cc21
synth/filter_resonance:band_pass/0.01-1/cc33

# Ring modulation
synth/ring_frequency/2-22/cc22
synth/ring_waveform/sine-triangle-square-saw/cc78
synth/ring_bend/n1-1/cc86

"""

LFO_PATHS = '''

'''

"""
# Basic Value Modulator LFO (Tremolo)
synth/lfo/rate/tremolo:0.1-10/cc74      # 0.1-10 Hz oscillation
synth/lfo/scale/tremolo:0-1/cc75        # Depth of effect
synth/lfo/offset/tremolo:0.5            # Center at 0.5 amplitude
synth/amplitude/lfo:tremolo         # Connect to amplitude

# One-Shot Fade LFO (Slow Attack)
synth/lfo/once/fade:true                # One-time execution
synth/lfo/rate/fade:0.5                 # Complete over 2 seconds
synth/lfo/scale/fade:1                  # Full range
synth/lfo/waveform/fade:ramp            # Linear ramp
synth/amplitude/lfo:fade            # Target amplitude

# Stepped LFO (Arpeggiator-style)
synth/lfo/interpolate/step:false        # No smoothing
synth/lfo/rate/step:4                   # 4 Hz for quarter notes
synth/lfo/scale/step:12                 # Octave range
synth/lfo/waveform/step:square          # Sharp steps
synth/bend/lfo:step                 # Affect pitch

# Phase-shifted LFO (Vibrato with delay)
synth/lfo/rate/vib:6                    # 6 Hz vibrato
synth/lfo/scale/vib:0.2                 # Small pitch variation
synth/lfo/phase_offset/vib:0.5          # Start halfway through
synth/bend/lfo:vib                  # Connect to pitch bend

# Complex waveform LFO (Custom envelope)
synth/lfo/waveform/env:custom-shape     # Custom waveform
synth/lfo/loop_start/env:0              # Full waveform
synth/lfo/loop_end/env:64               # Use all points
synth/lfo/once/env:true                 # Play once
synth/filter_frequency:low_pass/lfo:env      # Swept filter

# Per-channel LFO examples with MIDI targeting:

# Channel vibrato (bend) triggered by aftertouch (pressure)
channel/lfo/rate/vib_ch:6               # Fixed 6Hz
channel/lfo/scale/vib_ch:0-0.2/pressure # Depth controlled by pressure
channel/lfo/waveform/vib_ch:sine
channel/bend/lfo:vib_ch

# Channel tremolo with CC control
channel/lfo/rate/trem_ch:0.1-10/cc73    # Rate controlled by CC73  
channel/lfo/scale/trem_ch:0-1/cc74      # Depth controlled by CC74
channel/amplitude/lfo:trem_ch

# Channel filter sweep (one-shot triggered by note-on)
channel/lfo/once/sweep_ch:true
channel/lfo/rate/sweep_ch:0.5  
channel/lfo/scale/sweep_ch:500-2000/velocity # Range based on note velocity
channel/lfo/waveform/sweep_ch:ramp
channel/filter_frequency:high_pass/lfo:sweep_ch

# Channel ring mod with pitch bend depth
channel/lfo/rate/ring_ch:1-20/cc75
channel/lfo/scale/ring_ch:0-100/pitch_bend
channel/ring_frequency/lfo:ring_ch

# LFO CONFIGURATION SCHEMA
# SCOPE/lfo/[parameter]/[name]:[value or range]/[midi_trigger (optional)]

Parameters:
- rate        : 0.1-1000 Hz  (speed of oscillation)
- scale       : float        (depth/amplitude)
- offset      : -1 to 1      (center point)
- phase_offset: 0 to 1       (start position)
- once        : true/false   (one-shot vs continuous)
- interpolate : true/false   (smooth vs stepped)
- waveform    : string or buffer name
- loop_start  : 0 to len-1   (waveform loop point)
- loop_end    : start+1 to len

# CONNECTING LFO TO TARGET
# synth/[target]/lfo:[name]

# Note: Target must be a valid BlockInput parameter:
# - amplitude, bend, panning
# - filter values
# - ring mod values
# - other LFO parameters (can chain)

"""

RICH_SAW_PATHS = '''
# Note handling
channel/press_note/note_on
channel/release_note/note_off
channel/frequency/note_number/note_on

# Base waveform
synth/waveform/saw

# Ring modulation for harmonic richness
synth/ring_frequency/2-22/cc22
synth/ring_waveform/triangle

# Dynamic amplitude control
channel/amplitude/0.1-1/pressure

# Envelope shaping
synth/envelope:attack_time/0.05
synth/envelope:attack_level/1
synth/envelope:decay_time/0.5
synth/envelope:sustain_level/0.5
synth/envelope:release_time/2

# Filter for tone shaping
synth/filter_frequency:low_pass/200-2000/pressure
synth/filter_resonance:low_pass/0.1-2/cc22

'''

NOTE_PATHS = '''
# Note handling
channel/press_note/note_on
channel/release_note/note_off
channel/frequency/note_number/note_on

# Amplitude control
channel/amplitude/0.001-1/velocity
channel/amplitude/0.001-1/pressure

'''

"""
# Additional amplitude controls
channel/amplitude/0.001-1/velocity
channel/ring_bend/n1-1/pitch_bend
channel/bend/n1-1/pitch_bend

# Pressure and CC control
channel/amplitude/0.001-1/pressure
synth/amplitude/0.001-1/cc24
"""

OSCILLATOR_PATHS = '''
# Note handling
channel/press_note/note_on
channel/release_note/note_off

channel/amplitude/0.01-1/velocity

# Basic oscillator control
channel/frequency/note_number/note_on
synth/waveform/sine-triangle-square-saw/cc72

synth/ring_frequency/0.001-10/cc23
synth/ring_waveform/sine-triangle-square-saw/cc78
'''

"""
# Frequency control
synth/frequency/130.81-523.25/cc74
synth/frequency/220

# Waveform control
synth/waveform/saw
synth/waveform/sine
synth/waveform/triangle
synth/waveform/square
synth/waveform/noise
synth/waveform/white_noise

# Waveform morphing
synth/waveform/sine-triangle-square-saw/cc72

# Bend control
channel/bend/n1-1/pitch_bend
synth/bend/n12-12/cc85
synth/bend/n2

# Ring modulation
synth/ring_frequency/0.5-2000/cc76
synth/ring_frequency/440

synth/ring_waveform/sine
synth/ring_waveform/sine-triangle-square-saw/cc78

channel/ring_bend/n1-1/pitch_bend
synth/ring_bend/n12-12/cc85
synth/ring_bend/n2
"""

BASIC_PATHS = '''
# Note handling
channel/press_note/note_on
channel/release_note/note_off
channel/frequency/note_number/note_on

# Basic waveform
synth/waveform/sine

channel/amplitude/0.6

synth/panning/n1-1/cc24

'''

"""
synth/ring_frequency/1
synth/ring_waveform/sine
channel/ring_bend/n12-12/pitch_bend

channel/amplitude/0.7
channel/panning/n1-1/pitch_bend

synth/panning/n1-1/cc24

channel/bend/n0.1-0.1/pitch_bend

channel/amplitude/0.001-1/pressure

# Filter control
synth/filter_frequency:high_pass/20-20000/cc70
synth/filter_resonance:high_pass/0.1-2.0/cc71
# Envelope control
synth/envelope:attack_level/0.001-1/cc85
synth/envelope:attack_time/0.001-0.5/cc73
synth/envelope:decay_time/0.001-0.25/cc75
synth/envelope:sustain_level/0.001-1/cc66
synth/envelope:release_time/0.001-1/cc72

"""
AMPLIFIER_PATHS = '''
# Note handling
channel/press_note/note_on
channel/release_note/note_off
channel/frequency/note_number/note_on

# Amplitude control
channel/amplitude/0.001-1/velocity

# Basic waveform
synth/waveform/saw
'''

"""
# Additional amplitude controls
channel/amplitude/0.001-1/velocity
synth/amplitude/0.001-1/cc24
synth/amplitude/0.3
"""

ENVELOPE_PATHS = '''
# Note handling
channel/press_note/note_on
channel/release_note/note_off
channel/frequency/note_number/note_on

# Basic waveform
synth/waveform/sine

# Envelope control
synth/envelope:attack_level/0.001-1/cc85
synth/envelope:attack_time/0.001-0.5/cc73
synth/envelope:decay_time/0.001-0.25/cc75
synth/envelope:sustain_level/0.001-1/cc66
synth/envelope:release_time/0.001-1/cc72
'''

"""
# Set envelope values
synth/envelope:attack_level/0.75
synth/envelope:attack_time/0.1
synth/envelope:decay_time/0.25
synth/envelope:sustain_level/0.3
synth/envelope:release_time/0.5
"""

FILTER_PATHS = '''
# Note handling
channel/press_note/note_on
channel/release_note/note_off
channel/frequency/note_number/note_on

# Basic waveform
synth/waveform/saw

# Filter control
synth/filter_frequency:notch/20-20000/cc70
synth/filter_resonance:notch/0.1-2.0/cc71
'''

"""
# Filter types with explicit filter names
synth/filter_frequency:low_pass/20-20000/cc70
synth/filter_resonance:low_pass/0.1-2.0/cc71

synth/filter_frequency:high_pass/20-20000/cc70
synth/filter_resonance:high_pass/0.1-2.0/cc71

synth/filter_frequency:band_pass/20-20000/cc70
synth/filter_resonance:band_pass/0.1-2.0/cc71
"""

class InstrumentStateMachine:
    """Manages instrument setting state and pot value tracking."""
    def __init__(self, connection_manager):
        self.state = 'set'  # States: 'set' or 'changing'
        self.connection_manager = connection_manager
        self.expected_pots = set()  # Set of pot numbers we're waiting for
        self.received_pots = set()  # Set of pot numbers we've received
        self.waiting_for_cc127 = False
        self.midi_subscription = None  # MIDI subscription for CC messages
        self.midi_interface = None  # Reference to current MIDI interface
        self.connection_callback = None  # Callback for notifying connection state changes
        self.pot_to_cc_map = {}  # Map of pot numbers to CC numbers
        self.last_midi_time = 0  # Track when we last received MIDI
        
    def set_connection_callback(self, callback):
        """Set callback for connection state changes."""
        self.connection_callback = callback
        
    def on_config_sent(self, config_string, midi_interface):
        """Called when a new config is sent."""
        self.state = 'changing'
        log(TAG_INST, "Instrument state: changing")
        self.received_pots.clear()
        self.midi_interface = midi_interface
        self.pot_to_cc_map.clear()
        self.last_midi_time = 0  # Reset MIDI timing
        
        # Clean up any existing subscription
        if self.midi_subscription:
            self.midi_interface.unsubscribe(self.midi_subscription)
            self.midi_subscription = None
        
        if not config_string or config_string == "cc|":
            # Empty config - wait for CC127:0
            self.waiting_for_cc127 = True
            self.expected_pots.clear()
            log(TAG_INST, "Waiting for CC127:0")
            self.midi_subscription = midi_interface.subscribe(
                self._handle_midi_message,
                message_types=['cc'],
                cc_numbers={127}
            )
        else:
            # Parse config string to get expected pots
            self.waiting_for_cc127 = False
            self.expected_pots = set()
            parts = config_string.split('|')
            if len(parts) > 3:  # Has pot mappings
                for mapping in parts[3:]:
                    if '=' in mapping:
                        pot_num = int(mapping.split('=')[0])
                        cc_num = int(mapping.split('=')[1].split(':')[0])
                        self.expected_pots.add(pot_num)
                        self.pot_to_cc_map[cc_num] = pot_num
                # Subscribe to mapped CCs
                cc_numbers = set(self.pot_to_cc_map.keys())
                self.midi_subscription = midi_interface.subscribe(
                    self._handle_midi_message,
                    message_types=['cc'],
                    cc_numbers=cc_numbers
                )
                log(TAG_INST, f"Waiting for pots: {self.expected_pots}")
                log(TAG_INST, f"CC to pot mapping: {self.pot_to_cc_map}")
    
    def _handle_midi_message(self, msg):
        """Handle MIDI CC messages while in changing state."""
        if self.state == 'changing' and msg.type == 'cc':
            self.last_midi_time = time.monotonic()  # Update last MIDI time
            if self.waiting_for_cc127:
                if msg.control == 127 and msg.value == 0:
                    log(TAG_INST, "Received CC127:0")
                    # Send confirmation
                    if self.connection_manager:
                        self.connection_manager.uart.write("⚡\n")
                        log(TAG_INST, "Sent confirmation ⚡")
                    self._complete_change()
            else:
                # Check if this CC corresponds to a pot we're waiting for
                if msg.control in self.pot_to_cc_map:
                    pot_num = self.pot_to_cc_map[msg.control]
                    if pot_num not in self.received_pots:
                        log(TAG_INST, f"Received value for pot {pot_num} (CC {msg.control})")
                        self.received_pots.add(pot_num)
                        if self.received_pots == self.expected_pots:
                            # Send confirmation
                            if self.connection_manager:
                                self.connection_manager.uart.write("⚡\n")
                                log(TAG_INST, "Sent confirmation ⚡")
                            self._complete_change()
    
    def has_received_midi(self):
        """Check if we've received any MIDI since last config."""
        return self.last_midi_time > 0
    
    def _complete_change(self):
        """Complete the instrument change process."""
        self.state = 'set'
        # Unsubscribe from MIDI messages
        if self.midi_subscription and self.midi_interface:
            self.midi_interface.unsubscribe(self.midi_subscription)
            self.midi_subscription = None
        log(TAG_INST, "Received all expected values from base station")
        log(TAG_INST, f"Instrument state: {self.state}")
        
        # Notify connection manager of state change
        if self.connection_callback:
            self.connection_callback(self.state)

    def reset(self):
        """Reset state machine on disconnection."""
        log(TAG_INST, "Resetting instrument state machine")
        self.state = 'set'
        self.received_pots.clear()
        self.expected_pots.clear()
        self.waiting_for_cc127 = False
        self.pot_to_cc_map.clear()
        self.last_midi_time = 0  # Reset MIDI timing
        
        # Clean up any existing subscription
        if self.midi_subscription and self.midi_interface:
            self.midi_interface.unsubscribe(self.midi_subscription)
            self.midi_subscription = None
            self.midi_interface = None

class InstrumentManager:
    def __init__(self):
        self.instruments = {}
        self.instrument_order = []  # Maintain order of instruments
        self.current_instrument = None
        self._observers = []  # List of observers for instrument changes
        self.current_cc_config = None  # Cache for current CC config
        self.state_machine = None  # Set when connection manager is available
        self._discover_instruments()
        log(TAG_INST, "Instrument manager initialized")

    def set_connection_manager(self, connection_manager):
        """Set connection manager and initialize state machine."""
        self.state_machine = InstrumentStateMachine(connection_manager)

    def add_observer(self, observer):
        """Add an observer to be notified of instrument changes."""
        self._observers.append(observer)
        
    def remove_observer(self, observer):
        """Remove an observer."""
        if observer in self._observers:
            self._observers.remove(observer)

    def _notify_instrument_change(self, instrument_name, config_name, paths):
        """Notify observers of instrument change."""
        for observer in self._observers:
            observer.on_instrument_change(instrument_name, config_name, paths)

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
        """Update cached CC configuration from current paths."""
        if self.current_instrument:
            config_name, paths = self.instruments[self.current_instrument]
            router = get_router()
            router.parse_paths(paths, config_name)
            self.current_cc_config = router.get_cc_configs()
        else:
            self.current_cc_config = []

    def get_current_cc_configs(self):
        """Get cached CC configurations for the current instrument."""
        return self.current_cc_config if self.current_cc_config is not None else []

    def set_instrument(self, instrument_name):
        """Set current instrument and notify observers."""
        if instrument_name not in self.instruments:
            log(TAG_INST, f"Invalid instrument name: {instrument_name}", is_error=True)
            return False
            
        log(TAG_INST, f"Setting instrument to: {instrument_name}")
        self.current_instrument = instrument_name
        config_name, paths = self.instruments[instrument_name]

        # Update CC config cache
        self._update_cc_config()
        
        # Notify observers of change
        self._notify_instrument_change(instrument_name, config_name, paths)
        return True

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
        self._observers.clear()
        self.current_cc_config = None
        if self.state_machine and self.state_machine.midi_subscription:
            self.state_machine.midi_interface.unsubscribe(self.state_machine.midi_subscription)
        self.state_machine = None
