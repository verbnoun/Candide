"""High-level synthesizer coordination module.

This module provides the main interface for the synthesizer system, handling:
- Path parsing and configuration management
- MIDI parameter handling and mapping
- Message routing and control
- System integration and coordination

It uses modules.py for the actual sound generation and resource management.
This split separates the concerns of "what sound to make" (this file)
from "how to make sound" (modules.py).
"""

from modules import NotePool, create_waveform
import synthio
import sys
import array
import time
from constants import (
    SAMPLE_RATE,
    AUDIO_CHANNEL_COUNT,
    LOG_SYNTH,
    LOG_LIGHT_GREEN,
    LOG_RED,
    LOG_RESET,
    SYNTHESIZER_LOG
)

def _log(message, is_error=False, is_debug=False):
    """Enhanced logging with error and debug support."""
    if not SYNTHESIZER_LOG:
        return
        
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
            raise ValueError(f"MIDI value must be between 0 and 127, got {midi_value}")
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
            raise ValueError("No paths provided")
            
        for line in paths.strip().split('\n'):
            if not line:
                continue
                
            try:
                parts = line.strip().split('/')
                self._parse_line(parts)
            except Exception as e:
                _log(f"Error parsing path: {line} - {str(e)}", is_error=True)
                raise
                
        # Validate required paths are present
        if not self.enabled_messages:
            raise ValueError("No MIDI messages enabled in paths")
            
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
        if len(parts) < 3:
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
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
                    elif param_name == 'waveform' and next_part in ('triangle', 'sine', 'square', 'saw'):
                        self.fixed_values[param_name] = next_part
                        
                # Look for trigger type
                for p in parts[i:]:
                    if p in ('note_on', 'note_off', 'pressure', 'velocity', 'note_number'):
                        trigger = p
                        if p in ('note_on', 'note_off'):
                            self.enabled_messages.add(p.replace('_', ''))
                        elif p == 'pressure':
                            self.enabled_messages.add('pressure')
                    elif p.startswith('cc'):
                        try:
                            cc_num = int(p[2:])
                            trigger = p
                            self.enabled_messages.add('cc')
                            self.enabled_ccs.add(cc_num)
                        except ValueError:
                            raise ValueError(f"Invalid CC number in: {p}")
                    elif p == 'pitch_bend':
                        trigger = p
                        self.enabled_messages.add('pitchbend')
                
                if trigger:
                    self.midi_mappings[trigger] = param_name
                else:
                    raise ValueError(f"No trigger found in path: {'/'.join(parts)}")
                
                break
                
        if not scope:
            raise ValueError(f"No scope (global/per_key) found in: {'/'.join(parts)}")
            
        if not param_name:
            raise ValueError(f"No parameter name found in: {'/'.join(parts)}")
            
        if range_str:
            try:
                min_val, max_val = map(float, range_str.split('-'))
                range_obj = MidiRange(param_name, min_val, max_val)
                
                if scope == 'global':
                    self.global_ranges[param_name] = range_obj
                else:
                    self.key_ranges[param_name] = range_obj
            except ValueError as e:
                raise ValueError(f"Invalid range format {range_str}: {str(e)}")
    
    def convert_value(self, param_name, midi_value, is_global=True):
        """Convert MIDI value using appropriate range."""
        ranges = self.global_ranges if is_global else self.key_ranges
        if param_name not in ranges:
            raise KeyError(f"No range defined for parameter: {param_name}")
        return ranges[param_name].convert(midi_value)

