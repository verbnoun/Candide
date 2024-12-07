"""High-level synthesizer coordination module."""

from modules import VoicePool, create_waveform, create_morphed_waveform
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

def _log(message, is_error=False):
    if not SYNTHESIZER_LOG:
        return
    color = LOG_RED if is_error else LOG_LIGHT_GREEN
    if is_error:
        print("{}{} [ERROR] {}{}".format(color, LOG_SYNTH, message, LOG_RESET), file=sys.stderr)
    else:
        print("{}{} {}{}".format(color, LOG_SYNTH, message, LOG_RESET), file=sys.stderr)

class MidiRange:
    """Handles parameter range conversion and lookup table generation."""
    def __init__(self, name, min_val, max_val, is_integer=False):
        self.name = name
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self.is_integer = is_integer
        self.lookup_table = array.array('f', [0] * 128)
        self._build_lookup()
        _log("Created MIDI range: {} [{} to {}] {}".format(
            name, min_val, max_val, '(integer)' if is_integer else ''))
        
    def _build_lookup(self):
        """Build MIDI value lookup table for fast conversion."""
        for i in range(128):
            normalized = i / 127.0
            value = self.min_val + normalized * (self.max_val - self.min_val)
            self.lookup_table[i] = int(value) if self.is_integer else value
            
        _log("Lookup table for {} (sample values):".format(self.name))
        _log("  0: {}".format(self.lookup_table[0]))
        _log(" 64: {}".format(self.lookup_table[64]))
        _log("127: {}".format(self.lookup_table[127]))
    
    def convert(self, midi_value):
        """Convert MIDI value (0-127) to parameter value using lookup table."""
        if not 0 <= midi_value <= 127:
            _log("Invalid MIDI value {} for {}".format(midi_value, self.name), is_error=True)
            raise ValueError("MIDI value must be between 0 and 127, got {}".format(midi_value))
        value = self.lookup_table[midi_value]
        return value

