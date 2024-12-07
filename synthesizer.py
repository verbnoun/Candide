"""High-level synthesizer coordination module."""

from modules import VoicePool, create_waveform, create_morphed_waveform, WaveformMorph
from pather import PathParser
import synthio
import sys
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
    color = LOG_RED if is_error else LOG_LIGHT_GREEN  # Using LOG_LIGHT_GREEN for synth
    if is_error:
        print("{}{} [ERROR] {}{}".format(color, LOG_SYNTH, message, LOG_RESET), file=sys.stderr)
    else:
        print("{}{} {}{}".format(color, LOG_SYNTH, message, LOG_RESET), file=sys.stderr)

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
        self.base_morph = None  # WaveformMorph for base oscillator
        self.ring_morph = None  # WaveformMorph for ring oscillator
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
                
                # Use waveform based on path configuration
                if 'waveform' in self.path_parser.fixed_values:
                    waveform = create_waveform(self.path_parser.fixed_values['waveform'])
                    _log(f"Using fixed base waveform: {self.path_parser.fixed_values['waveform']}")
                elif self.base_morph:
                    # Convert current morph position to MIDI value
                    midi_value = int(self.path_parser.current_morph_position * 127)
                    waveform = self.base_morph.get_waveform(midi_value)
                    _log(f"Using pre-calculated base morphed waveform at position {self.path_parser.current_morph_position}")
                else:
                    waveform = self.global_waveform
                
                # Create ring waveform based on path configuration
                if self.path_parser.current_ring_params['waveform']:
                    ring_waveform = create_waveform(self.path_parser.current_ring_params['waveform'])
                    _log(f"Using fixed ring waveform: {self.path_parser.current_ring_params['waveform']}")
                elif self.ring_morph:
                    # Convert current ring morph position to MIDI value
                    midi_value = int(self.path_parser.current_ring_morph_position * 127)
                    ring_waveform = self.ring_morph.get_waveform(midi_value)
                    _log(f"Using pre-calculated ring morphed waveform at position {self.path_parser.current_ring_morph_position}")
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
                        
                        # Parse path to determine parameter type
                        path_parts = original_path.split('/')
                        
                        # For ring waveform morph, use ring_morph parameter
                        if (path_parts[0] == 'oscillator' and 
                            path_parts[1] == 'ring' and 
                            path_parts[2] == 'waveform' and 
                            path_parts[3] == 'morph'):
                            param_name = 'ring_morph'
                            
                        value = self.path_parser.convert_value(param_name, msg.value, True)
                        _log("Updated {} = {}".format(original_path, value))
                        
                        # Handle base waveform morph
                        if (path_parts[0] == 'oscillator' and 
                            path_parts[1] == 'waveform' and 
                            path_parts[2] == 'morph'):
                            self.path_parser.current_morph_position = value
                            if self.base_morph:
                                new_waveform = self.base_morph.get_waveform(msg.value)
                                _log(f"Using pre-calculated base morphed waveform at position {value}")
                                for voice in self.voice_pool.voices:
                                    if voice.active_note:
                                        voice.update_active_note(self.synth, waveform=new_waveform)
                                    
                        # Handle ring waveform morph
                        elif (path_parts[0] == 'oscillator' and 
                              path_parts[1] == 'ring' and 
                              path_parts[2] == 'waveform' and 
                              path_parts[3] == 'morph'):
                            self.path_parser.current_ring_morph_position = value
                            if self.ring_morph:
                                new_ring_waveform = self.ring_morph.get_waveform(msg.value)
                                _log(f"Using pre-calculated ring morphed waveform at position {value}")
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
            # Base oscillator waveform should be determined by path
            if 'waveform' in self.path_parser.fixed_values:
                # Path specified a fixed waveform (oscillator/waveform/global/TYPE/note_on)
                waveform_type = self.path_parser.fixed_values['waveform']
                self.global_waveform = create_waveform(waveform_type)
                self.base_morph = None
                _log(f"Created fixed base waveform: {waveform_type}")
            elif self.path_parser.waveform_sequence:
                # Path specified morphing (oscillator/waveform/morph/global/TYPE-TYPE-TYPE/ccX)
                self.base_morph = WaveformMorph('base', self.path_parser.waveform_sequence)
                self.global_waveform = self.base_morph.get_waveform(0)  # Start at first waveform
                _log(f"Created base morph table: {'-'.join(self.path_parser.waveform_sequence)}")
            else:
                _log("No base oscillator waveform path found", is_error=True)
                raise ValueError("No base oscillator waveform path found")
            
            # Ring oscillator waveform should be determined by path
            if self.path_parser.current_ring_params['waveform']:
                # Path specified a fixed waveform (oscillator/ring/waveform/global/TYPE/note_on)
                ring_type = self.path_parser.current_ring_params['waveform']
                self.global_ring_waveform = create_waveform(ring_type)
                self.ring_morph = None
                _log(f"Created fixed ring waveform: {ring_type}")
            elif self.path_parser.ring_waveform_sequence:
                # Path specified morphing (oscillator/ring/waveform/morph/global/TYPE-TYPE-TYPE/ccX)
                self.ring_morph = WaveformMorph('ring', self.path_parser.ring_waveform_sequence)
                self.global_ring_waveform = self.ring_morph.get_waveform(0)  # Start at first waveform
                _log(f"Created ring morph table: {'-'.join(self.path_parser.ring_waveform_sequence)}")
            
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

    def update_instrument(self, paths, config_name=None):
        """Update instrument configuration."""
        _log("Updating instrument configuration...")
        _log("----------------------------------------")
        
        try:
            # Release all notes before reconfiguring
            if self.voice_pool:
                self.voice_pool.release_all(self.synth)
                _log("Released all voices during reconfiguration")
            
            # Parse paths using PathParser
            self.path_parser.parse_paths(paths, config_name)
            
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
