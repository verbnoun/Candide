"""Synthesizer setup and initialization module."""


from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from logging import log, TAG_SETUP
from interfaces import SynthioInterfaces
from voices import VoicePool
from router import PathParser
from patcher import MidiHandler

class SynthesizerSetup:
    """Handles initialization and setup of the synthesizer."""
    def __init__(self, midi_interface, audio_system=None):
        self.audio_system = audio_system
        self.midi_interface = midi_interface
        self.synthesizer = None  # Reference to synthesizer for updates
        log(TAG_SETUP, "Setup initialized with midi_interface and audio_system")
        
    def initialize(self):
        """Initialize all synthesizer components."""
        from synthesizer import SynthState, SynthMonitor
        
        log(TAG_SETUP, "Initializing synthesizer components...")
        
        synth_components = {
            'synth': None,
            'voice_pool': VoicePool(5),
            'path_parser': PathParser(),
            'state': SynthState(),
            'monitor': SynthMonitor()
        }
        
        log(TAG_SETUP, "Created base components:")
        log(TAG_SETUP, f"- Voice pool with 5 voices")
        log(TAG_SETUP, f"- Path parser")
        log(TAG_SETUP, f"- Synth state")
        log(TAG_SETUP, f"- Monitor")
        
        # Initialize MidiHandler with midi_interface
        midi_handler = MidiHandler(
            synth_components['state'], 
            synth_components['path_parser']
        )
        midi_handler.set_midi_interface(self.midi_interface)
        synth_components['midi_handler'] = midi_handler
        log(TAG_SETUP, "Created MIDI handler and connected interface")
        
        return synth_components
        
    def setup_synthio(self, synth_state, store, path_parser):
        """Initialize or update synthio synthesizer based on global settings."""
        try:
            log(TAG_SETUP, "Setting up synthio...")
            
            # Create synth parameters
            params = {
                'sample_rate': SAMPLE_RATE,
                'channel_count': AUDIO_CHANNEL_COUNT
            }
            log(TAG_SETUP, f"Base params: sample_rate={SAMPLE_RATE}, channel_count={AUDIO_CHANNEL_COUNT}")
            
            # Add waveform if available from store
            waveform = store.get('waveform')
            if waveform is not None:
                log(TAG_SETUP, f"Found waveform in store: {type(waveform)}")
                params['waveform'] = waveform
                log(TAG_SETUP, "Using waveform from store")
            else:
                log(TAG_SETUP, "Using default synthio waveform")
            
            # Check for envelope parameters
            envelope_params = {}
            for param in ['attack_time', 'decay_time', 'release_time', 
                        'attack_level', 'sustain_level']:
                value = store.get(param)
                if value is not None:
                    try:
                        envelope_params[param] = float(value)
                        log(TAG_SETUP, f"Using envelope parameter {param}: {value}")
                    except (TypeError, ValueError) as e:
                        log(TAG_SETUP, f"Invalid envelope parameter {param}: {value}", is_error=True)
                        continue
            
            # Create envelope if we have all parameters
            if len(envelope_params) == 5:
                try:
                    log(TAG_SETUP, "Creating envelope with params:")
                    for param, value in envelope_params.items():
                        log(TAG_SETUP, f"  {param}: {value}")
                    envelope = SynthioInterfaces.create_envelope(**envelope_params)
                    params['envelope'] = envelope
                    log(TAG_SETUP, "Created envelope for synth initialization")
                except Exception as e:
                    log(TAG_SETUP, f"Failed to create envelope: {str(e)}", is_error=True)
            else:
                missing = set(['attack_time', 'decay_time', 'release_time', 
                            'attack_level', 'sustain_level']) - set(envelope_params.keys())
                log(TAG_SETUP, f"Missing envelope parameters: {missing}")
            
            # Create synth with base parameters
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
            log(TAG_SETUP, "Parsing paths...")
            if config_name:
                log(TAG_SETUP, f"Using config: {config_name}")
            self.synthesizer.path_parser.parse_paths(paths, config_name)
            
            # 3. Send startup values immediately after parsing paths
            log(TAG_SETUP, "Sending startup values...")
            self.synthesizer.midi_handler.send_startup_values()
            
            # 4. Create synthesizer with base parameters (now has startup values in store)
            log(TAG_SETUP, "Creating new synthesizer instance...")
            self.synthesizer.synth = self.setup_synthio(
                self.synthesizer.state,
                self.synthesizer.state,
                self.synthesizer.path_parser
            )
            
            # 5. Setup MIDI handlers
            log(TAG_SETUP, "Setting up MIDI handlers...")
            self.synthesizer.midi_handler.setup_handlers()
            
            log(TAG_SETUP, "----------------------------------------")
            log(TAG_SETUP, "Instrument update complete")
            
            # Signal synth readiness after successful update
            if self.synthesizer.midi_handler.ready_callback:
                log(TAG_SETUP, "Signaling synth ready")
                self.synthesizer.midi_handler.ready_callback()
            
        except Exception as e:
            log(TAG_SETUP, f"Failed to update instrument: {str(e)}", is_error=True)
            self.synthesizer._emergency_cleanup()
            raise

    def set_synthesizer(self, synthesizer):
        """Set synthesizer reference for updates."""
        self.synthesizer = synthesizer
        log(TAG_SETUP, "Set synthesizer reference")

    def cleanup(self, synthesizer):
        """Clean up resources."""
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
                
            synthesizer.state.clear()  # Clear stored values during cleanup
            log(TAG_SETUP, "Cleanup complete")
            
        except Exception as e:
            log(TAG_SETUP, f"Error during cleanup: {str(e)}", is_error=True)
            synthesizer._emergency_cleanup()