class PathParser:
    """Parses instrument paths and manages parameter conversions."""
    def __init__(self):
        self.global_ranges = {}  # name -> MidiRange
        self.key_ranges = {}     # name -> MidiRange
        self.fixed_values = {}   # name -> value (e.g. waveform types)
        self.midi_mappings = {}  # trigger -> (path, param_name)  # Changed to store full path info
        self.enabled_messages = set()
        self.enabled_ccs = set()
        self.filter_type = None  # Current filter type
        self.current_filter_params = {
            'frequency': 0,
            'resonance': 0
        }
        self.current_ring_params = {
            'frequency': 20,  # Default to minimum
            'bend': 0,       # Default to no bend
            'waveform': None # Will be set during parsing
        }
        self.current_envelope_params = {
            'attack_time': 0.1,
            'decay_time': 0.05,
            'release_time': 0.2,
            'attack_level': 1.0,
            'sustain_level': 0.8
        }
        # Keep morph state separate and clear
        self.current_morph_position = 0.0  # Base waveform morph (CC72)
        self.current_ring_morph_position = 0.0  # Ring waveform morph (CC76)
        self.waveform_sequence = None  # Base waveform sequence
        self.ring_waveform_sequence = None  # Ring waveform sequence
        
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
        _log(f"Filter type: {self.filter_type}")
        _log(f"Ring mod params: {self.current_ring_params}")
        _log(f"Envelope params: {self.current_envelope_params}")
        if self.waveform_sequence:
            _log(f"Waveform morph sequence: {'-'.join(self.waveform_sequence)}")
        if self.ring_waveform_sequence:
            _log(f"Ring waveform morph sequence: {'-'.join(self.ring_waveform_sequence)}")
    
    def _reset(self):
        """Reset all collections before parsing new paths."""
        self.global_ranges.clear()
        self.key_ranges.clear()
        self.fixed_values.clear()
        self.midi_mappings.clear()
        self.enabled_messages.clear()
        self.enabled_ccs.clear()
        self.filter_type = None
        self.current_filter_params = {
            'frequency': 0,
            'resonance': 0
        }
        self.current_ring_params = {
            'frequency': 20,  # Default to minimum
            'bend': 0,       # Default to no bend
            'waveform': None # Will be set during parsing
        }
        self.current_envelope_params = {
            'attack_time': 0.1,
            'decay_time': 0.05,
            'release_time': 0.2,
            'attack_level': 1.0,
            'sustain_level': 0.8
        }
        self.current_morph_position = 0.0
        self.current_ring_morph_position = 0.0
        self.waveform_sequence = None
        self.ring_waveform_sequence = None

    def _parse_range(self, range_str):
        """Parse a range string, handling negative numbers with 'n' prefix."""
        try:
            if '-' not in range_str:
                raise ValueError(f"Invalid range format: {range_str}")
                
            min_str, max_str = range_str.split('-')
            
            # Handle negative numbers with 'n' prefix
            if min_str.startswith('n'):
                min_val = -float(min_str[1:])
            else:
                min_val = float(min_str)
                
            max_val = float(max_str)
            return min_val, max_val
            
        except ValueError as e:
            raise ValueError(f"Invalid range format {range_str}: {str(e)}")
    
    def _parse_line(self, parts):
        """Parse a single path line to extract parameter information."""
        if len(parts) < 3:
            raise ValueError(f"Invalid path format: {'/'.join(parts)}")
            
        # Store original path for parameter mapping
        original_path = '/'.join(parts)
            
        # Check for filter configuration
        if parts[0] == 'filter':
            if len(parts) >= 2 and parts[1] in ('low_pass', 'high_pass', 'band_pass', 'notch'):
                self.filter_type = parts[1]
                _log(f"Found filter type: {self.filter_type}")

        # Check for waveform morph configuration
        if (parts[0] == 'oscillator' and len(parts) >= 4 and 
            parts[1] == 'waveform' and parts[2] == 'morph'):
            _log("Found waveform morph configuration")
            # Extract waveform sequence from the path
            if len(parts) >= 5 and '-' in parts[4]:
                self.waveform_sequence = parts[4].split('-')
                _log(f"Found waveform sequence: {self.waveform_sequence}")
                # Create range for morph parameter (0-1)
                self.global_ranges['morph'] = MidiRange('morph', 0, 1)

        # Check for ring modulation configuration
        if parts[0] == 'oscillator' and len(parts) >= 2 and parts[1] == 'ring':
            if len(parts) >= 3:
                if parts[2] == 'waveform':
                    if parts[3] == 'morph':
                        # Extract ring waveform sequence
                        if len(parts) >= 6 and '-' in parts[5]:
                            self.ring_waveform_sequence = parts[5].split('-')
                            _log(f"Found ring waveform sequence: {self.ring_waveform_sequence}")
                            # Create separate range for ring morph
                            self.global_ranges['ring_morph'] = MidiRange('ring_morph', 0, 1)
                    elif len(parts) >= 5:
                        self.current_ring_params['waveform'] = parts[4]
                        _log(f"Found ring mod waveform: {parts[4]}")
                        
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
                    if '-' in next_part and not any(w in next_part for w in ('sine', 'triangle', 'square', 'saw')):
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
                    # Store full path info with parameter
                    self.midi_mappings[trigger] = (original_path, param_name)
                else:
                    raise ValueError(f"No trigger found in path: {original_path}")
                
                break
                
        if not scope:
            raise ValueError(f"No scope (global/per_key) found in: {original_path}")
            
        if not param_name:
            raise ValueError(f"No parameter name found in: {original_path}")
            
        if range_str:
            try:
                min_val, max_val = self._parse_range(range_str)
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

    def update_envelope(self):
        """Create a new envelope with current parameters."""
        return synthio.Envelope(
            attack_time=self.current_envelope_params['attack_time'],
            decay_time=self.current_envelope_params['decay_time'],
            release_time=self.current_envelope_params['release_time'],
            attack_level=self.current_envelope_params['attack_level'],
            sustain_level=self.current_envelope_params['sustain_level']
        )

