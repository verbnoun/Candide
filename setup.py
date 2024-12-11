"""Synthesizer setup and initialization module."""

import synthio
import time
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from logging import log, TAG_SYNTH
from interfaces import SynthioInterfaces, WaveformMorph
from voices import VoicePool
from router import PathParser
from patcher import MidiHandler

class SynthesizerSetup:
    """Handles initialization and setup of the synthesizer."""
    def __init__(self, midi_interface, audio_system=None):
        self.audio_system = audio_system
        self.midi_interface = midi_interface
        
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
            
            # Create initial envelope using synthesizer's method
            from synthesizer import Synthesizer
            initial_envelope = Synthesizer._create_envelope(None, store, path_parser)
            
            synth = SynthioInterfaces.create_synthesizer(
                sample_rate=SAMPLE_RATE,
                channel_count=AUDIO_CHANNEL_COUNT,
                waveform=synth_state.global_waveform,
                envelope=initial_envelope
            )
            
            if self.audio_system and self.audio_system.mixer:
                self.audio_system.mixer.voice[0].play(synth)
                log(TAG_SYNTH, "Connected synthesizer to audio mixer")
                
            log(TAG_SYNTH, "Synthio initialization complete")
            return synth
                
        except Exception as e:
            log(TAG_SYNTH, f"Failed to initialize synthio: {str(e)}", is_error=True)
            raise

    def _configure_waveforms(self, synth_state, store, path_parser):
        """Create base and ring waveforms"""
        # Configure base waveform
        waveform = store.get('waveform')
        if waveform:
            synth_state.global_waveform = SynthioInterfaces.create_waveform(waveform)
            synth_state.base_morph = None
            log(TAG_SYNTH, f"Created base waveform: {waveform}")
        elif path_parser.waveform_sequence:
            synth_state.base_morph = WaveformMorph('base', path_parser.waveform_sequence)
            synth_state.global_waveform = synth_state.base_morph.get_waveform(0)
            log(TAG_SYNTH, f"Created base morph table: {'-'.join(path_parser.waveform_sequence)}")
        else:
            log(TAG_SYNTH, "No base oscillator waveform path found", is_error=True)
            raise ValueError("No base oscillator waveform path found")
            
        # Configure ring waveform if ring mod is enabled
        if path_parser.has_ring_mod:
            ring_waveform = store.get('ring_waveform')
            if ring_waveform:
                synth_state.global_ring_waveform = SynthioInterfaces.create_waveform(ring_waveform)
                synth_state.ring_morph = None
                log(TAG_SYNTH, f"Created ring waveform: {ring_waveform}")
            elif path_parser.ring_waveform_sequence:
                synth_state.ring_morph = WaveformMorph('ring', path_parser.ring_waveform_sequence)
                synth_state.global_ring_waveform = synth_state.ring_morph.get_waveform(0)
                log(TAG_SYNTH, f"Created ring morph table: {'-'.join(path_parser.ring_waveform_sequence)}")

    def initialize_set_values(self, store, path_parser):
        """Handle all set values from path parser during initialization."""
        try:
            success = True
            for name, value in path_parser.set_values.items():
                try:
                    store.store(name, value)
                    log(TAG_SYNTH, f"Successfully stored initial value {name}={value}")
                except Exception as e:
                    log(TAG_SYNTH, f"Failed to store initial value {name}: {str(e)}", is_error=True)
                    success = False
            return success
        except Exception as e:
            log(TAG_SYNTH, f"Error in initialize_set_values: {str(e)}", is_error=True)
            return False

    def cleanup(self, synthesizer):
        """Clean up resources."""
        log(TAG_SYNTH, "Cleaning up synthesizer...")
        try:
            if synthesizer.voice_pool:
                synthesizer.voice_pool.release_all()
                log(TAG_SYNTH, "Released all voices during cleanup")
            
            if synthesizer.midi_handler:
                synthesizer.midi_handler.cleanup()
                
            if synthesizer.synth:
                synthesizer.synth.deinit()
                synthesizer.synth = None
                log(TAG_SYNTH, "Deinitialized synthesizer")
                
            synthesizer.state.clear()  # Clear stored values during cleanup
            log(TAG_SYNTH, "Cleanup complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Error during cleanup: {str(e)}", is_error=True)
            synthesizer._emergency_cleanup()
