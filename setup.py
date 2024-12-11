"""Synthesizer setup and initialization module."""

import synthio
import time
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from logging import log, TAG_SETUP
from interfaces import SynthioInterfaces, WaveformMorph
from voices import VoicePool
from router import PathParser
from patcher import MidiHandler

class SynthesizerSetup:
    """Handles initialization and setup of the synthesizer."""
    def __init__(self, midi_interface, audio_system=None):
        self.audio_system = audio_system
        self.midi_interface = midi_interface
        self.synthesizer = None  # Reference to synthesizer for updates
        
    def initialize(self):
        """Initialize all synthesizer components."""
        from synthesizer import SynthState, SynthMonitor
        
        synth_components = {
            'synth': None,
            'voice_pool': VoicePool(5),
            'path_parser': PathParser(),
            'state': SynthState(),
            'monitor': SynthMonitor()
        }
        
        # Initialize MidiHandler with midi_interface
        midi_handler = MidiHandler(
            synth_components['state'], 
            synth_components['path_parser']
        )
        midi_handler.set_midi_interface(self.midi_interface)
        synth_components['midi_handler'] = midi_handler
        
        return synth_components
        
    def setup_synthio(self, synth_state, store, path_parser):
        """Initialize or update synthio synthesizer based on global settings."""
        try:
            self._configure_waveforms(synth_state, store, path_parser)
            
            # Create synth parameters
            params = {
                'sample_rate': SAMPLE_RATE,
                'channel_count': AUDIO_CHANNEL_COUNT,
                'waveform': synth_state.global_waveform
            }
            
            # Create synth with base parameters
            synth = SynthioInterfaces.create_synthesizer(**params)
            
            if self.audio_system and self.audio_system.mixer:
                self.audio_system.mixer.voice[0].play(synth)
                log(TAG_SETUP, "Connected synthesizer to audio mixer")
                
            log(TAG_SETUP, "Synthio initialization complete")
            return synth
                
        except Exception as e:
            log(TAG_SETUP, f"Failed to initialize synthio: {str(e)}", is_error=True)
            raise

    def update_instrument(self, paths, config_name=None):
        """Update instrument configuration."""
        if not self.synthesizer:
            log(TAG_SETUP, "No synthesizer reference for update", is_error=True)
            return
            
        log(TAG_SETUP, "Updating instrument configuration...")
        log(TAG_SETUP, "----------------------------------------")
        
        try:
            # 1. Release all voices and clear state
            if self.synthesizer.voice_pool:
                self.synthesizer.voice_pool.release_all()
                log(TAG_SETUP, "Released all voices during reconfiguration")
            self.synthesizer.state.clear()
            
            # 2. Parse paths
            self.synthesizer.path_parser.parse_paths(paths, config_name)
            
            # 3. Store all set values first
            if not self.store_set_values(self.synthesizer.state, self.synthesizer.path_parser):
                log(TAG_SETUP, "Failed to store set values", is_error=True)
                raise ValueError("Failed to store set values")
            
            # 4. Create synthesizer with base parameters (needs stored waveform)
            self.synthesizer.synth = self.setup_synthio(
                self.synthesizer.state,
                self.synthesizer.state,
                self.synthesizer.path_parser
            )
            
            # 5. Execute set actions (like envelope updates)
            if not self.execute_set_actions(self.synthesizer.path_parser):
                log(TAG_SETUP, "Failed to execute set actions", is_error=True)
                raise ValueError("Failed to execute set actions")
            
            # 6. Setup MIDI handlers
            self.synthesizer.midi_handler.setup_handlers()
            
            log(TAG_SETUP, "----------------------------------------")
            log(TAG_SETUP, "Instrument update complete")
            
        except Exception as e:
            log(TAG_SETUP, f"Failed to update instrument: {str(e)}", is_error=True)
            self.synthesizer._emergency_cleanup()
            raise

    def store_set_values(self, store, path_parser):
        """Store all set values."""
        try:
            success = True
            for name, value in path_parser.set_values.items():
                try:
                    store.store(name, value)
                    log(TAG_SETUP, f"Stored set value {name}={value}")
                except Exception as e:
                    log(TAG_SETUP, f"Failed to store set value {name}: {str(e)}", is_error=True)
                    success = False
            return success
        except Exception as e:
            log(TAG_SETUP, f"Error storing set values: {str(e)}", is_error=True)
            return False

    def execute_set_actions(self, path_parser):
        """Execute all set actions."""
        try:
            success = True
            if self.synthesizer and 'set' in path_parser.midi_mappings:
                for action in path_parser.midi_mappings['set']:
                    try:
                        # Skip waveform action since it's handled during synth creation
                        if action['target'] == 'waveform':
                            continue
                            
                        # Get handler method from synthesizer
                        handler = getattr(self.synthesizer, action['handler'])
                        
                        # Call handler with target and value
                        if action['scope'] == 'per_key':
                            handler(action['target'], action['value'], None)  # No channel for set values
                        else:
                            handler(action['target'], action['value'])
                            
                        log(TAG_SETUP, f"Executed set action: {action['handler']}({action['target']}, {action['value']})")
                    except Exception as e:
                        log(TAG_SETUP, f"Failed to execute set action: {str(e)}", is_error=True)
                        success = False
            return success
        except Exception as e:
            log(TAG_SETUP, f"Error executing set actions: {str(e)}", is_error=True)
            return False

    def set_synthesizer(self, synthesizer):
        """Set synthesizer reference for updates."""
        self.synthesizer = synthesizer

    def _configure_waveforms(self, synth_state, store, path_parser):
        """Create base and ring waveforms"""
        # Configure base waveform
        waveform = store.get('waveform')
        if waveform:
            synth_state.global_waveform = SynthioInterfaces.create_waveform(waveform)
            synth_state.base_morph = None
            log(TAG_SETUP, f"Created base waveform: {waveform}")
        elif path_parser.waveform_sequence:
            synth_state.base_morph = WaveformMorph('base', path_parser.waveform_sequence)
            synth_state.global_waveform = synth_state.base_morph.get_waveform(0)
            log(TAG_SETUP, f"Created base morph table: {'-'.join(path_parser.waveform_sequence)}")
        else:
            log(TAG_SETUP, "No base oscillator waveform path found", is_error=True)
            raise ValueError("No base oscillator waveform path found")
            
        # Configure ring waveform if ring mod is enabled
        if path_parser.has_ring_mod:
            ring_waveform = store.get('ring_waveform')
            if ring_waveform:
                synth_state.global_ring_waveform = SynthioInterfaces.create_waveform(ring_waveform)
                synth_state.ring_morph = None
                log(TAG_SETUP, f"Created ring waveform: {ring_waveform}")
            elif path_parser.ring_waveform_sequence:
                synth_state.ring_morph = WaveformMorph('ring', path_parser.ring_waveform_sequence)
                synth_state.global_ring_waveform = synth_state.ring_morph.get_waveform(0)
                log(TAG_SETUP, f"Created ring morph table: {'-'.join(path_parser.ring_waveform_sequence)}")

    def cleanup(self, synthesizer):
        """Clean up resources."""
        log(TAG_SETUP, "Cleaning up synthesizer...")
        try:
            if synthesizer.voice_pool:
                synthesizer.voice_pool.release_all()
                log(TAG_SETUP, "Released all voices during cleanup")
            
            if synthesizer.midi_handler:
                synthesizer.midi_handler.cleanup()
                
            if synthesizer.synth:
                synthesizer.synth.deinit()
                synthesizer.synth = None
                log(TAG_SETUP, "Deinitialized synthesizer")
                
            synthesizer.state.clear()  # Clear stored values during cleanup
            log(TAG_SETUP, "Cleanup complete")
            
        except Exception as e:
            log(TAG_SETUP, f"Error during cleanup: {str(e)}", is_error=True)
            synthesizer._emergency_cleanup()