class Synthesizer:
    """Main synthesizer class coordinating MIDI handling and sound generation."""
    def __init__(self, midi_interface, audio_system=None):
        self.midi_interface = midi_interface
        self.audio_system = audio_system
        self.synth = None
        self.voice_pool = VoicePool(5)
        self.path_parser = PathParser()
        self.current_subscription = None
        self.ready_callback = None
        self.global_waveform = None
        self.global_ring_waveform = None
        self.last_health_check = time.monotonic()
        self.health_check_interval = 5.0
        _log("Synthesizer initialized")

    def _handle_midi_message(self, msg):
        """Handle incoming MIDI messages."""
        try:
            # Log received MIDI message
            if msg == 'noteon':
                _log("Received MIDI note-on: ch={} note={} vel={}".format(
                    msg.channel, msg.note, msg.velocity))
            elif msg == 'noteoff':
                _log("Received MIDI note-off: ch={} note={}".format(
                    msg.channel, msg.note))
            elif msg == 'cc':
                _log("Received MIDI CC: ch={} cc={} val={}".format(
                    msg.channel, msg.control, msg.value))
            elif msg == 'pitchbend':
                _log("Received MIDI pitch bend: ch={} val={}".format(
                    msg.channel, msg.pitch_bend))
            elif msg == 'channelpressure':
                _log("Received MIDI pressure: ch={} val={}".format(
                    msg.channel, msg.pressure))
            
            self._check_health()
            
            if not self.synth:
                _log("No synthesizer available", is_error=True)
                return
            
            if msg == 'noteon' and msg.velocity > 0 and 'noteon' in self.path_parser.enabled_messages:
                _log("Targeting {}.{} with note-on".format(msg.note, msg.channel))
                
                # Create waveform based on current morph position
                waveform = create_morphed_waveform(
                    self.path_parser.current_morph_position,
                    self.path_parser.waveform_sequence
                )
                _log(f"Using current morph position: {self.path_parser.current_morph_position}")
                
                # Create ring waveform based on current ring morph position
                if self.path_parser.ring_waveform_sequence:
                    ring_waveform = create_morphed_waveform(
                        self.path_parser.current_ring_morph_position,
                        self.path_parser.ring_waveform_sequence
                    )
                    _log(f"Using current ring morph position: {self.path_parser.current_ring_morph_position}")
                else:
                    ring_waveform = self.global_ring_waveform
                
                note_params = {
                    'frequency': synthio.midi_to_hz(msg.note),
                    'waveform': waveform,
                    'filter_type': self.path_parser.filter_type,
                    'filter_frequency': self.path_parser.current_filter_params['frequency'],
                    'filter_resonance': self.path_parser.current_filter_params['resonance'],
                    'ring_frequency': self.path_parser.current_ring_params['frequency'],
                    'ring_waveform': ring_waveform,
                    'ring_bend': self.path_parser.current_ring_params['bend']
                }
                
                self.voice_pool.press_note(msg.note, msg.channel, self.synth, **note_params)
                
            elif ((msg == 'noteoff' or (msg == 'noteon' and msg.velocity == 0)) and 
                  'noteoff' in self.path_parser.enabled_messages):
                _log("Targeting {}.{} with note-off".format(msg.note, msg.channel))
                
                voice = self.voice_pool.release_note(msg.note, self.synth)
                if not voice:
                    _log("No voice found at {}.{}".format(msg.note, msg.channel), is_error=True)
                
            elif msg == 'cc' and 'cc' in self.path_parser.enabled_messages:
                cc_trigger = "cc{}".format(msg.control)
                if msg.control in self.path_parser.enabled_ccs:
                    path_info = self.path_parser.midi_mappings.get(cc_trigger)
                    if path_info:
                        original_path, param_name = path_info
                        value = self.path_parser.convert_value(param_name, msg.value, True)
                        _log("Updated {} = {}".format(original_path, value))
                        
                        # Parse path to determine parameter type
                        path_parts = original_path.split('/')
                        
                        # Handle base waveform morph
                        if (path_parts[0] == 'oscillator' and 
                            path_parts[1] == 'waveform' and 
                            path_parts[2] == 'morph'):
                            self.path_parser.current_morph_position = value
                            new_waveform = create_morphed_waveform(
                                value,
                                self.path_parser.waveform_sequence
                            )
                            _log(f"Created new base morphed waveform at position {value}")
                            for voice in self.voice_pool.voices:
                                if voice.active_note:
                                    voice.update_active_note(self.synth, waveform=new_waveform)
                                    
                        # Handle ring waveform morph
                        elif (path_parts[0] == 'oscillator' and 
                              path_parts[1] == 'ring' and 
                              path_parts[2] == 'waveform' and 
                              path_parts[3] == 'morph'):
                            self.path_parser.current_ring_morph_position = value
                            new_ring_waveform = create_morphed_waveform(
                                value,
                                self.path_parser.ring_waveform_sequence
                            )
                            _log(f"Created new ring morphed waveform at position {value}")
                            for voice in self.voice_pool.voices:
                                if voice.active_note:
                                    voice.update_active_note(self.synth, ring_waveform=new_ring_waveform)
                                    
                        # Handle ring frequency
                        elif (path_parts[0] == 'oscillator' and 
                              path_parts[1] == 'ring' and 
                              path_parts[2] == 'frequency'):
                            self.path_parser.current_ring_params['frequency'] = value
                            _log(f"Updated ring frequency = {value}")
                            for voice in self.voice_pool.voices:
                                if voice.active_note:
                                    voice.update_active_note(self.synth, ring_frequency=value)
                                    
                        # Handle ring bend
                        elif (path_parts[0] == 'oscillator' and 
                              path_parts[1] == 'ring' and 
                              path_parts[2] == 'bend'):
                            self.path_parser.current_ring_params['bend'] = value
                            _log(f"Updated ring bend = {value}")
                            for voice in self.voice_pool.voices:
                                if voice.active_note:
                                    voice.update_active_note(self.synth, ring_bend=value)
                                    
                        # Handle envelope parameter updates
                        elif param_name in ('attack_time', 'decay_time', 'release_time', 
                                        'attack_level', 'sustain_level'):
                            self.path_parser.current_envelope_params[param_name] = value
                            # Update global envelope
                            self.synth.envelope = self.path_parser.update_envelope()
                            _log(f"Updated global envelope {param_name} = {value}")
                            
                        # Handle filter parameter updates
                        elif param_name == 'frequency':
                            self.path_parser.current_filter_params['frequency'] = value
                            # Update all active voices with new filter
                            for voice in self.voice_pool.voices:
                                if voice.active_note:
                                    voice.update_active_note(self.synth,
                                        filter_type=self.path_parser.filter_type,
                                        filter_frequency=value,
                                        filter_resonance=self.path_parser.current_filter_params['resonance'])
                                    
                        elif param_name == 'resonance':
                            self.path_parser.current_filter_params['resonance'] = value
                            # Update all active voices with new filter
                            for voice in self.voice_pool.voices:
                                if voice.active_note:
                                    voice.update_active_note(self.synth,
                                        filter_type=self.path_parser.filter_type,
                                        filter_frequency=self.path_parser.current_filter_params['frequency'],
                                        filter_resonance=value)
                
            elif msg == 'pitchbend' and 'pitchbend' in self.path_parser.enabled_messages:
                midi_value = (msg.pitch_bend >> 7) & 0x7F
                voice = self.voice_pool.get_voice_by_channel(msg.channel)
                if voice and voice.active_note:
                    for param_name, range_obj in self.path_parser.key_ranges.items():
                        if 'pitch_bend' in self.path_parser.midi_mappings:
                            value = range_obj.convert(midi_value)
                            if param_name == 'bend':
                                voice.update_active_note(self.synth, bend=value)
                            elif param_name == 'panning':
                                voice.update_active_note(self.synth, panning=value)
                
            elif msg == 'channelpressure' and 'pressure' in self.path_parser.enabled_messages:
                voice = self.voice_pool.get_voice_by_channel(msg.channel)
                if voice and voice.active_note:
                    for param_name, range_obj in self.path_parser.key_ranges.items():
                        if 'pressure' in self.path_parser.midi_mappings:
                            value = range_obj.convert(msg.pressure)
                            if param_name == 'amplitude':
                                voice.update_active_note(self.synth, amplitude=value)
                
        except Exception as e:
            _log("Error handling MIDI message: {}".format(str(e)), is_error=True)
            self._emergency_cleanup()

    def _setup_synthio(self):
        """Initialize or update synthio synthesizer based on global settings."""
        try:
            # Create initial waveform based on morph position
            self.global_waveform = create_morphed_waveform(
                self.path_parser.current_morph_position,
                self.path_parser.waveform_sequence
            )
            _log(f"Created initial morphed waveform at position {self.path_parser.current_morph_position}")
            
            # Create ring modulation waveform if specified
            if self.path_parser.current_ring_params['waveform']:
                if self.path_parser.ring_waveform_sequence:
                    self.global_ring_waveform = create_morphed_waveform(
                        self.path_parser.current_ring_morph_position,  # Use ring-specific position
                        self.path_parser.ring_waveform_sequence
                    )
                    _log(f"Created morphed ring mod waveform at position {self.path_parser.current_ring_morph_position}")
                else:
                    self.global_ring_waveform = create_waveform(
                        self.path_parser.current_ring_params['waveform'])
                    _log(f"Created ring mod waveform: {self.path_parser.current_ring_params['waveform']}")
            
            # Create initial envelope
            initial_envelope = self.path_parser.update_envelope()
            _log("Created initial envelope with params: {}".format(
                self.path_parser.current_envelope_params))
            
            self.synth = synthio.Synthesizer(
                sample_rate=SAMPLE_RATE,
                channel_count=AUDIO_CHANNEL_COUNT,
                waveform=self.global_waveform,
                envelope=initial_envelope)
            
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
            if self.voice_pool:
                self.voice_pool.release_all(self.synth)
                _log("Released all voices during reconfiguration")
            
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
                # Check voice pool health
                self.voice_pool.check_health(self.synth)
                
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
            # Release all voices
            if self.voice_pool and self.synth:
                self.voice_pool.release_all(self.synth)
                _log("Emergency released all voices")
            
            # Reset MIDI subscription
            if self.current_subscription:
                try:
                    self.midi_interface.unsubscribe(self.current_subscription)
                except Exception as e:
                    _log(f"Error unsubscribing MIDI: {str(e)}", is_error=True)
                self.current_subscription = None
                
            # Reset synthesizer
            if self.synth:
                try:
                    self.synth.deinit()
                except Exception as e:
                    _log(f"Error deinitializing synth: {str(e)}", is_error=True)
            self.synth = None
                
            # Try to re-init synth
            try:
                self._setup_synthio()
                self._setup_midi_handlers()
                _log("Successfully re-initialized synthesizer after emergency")
            except Exception as e:
                _log(f"Failed to re-initialize synth: {str(e)}", is_error=True)
                
            _log("Emergency cleanup complete")
            
        except Exception as e:
            _log(f"Error during emergency cleanup: {str(e)}", is_error=True)

    def cleanup(self):
        """Clean up resources."""
        _log("Cleaning up synthesizer...")
        try:
            if self.voice_pool and self.synth:
                self.voice_pool.release_all(self.synth)
                _log("Released all voices during cleanup")
            
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
