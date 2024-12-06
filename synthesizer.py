"""Synthesizer module for handling MIDI input and audio synthesis."""

import array
import synthio
import sys
from adafruit_midi.note_on import NoteOn 
from adafruit_midi.note_off import NoteOff
from adafruit_midi.control_change import ControlChange
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.channel_pressure import ChannelPressure
from constants import (
    SAMPLE_RATE, 
    AUDIO_CHANNEL_COUNT,
    LOG_SYNTH,
    LOG_LIGHT_GREEN,
    LOG_RED,
    LOG_RESET
)

def _log(message, is_error=False, is_debug=False):
    """Enhanced logging with error and debug support."""
    color = LOG_RED if is_error else LOG_LIGHT_GREEN
    if is_error:
        print(f"{color}{LOG_SYNTH} [ERROR] {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{LOG_SYNTH} {message}{LOG_RESET}", file=sys.stderr)

class MidiRange:
    """Handles parameter range conversion and lookup table generation."""
    def __init__(self, name, min_val, max_val, is_integer=False):
        self.name = name
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.is_integer = is_integer
        self.lookup_table = array.array('f', [0] * 128)
        self._build_lookup()
        _log(f"Created MIDI range: {name} [{min_val} to {max_val}] {'(integer)' if is_integer else ''}")
        
    def _build_lookup(self):
        """Build MIDI value lookup table for fast conversion."""
        for i in range(128):
            normalized = i / 127.0
            value = self.min_val + normalized * (self.max_val - self.min_val)
            self.lookup_table[i] = int(value) if self.is_integer else value
            
        _log(f"Lookup table for {self.name} (sample values):")
        _log(f"  0: {self.lookup_table[0]}")
        _log(f" 64: {self.lookup_table[64]}")
        _log(f"127: {self.lookup_table[127]}")
    
    def convert(self, midi_value):
        """Convert MIDI value (0-127) to parameter value using lookup table."""
        if not 0 <= midi_value <= 127:
            _log(f"Invalid MIDI value {midi_value} for {self.name}", is_error=True)
            return self.min_val
        value = self.lookup_table[midi_value]
        _log(f"Converted {self.name}: MIDI {midi_value} -> {value}")
        return value

class PathParser:
    """Parses instrument paths and manages parameter conversions."""
    def __init__(self):
        self.global_ranges = {}  # name -> MidiRange
        self.key_ranges = {}     # name -> MidiRange
        self.fixed_values = {}   # name -> value (e.g. waveform types)
        self.midi_mappings = {}  # trigger -> parameter name
        self.enabled_messages = set()
        self.enabled_ccs = set()
        
    def parse_paths(self, paths):
        """Parse instrument paths to extract parameters and mappings."""
        _log("Parsing instrument paths...")
        self._reset()
        
        if not paths:
            return
            
        for line in paths.strip().split('\n'):
            if not line:
                continue
                
            try:
                parts = line.strip().split('/')
                self._parse_line(parts)
            except Exception as e:
                _log(f"Error parsing path: {line} - {str(e)}", is_error=True)
                
        _log("Path parsing complete:")
        _log(f"Global parameters: {list(self.global_ranges.keys())}")
        _log(f"Per-key parameters: {list(self.key_ranges.keys())}")
        _log(f"Fixed values: {self.fixed_values}")
        _log(f"Enabled messages: {self.enabled_messages}")
        _log(f"Enabled CCs: {self.enabled_ccs}")
    
    def _reset(self):
        """Reset all collections before parsing new paths."""
        self.global_ranges.clear()
        self.key_ranges.clear()
        self.fixed_values.clear()
        self.midi_mappings.clear()
        self.enabled_messages.clear()
        self.enabled_ccs.clear()
    
    def _parse_line(self, parts):
        """Parse a single path line to extract parameter information."""
        # Find parameter scope and name
        scope = None
        param_name = None
        range_str = None
        trigger = None
        
        for i, part in enumerate(parts):
            if part in ('global', 'per_key'):
                scope = part
                if i > 0:
                    param_name = parts[i-1]
                if i + 1 < len(parts):
                    next_part = parts[i+1]
                    if '-' in next_part:
                        range_str = next_part
                    elif next_part in ('triangle', 'sine', 'square', 'saw'):
                        self.fixed_values[param_name] = next_part
                        
                # Look for trigger type
                for p in parts[i:]:
                    if p in ('note_on', 'note_off', 'pressure'):
                        trigger = p
                        self.enabled_messages.add(p.replace('_', ''))
                    elif p.startswith('cc'):
                        try:
                            cc_num = int(p[2:])
                            trigger = p
                            self.enabled_messages.add('cc')
                            self.enabled_ccs.add(cc_num)
                        except ValueError:
                            continue
                    elif p == 'pitch_bend':
                        trigger = p
                        self.enabled_messages.add('pitchbend')
                
                if trigger:
                    self.midi_mappings[trigger] = param_name
                
                break
                
        if scope and param_name and range_str:
            try:
                min_val, max_val = map(float, range_str.split('-'))
                range_obj = MidiRange(param_name, min_val, max_val)
                
                if scope == 'global':
                    self.global_ranges[param_name] = range_obj
                else:
                    self.key_ranges[param_name] = range_obj
            except ValueError as e:
                _log(f"Error parsing range {range_str}: {str(e)}", is_error=True)
    
    def convert_value(self, param_name, midi_value, is_global=True):
        """Convert MIDI value using appropriate range."""
        ranges = self.global_ranges if is_global else self.key_ranges
        if param_name in ranges:
            return ranges[param_name].convert(midi_value)
        return None

