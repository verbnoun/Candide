"""Synthesizer setup and initialization module."""

from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT, MAX_VOICES
from logging import log, TAG_SETUP
from interfaces import SynthioInterfaces
from voices import VoicePool
from router import PathParser
from patcher import MidiHandler

class SynthesizerSetup:
    def __init__(self, midi_interface, audio_system=None):
        self.audio_system = audio_system
        self.midi_interface = midi_interface
        self.synthesizer = None
        log(TAG_SETUP, "Setup initialized with midi_interface and audio_system")
        
    def initialize(self):
        from synthesizer import SynthStore, SynthMonitor
        
        log(TAG_SETUP, "Initializing synthesizer components...")
        
        synth_components = {
            'synth': None,
            'voice_pool': VoicePool(MAX_VOICES),
            'path_parser': PathParser(),
            'state': SynthStore(),
            'monitor': SynthMonitor()
        }
        
        log(TAG_SETUP, "Created base components:")
        log(TAG_SETUP, f"- Voice pool with {MAX_VOICES} voices")
        log(TAG_SETUP, f"- Path parser")
        log(TAG_SETUP, f"- Synth state")
        log(TAG_SETUP, f"- Monitor")
        
        midi_handler = MidiHandler(
            synth_components['state'], 
            synth_components['path_parser']
        )
        midi_handler.set_midi_interface(self.midi_interface)
        synth_components['midi_handler'] = midi_handler
        log(TAG_SETUP, "Created MIDI handler and connected interface")
        
        return synth_components
        
    def setup_synthio(self, state):
        try:
            log(TAG_SETUP, "Setting up synthio...")
            
            params = {
                'sample_rate': SAMPLE_RATE,
                'channel_count': AUDIO_CHANNEL_COUNT
            }
            log(TAG_SETUP, f"Base params: sample_rate={SAMPLE_RATE}, channel_count={AUDIO_CHANNEL_COUNT}")
            
            log(TAG_SETUP, "Creating synthesizer with params:")
            for param, value in params.items():
                log(TAG_SETUP, f"  {param}: {type(value)}")
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
        if not self.synthesizer:
            log(TAG_SETUP, "No synthesizer reference for update", is_error=True)
            return
            
        log(TAG_SETUP, "Updating instrument configuration...")
        log(TAG_SETUP, "----------------------------------------")
        
        try:
            if self.synthesizer.voice_pool:
                self.synthesizer.voice_pool.release_all()
                log(TAG_SETUP, "Released all voices during reconfiguration")
            self.synthesizer.state.clear()
            
            log(TAG_SETUP, "Parsing paths...")
            if config_name:
                log(TAG_SETUP, f"Using config: {config_name}")
            self.synthesizer.path_parser.parse_paths(paths, config_name)
            
            log(TAG_SETUP, "Sending startup values...")
            self.synthesizer.midi_handler.send_startup_values()
            
            log(TAG_SETUP, "Creating new synthesizer instance...")
            self.synthesizer.synth = self.setup_synthio(self.synthesizer.state)
            
            log(TAG_SETUP, "Setting up MIDI handlers...")
            self.synthesizer.midi_handler.setup_handlers()
            
            log(TAG_SETUP, "----------------------------------------")
            log(TAG_SETUP, "Instrument update complete")
            
            if self.synthesizer.midi_handler.ready_callback:
                log(TAG_SETUP, "Signaling synth ready")
                self.synthesizer.midi_handler.ready_callback()
            
        except Exception as e:
            log(TAG_SETUP, f"Failed to update instrument: {str(e)}", is_error=True)
            self.synthesizer._emergency_cleanup()
            raise

    def set_synthesizer(self, synthesizer):
        self.synthesizer = synthesizer
        log(TAG_SETUP, "Set synthesizer reference")

    def cleanup(self, synthesizer):
        log(TAG_SETUP, "Cleaning up synthesizer...")
        try:
            if synthesizer.voice_pool:
                synthesizer.voice_pool.release_all()
                log(TAG_SETUP, "Released all voices during cleanup")
            
            if synthesizer.midi_handler:
                synthesizer.midi_handler.cleanup()
                log(TAG_SETUP, "Cleaned up MIDI handler")
                
            if synthesizer.synth:
                synthesizer.synth.deinit()
                synthesizer.synth = None
                log(TAG_SETUP, "Deinitialized synthesizer")
                
            synthesizer.state.clear()
            log(TAG_SETUP, "Cleanup complete")
            
        except Exception as e:
            log(TAG_SETUP, f"Error during cleanup: {str(e)}", is_error=True)
            synthesizer._emergency_cleanup()
