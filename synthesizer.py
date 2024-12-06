"""Synthesizer module for handling MIDI input and audio synthesis."""

from adafruit_midi.note_on import NoteOn 
from adafruit_midi.note_off import NoteOff
from adafruit_midi.control_change import ControlChange
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.channel_pressure import ChannelPressure

def _log(message):
    """Simple logging function for synthesizer events."""
    print(f"[SYNTH ] {message}")

class Synthesizer:
    def __init__(self, midi_interface):
        """Initialize the synthesizer with a MIDI interface.
        
        Args:
            midi_interface: MidiInterface instance for MIDI communication
        """
        self.midi_interface = midi_interface
        self.current_paths = None
        self.current_subscription = None
        self.enabled_messages = set()
        self.enabled_ccs = set()
        self.ready_callback = None
        self.is_ready = False
        _log("Synthesizer initialized")

    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready for MIDI.
        
        Args:
            callback: Function to call when synth is ready
        """
        _log("Ready callback registered")
        self.ready_callback = callback
        # If we're already configured, signal ready immediately
        if self.is_ready and self.ready_callback:
            _log("Already configured - signaling ready immediately")
            self.ready_callback()

    def _parse_paths(self, paths):
        """Parse paths to determine which MIDI messages to handle.
        
        Args:
            paths: String containing instrument paths
        """
        if not paths:
            return set(), set()
            
        message_types = set()
        cc_numbers = set()
        
        for line in paths.strip().split('\n'):
            if not line:
                continue
                
            parts = line.split('/')
            
            # Check for note messages
            if 'note_on' in parts:
                message_types.add('note_on')
            if 'note_off' in parts:
                message_types.add('note_off')
                
            # Check for other MIDI messages
            if 'pitch_bend' in parts:
                message_types.add('pitch_bend')
            if 'pressure' in parts:
                message_types.add('pressure')
                
            # Check for CC numbers
            last_part = parts[-1]
            if last_part.startswith('cc'):
                try:
                    cc_num = int(last_part[2:])
                    cc_numbers.add(cc_num)
                    message_types.add('cc')
                except ValueError:
                    continue

        return message_types, cc_numbers

    def _setup_midi_handlers(self):
        """Set up MIDI message handlers based on current paths."""
        _log("Setting up MIDI handlers...")
        self.is_ready = False
        
        # Clear any existing subscription
        if self.current_subscription:
            self.midi_interface.unsubscribe(self.current_subscription)
            
        # Determine which message types to subscribe to
        message_types = []
        if 'note_on' in self.enabled_messages:
            message_types.append(NoteOn)
        if 'note_off' in self.enabled_messages:
            message_types.append(NoteOff)
        if 'cc' in self.enabled_messages:
            message_types.append(ControlChange)
        if 'pitch_bend' in self.enabled_messages:
            message_types.append(PitchBend)
        if 'pressure' in self.enabled_messages:
            message_types.append(ChannelPressure)
            
        # Create new subscription if we have message types to handle
        if message_types:
            # Pass enabled_ccs to subscription for CC filtering
            self.current_subscription = self.midi_interface.subscribe(
                self._handle_midi_message,
                message_types=message_types,
                cc_numbers=self.enabled_ccs if 'cc' in self.enabled_messages else None
            )
            _log(f"MIDI handlers configured for: {self.enabled_messages}")
            if self.enabled_ccs:
                _log(f"Listening for CCs: {sorted(list(self.enabled_ccs))}")

        # Mark as ready and signal if callback registered
        self.is_ready = True
        if self.ready_callback:
            _log("Configuration complete - signaling ready")
            self.ready_callback()

    def update_instrument(self, paths):
        """Update the current instrument paths and reconfigure MIDI handling.
        
        Args:
            paths: String containing new instrument paths
        """
        _log("Updating instrument configuration...")
        self.current_paths = paths
        self.enabled_messages, self.enabled_ccs = self._parse_paths(paths)
        self._setup_midi_handlers()

    def _handle_midi_message(self, msg):
        """Handle incoming MIDI messages.
        
        Args:
            msg: MIDI message object
        """
        # Filter messages based on current configuration
        if isinstance(msg, NoteOn) and 'note_on' in self.enabled_messages:
            _log(f"Note On received - note={msg.note}, velocity={msg.velocity}, channel={msg.channel+1}")
            
        elif isinstance(msg, NoteOff) and 'note_off' in self.enabled_messages:
            _log(f"Note Off received - note={msg.note}, velocity={msg.velocity}, channel={msg.channel+1}")
            
        elif isinstance(msg, ControlChange) and 'cc' in self.enabled_messages:
            if msg.control in self.enabled_ccs:
                _log(f"Control Change received - control={msg.control}, value={msg.value}, channel={msg.channel+1}")
            
        elif isinstance(msg, PitchBend) and 'pitch_bend' in self.enabled_messages:
            bend_value = msg.pitch_bend - 8192
            _log(f"Pitch Bend received - value={bend_value}, channel={msg.channel+1}")
            
        elif isinstance(msg, ChannelPressure) and 'pressure' in self.enabled_messages:
            _log(f"Channel Pressure received - pressure={msg.pressure}, channel={msg.channel+1}")

    def cleanup(self):
        """Clean up synthesizer resources."""
        if self.current_subscription:
            self.midi_interface.unsubscribe(self.current_subscription)
        self.is_ready = False
        _log("Cleaning up synthesizer")