class NotePool:
    """Manages a fixed pool of pre-allocated notes."""
    def __init__(self, size=5):
        self.size = size
        self.available = list(range(size))  # Available note indices
        self.pressed = {}    # note_number -> index mapping
        self.order = []      # Tracks note age (oldest first)
        _log(f"Note pool initialized with size {size}")
    
    def get_note(self, note_number):
        """Get next available note or release oldest if pool exhausted."""
        try:
            # If note is already pressed, release it first
            if note_number in self.pressed:
                self.release_note(note_number)
                _log(f"Released already pressed note {note_number}")
            
            if self.available:
                index = self.available.pop()
            elif len(self.pressed) >= self.size:
                # Release oldest note if pool is full
                oldest_number = self.order[0]
                index = self.pressed[oldest_number]
                self.order.remove(oldest_number)
                del self.pressed[oldest_number]
                _log(f"Pool full - released oldest note {oldest_number}")
            else:
                _log("Error: Note pool in invalid state", is_error=True)
                return None
                
            self.pressed[note_number] = index
            self.order.append(note_number)
            _log(f"Note {note_number} allocated from pool (index {index})")
            return index
            
        except Exception as e:
            _log(f"Error in get_note: {str(e)}", is_error=True)
            return None
        
    def release_note(self, note_number):
        """Release a note back to the pool."""
        try:
            if note_number in self.pressed:
                index = self.pressed[note_number]
                del self.pressed[note_number]
                self.order.remove(note_number)
                self.available.append(index)
                _log(f"Note {note_number} (index {index}) released back to pool")
                return index
            return None
            
        except Exception as e:
            _log(f"Error in release_note: {str(e)}", is_error=True)
            return None
    
    def release_all(self):
        """Release all notes back to the pool."""
        try:
            for note_number in list(self.pressed.keys()):
                self.release_note(note_number)
            _log("All notes released")
        except Exception as e:
            _log(f"Error in release_all: {str(e)}", is_error=True)