class Synthesizer:
    """Main synthesizer class coordinating MIDI handling and sound generation."""
    def __init__(self, midi_interface, audio_system=None):
        """Initialize the synthesizer with a MIDI interface."""
        self.midi_interface = midi_interface
        self.audio_system = audio_system
        self.synth = None
        self.note_pool = NotePool(5)
        self.path_parser = PathParser()
        self.current_subscription = None
        self.ready_callback = None
        self.global_waveform = None
        self.last_health_check = time.monotonic()
        self.health_check_interval = 5.0  # Check every 5 seconds
        _log("Synthesizer initialized")

    def _setup_synthio(self):
        """Initialize or update synthio synthesizer based on global settings."""
        try:
            if 'waveform' not in self.path_parser.fixed_values:
                raise ValueError("No waveform type specified in paths")
                
            waveform_type = self.path_parser.fixed_values['waveform']
            self.global_waveform = create_waveform(waveform_type)
            
            _log(f"Creating synthio synthesizer with {waveform_type} waveform")
            self.synth = synthio.Synthesizer(
                sample_rate=SAMPLE_RATE,
                channel_count=AUDIO_CHANNEL_COUNT,
                waveform=self.global_waveform)
            
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
            message_types.append('noteon')
        if 'noteoff' in self.path_parser.enabled_messages:
            message_types.append('noteoff')
        if 'cc' in self.path_parser.enabled_messages:
            message_types.append('cc')
        if 'pitchbend' in self.path_parser.enabled_messages:
            message_types.append('pitchbend')
        if 'pressure' in self.path_parser.enabled_messages:
            message_types.append('channelpressure')
            
        if not message_types:
            raise ValueError("No MIDI message types enabled in paths")
            
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
                released_notes = self.note_pool.release_all(self.synth)
                _log(f"Released {len(released_notes)} notes during reconfiguration")
            
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
            self._emergency_cleanup()
            raise

    def _check_health(self):
        """Perform periodic health check of the synthesizer system."""
        current_time = time.monotonic()
        if current_time - self.last_health_check >= self.health_check_interval:
            _log("Performing synthesizer health check")
            try:
                # Check note pool health
                self.note_pool.check_health()
                
                # Verify synth state
                if self.synth is None:
                    _log("Synthesizer object is None", is_error=True)
                    self._emergency_cleanup()
                    self._setup_synthio()
                
                self.last_health_check = current_time
                
            except Exception as e:
                _log(f"Health check failed: {str(e)}", is_error=True)
                self._emergency_cleanup()

    def _emergency_cleanup(self):
        """Perform emergency cleanup in case of critical errors."""
        _log("Performing emergency cleanup", is_error=True)
        try:
            # Release all notes
            if self.note_pool:
                released_notes = self.note_pool.release_all(self.synth)
                _log(f"Emergency released {len(released_notes)} notes")
            
            # Reset synthesizer
            if self.synth:
                try:
                    self.synth.deinit()
                except Exception as e:
                    _log(f"Error deinitializing synth: {str(e)}", is_error=True)
                self.synth = None
            
            # Reset MIDI subscription
            if self.current_subscription:
                try:
                    self.midi_interface.unsubscribe(self.current_subscription)
                except Exception as e:
                    _log(f"Error unsubscribing MIDI: {str(e)}", is_error=True)
                self.current_subscription = None
                
            _log("Emergency cleanup complete")
            
        except Exception as e:
            _log(f"Error during emergency cleanup: {str(e)}", is_error=True)

    def _handle_midi_message(self, msg):
        """Handle incoming MIDI messages."""
        try:
            # Perform periodic health check
            self._check_health()
            
            if msg == 'noteon' and msg.velocity > 0 and 'noteon' in self.path_parser.enabled_messages:
                _log(f"Processing Note On: ch={msg.channel} note={msg.note} vel={msg.velocity}")
                # Get note from pool with channel tracking
                result = self.note_pool.get_note(msg.note, msg.channel, self.synth)
                if result:
                    index, note = result
                    
                    # Apply global parameters from path_parser
                    if 'waveform' in self.path_parser.fixed_values:
                        note.waveform = self.global_waveform
                    
                    # Apply any per-key parameters
                    for param_name, range_obj in self.path_parser.key_ranges.items():
                        if param_name == 'frequency':
                            note.frequency = synthio.midi_to_hz(msg.note)
                    
                    # Actually press the note
                    self.synth.press(note)
                    _log(f"Pressed note {msg.note} on channel {msg.channel}")
                else:
                    _log(f"Failed to allocate note {msg.note}", is_error=True)
                
            elif ((msg == 'noteoff' or (msg == 'noteon' and msg.velocity == 0)) and 
                  'noteoff' in self.path_parser.enabled_messages):
                _log(f"Processing Note Off: ch={msg.channel} note={msg.note}")
                # Release the note using existing pool management
                index, note = self.note_pool.release_note(msg.note, self.synth)
                if note is not None:
                    self.synth.release(note)
                    _log(f"Released note {msg.note}")
                else:
                    _log(f"Note {msg.note} not found for release", is_error=True)
                
            elif msg == 'cc' and 'cc' in self.path_parser.enabled_messages:
                cc_trigger = f"cc{msg.control}"
                if msg.control in self.path_parser.enabled_ccs:
                    param_name = self.path_parser.midi_mappings.get(cc_trigger)
                    if param_name:
                        value = self.path_parser.convert_value(param_name, msg.value, True)
                        _log(f"Updated global {param_name} = {value}")
                
            elif msg == 'pitchbend' and 'pitchbend' in self.path_parser.enabled_messages:
                # Convert 14-bit pitch bend to 7-bit MIDI value
                midi_value = (msg.pitch_bend >> 7) & 0x7F
                for param_name, range_obj in self.path_parser.key_ranges.items():
                    if 'pitch_bend' in self.path_parser.midi_mappings:
                        value = range_obj.convert(midi_value)
                        if msg.channel in self.note_pool.channel_notes:
                            note_num, idx = self.note_pool.channel_notes[msg.channel]
                            note = self.note_pool.notes[idx]
                            if param_name == 'bend':
                                note.bend = value
                                _log(f"Applied bend={value} to note {note_num}")
                            elif param_name == 'panning':
                                note.panning = value
                                _log(f"Applied panning={value} to note {note_num}")
                
            elif msg == 'channelpressure' and 'pressure' in self.path_parser.enabled_messages:
                for param_name, range_obj in self.path_parser.key_ranges.items():
                    if 'pressure' in self.path_parser.midi_mappings:
                        value = range_obj.convert(msg.pressure)
                        if msg.channel in self.note_pool.channel_notes:
                            note_num, idx = self.note_pool.channel_notes[msg.channel]
                            note = self.note_pool.notes[idx]
                            if param_name == 'sustain_level':
                                note.amplitude = value
                                _log(f"Applied amplitude={value} to note {note_num}")
                
        except Exception as e:
            _log(f"Error handling MIDI message: {str(e)}", is_error=True)
            self._emergency_cleanup()

    def cleanup(self):
        """Clean up resources."""
        _log("Cleaning up synthesizer...")
        try:
            if self.note_pool:
                released_notes = self.note_pool.release_all(self.synth)
                _log(f"Released {len(released_notes)} notes during cleanup")
            
            if self.current_subscription:
                self.midi_interface.unsubscribe(self.current_subscription)
                self.current_subscription = None
                _log("Unsubscribed from MIDI messages")
                
            if self.synth:
                self.synth.deinit()
                self.synth = None
                _log("Deinitialized synthesizer")
                
            _log("Cleanup complete")
            
        except Exception as e:
            _log(f"Error during cleanup: {str(e)}", is_error=True)
            self._emergency_cleanup()