class Synthesizer:
    def __init__(self, midi_interface, audio_system=None):
        """Initialize the synthesizer with a MIDI interface."""
        self.midi_interface = midi_interface
        self.audio_system = audio_system
        self.synth = None
        self.note_pool = NotePool(5)
        self.path_parser = PathParser()
        self.current_subscription = None
        self.ready_callback = None
        _log("Synthesizer initialized")

    def _setup_synthio(self):
        """Initialize or update synthio synthesizer based on global settings."""
        try:
            # Get waveform setting if it exists
            waveform_type = self.path_parser.fixed_values.get('waveform', 'triangle')
            
            # Create waveform buffer
            waveform = array.array('h', range(-32767, 32767, 32767 * 2 // 100))
            
            _log(f"Creating synthio synthesizer with {waveform_type} waveform")
            self.synth = synthio.Synthesizer(sample_rate=SAMPLE_RATE, channel_count=AUDIO_CHANNEL_COUNT, waveform=waveform)
            
            # Connect synthesizer to audio system's mixer if available
            if self.audio_system and self.audio_system.mixer:
                self.audio_system.mixer.voice[0].play(self.synth)
                _log("Connected synthesizer to audio mixer")
                
            _log("Synthio initialization complete")
            
        except Exception as e:
            _log(f"Failed to initialize synthio: {str(e)}", is_error=True)
            raise

    def register_ready_callback(self, callback):
        """Register a callback to be notified when synth is ready."""
        self.ready_callback = callback
        _log("Ready callback registered")

    def _setup_midi_handlers(self):
        """Set up MIDI message handlers."""
        if self.current_subscription:
            self.midi_interface.unsubscribe(self.current_subscription)
            self.current_subscription = None
            
        _log("Setting up MIDI handlers...")
        
        message_types = []
        if 'noteon' in self.path_parser.enabled_messages:
            message_types.append(NoteOn)
        if 'noteoff' in self.path_parser.enabled_messages:
            message_types.append(NoteOff)
        if 'cc' in self.path_parser.enabled_messages:
            message_types.append(ControlChange)
        if 'pitchbend' in self.path_parser.enabled_messages:
            message_types.append(PitchBend)
        if 'pressure' in self.path_parser.enabled_messages:
            message_types.append(ChannelPressure)
            
        if message_types:
            self.current_subscription = self.midi_interface.subscribe(
                self._handle_midi_message,
                message_types=message_types,
                cc_numbers=self.path_parser.enabled_ccs if 'cc' in self.path_parser.enabled_messages else None
            )
            _log(f"MIDI handlers configured for: {self.path_parser.enabled_messages}")
        
        if self.ready_callback:
            _log("Configuration complete - signaling ready")
            self.ready_callback()

    def update_instrument(self, paths):
        """Update instrument configuration."""
        _log("Updating instrument configuration...")
        _log("----------------------------------------")
        
        try:
            # Release all notes before reconfiguring
            if self.note_pool:
                self.note_pool.release_all()
            
            # Parse paths using PathParser
            self.path_parser.parse_paths(paths)
            
            # Initialize or update synthio
            self._setup_synthio()
            
            # Configure MIDI handling
            self._setup_midi_handlers()
            
            _log("----------------------------------------")
            _log("Instrument update complete")
            
        except Exception as e:
            _log(f"Failed to update instrument: {str(e)}", is_error=True)
            raise

    def _handle_midi_message(self, msg):
        """Handle incoming MIDI messages."""
        try:
            if isinstance(msg, NoteOn) and msg.velocity > 0 and 'noteon' in self.path_parser.enabled_messages:
                # Handle note on with velocity > 0
                index = self.note_pool.get_note(msg.note)
                if index is not None:
                    freq = synthio.midi_to_hz(msg.note)
                    _log(f"Would press note {msg.note} (index {index}) at f={freq:.1f}Hz")
                    
                    # Log any per-key parameters
                    for param_name, range_obj in self.path_parser.key_ranges.items():
                        if 'note_on' in self.path_parser.midi_mappings:
                            value = range_obj.convert(msg.velocity)
                            _log(f"Would apply {param_name} = {value} for note {msg.note}")
                
            elif (isinstance(msg, NoteOff) or 
                  (isinstance(msg, NoteOn) and msg.velocity == 0)) and 'noteoff' in self.path_parser.enabled_messages:
                # Handle both note off messages and note on with velocity 0 (note off)
                index = self.note_pool.release_note(msg.note)
                if index is not None:
                    _log(f"Would release note {msg.note} (index {index})")
                
            elif isinstance(msg, ControlChange) and 'cc' in self.path_parser.enabled_messages:
                cc_trigger = f"cc{msg.control}"
                if msg.control in self.path_parser.enabled_ccs:
                    param_name = self.path_parser.midi_mappings.get(cc_trigger)
                    if param_name:
                        value = self.path_parser.convert_value(param_name, msg.value, True)
                        _log(f"Would apply CC {msg.control} ({param_name}) = {value}")
                
            elif isinstance(msg, PitchBend) and 'pitchbend' in self.path_parser.enabled_messages:
                # Convert 14-bit pitch bend to 7-bit MIDI value
                midi_value = (msg.pitch_bend >> 7) & 0x7F
                for param_name, range_obj in self.path_parser.key_ranges.items():
                    if 'pitch_bend' in self.path_parser.midi_mappings:
                        value = range_obj.convert(midi_value)
                        _log(f"Would apply Pitch Bend ({param_name}) = {value}")
                
            elif isinstance(msg, ChannelPressure) and 'pressure' in self.path_parser.enabled_messages:
                for param_name, range_obj in self.path_parser.key_ranges.items():
                    if 'pressure' in self.path_parser.midi_mappings:
                        value = range_obj.convert(msg.pressure)
                        _log(f"Would apply Channel Pressure ({param_name}) = {value}")
                
        except Exception as e:
            _log(f"Error handling MIDI message: {str(e)}", is_error=True)
            if self.note_pool:
                self.note_pool.release_all()

    def cleanup(self):
        """Clean up resources."""
        _log("Cleaning up synthesizer...")
        try:
            if self.note_pool:
                self.note_pool.release_all()
            
            if self.current_subscription:
                self.midi_interface.unsubscribe(self.current_subscription)
                self.current_subscription = None
                
            if self.synth:
                self.synth.deinit()
                self.synth = None
                
            _log("Cleanup complete")
            
        except Exception as e:
            _log(f"Error during cleanup: {str(e)}", is_error=True)
