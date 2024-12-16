"""Synthesizer setup and initialization module."""

import time
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT, MAX_VOICES, ConnectionState
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
        self.connection_manager = None
        self.waiting_for_cc = False
        self.expected_ccs = set()
        self.received_ccs = set()
        self.wait_start_time = None
        self.CC_TIMEOUT = 2.0  # Timeout in seconds
        log(TAG_SETUP, "Setup initialized with midi_interface and audio_system")
        
    def set_connection_manager(self, connection_manager):
        """Set connection manager reference."""
        self.connection_manager = connection_manager
        log(TAG_SETUP, "Connection manager reference set")
        
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

    def handle_store_update(self, param_name):
        """Handle store updates during instrument changes."""
        if not self.waiting_for_cc:
            return
            
        # Extract CC number from param name if it's from a CC update
        for cc in self.expected_ccs:
            if str(cc) in param_name:
                self.received_ccs.add(cc)
                remaining = len(self.expected_ccs) - len(self.received_ccs)
                log(TAG_SETUP, f"Received CC {cc}, waiting for {remaining} more...")
                break

    def check_cc_timeout(self):
        """Check if we've timed out waiting for CC updates."""
        if not self.waiting_for_cc or not self.wait_start_time:
            return False
            
        if time.monotonic() - self.wait_start_time > self.CC_TIMEOUT:
            missing = self.expected_ccs - self.received_ccs
            log(TAG_SETUP, f"Timed out waiting for CCs: {sorted(list(missing))}")
            return True
        return False

    def wait_for_cc_updates(self):
        """Wait for all expected CC updates or timeout."""
        while self.waiting_for_cc:
            if len(self.received_ccs) == len(self.expected_ccs):
                log(TAG_SETUP, "Received all expected CC updates")
                self.waiting_for_cc = False
                return True
                
            if self.check_cc_timeout():
                return False
                    
            time.sleep(0.1)  # Small sleep to prevent tight loop
        return True

    def on_connection_state_change(self, new_state):
        """Handle connection state changes."""
        if new_state == ConnectionState.DETECTED:
            log(TAG_SETUP, "Base station detected - preparing for MIDI updates")
            # Just update state - wait for CONNECTED before proceeding
            
        elif new_state == ConnectionState.CONNECTED:
            log(TAG_SETUP, "Connection established - synth will wait for MIDI updates")
            
        elif new_state == ConnectionState.STANDALONE:
            log(TAG_SETUP, "Connection lost - synth will use startup values only")
            
    def on_instrument_change(self, instrument_name, config_name, paths):
        """Handle instrument changes."""
        if not self.synthesizer:
            log(TAG_SETUP, "No synthesizer reference for update", is_error=True)
            return
            
        log(TAG_SETUP, "=== Starting Instrument Update ===")
        
        try:
            # 1. Clean up old synth first
            log(TAG_SETUP, "Step 1: Cleaning up old synthesizer...")
            if self.synthesizer.voice_pool:
                self.synthesizer.voice_pool.release_all()
                log(TAG_SETUP, "Released all voices")
            if self.synthesizer.synth:
                self.synthesizer.synth.deinit()
                self.synthesizer.synth = None
                log(TAG_SETUP, "Deinitialized old synthesizer")
            
            # 2. Clear store for new state
            log(TAG_SETUP, "Step 2: Clearing synth store...")
            self.synthesizer.state.clear()
            log(TAG_SETUP, "Store cleared")
            
            # 3. Parse paths and prepare new configuration
            log(TAG_SETUP, "Step 3: Parsing new instrument paths...")
            if config_name:
                log(TAG_SETUP, f"Using config: {config_name}")
            self.synthesizer.path_parser.parse_paths(paths, config_name)
            
            # Check if connected to base station
            if self.connection_manager and self.connection_manager.get_state() == ConnectionState.CONNECTED:
                log(TAG_SETUP, "Base station connected - waiting for MIDI updates")
                
                # Track expected CCs
                self.expected_ccs = set(self.synthesizer.path_parser.enabled_ccs)
                self.received_ccs.clear()
                self.waiting_for_cc = True
                
                # Set up store update callback
                self.synthesizer.state.set_store_update_callback(self.handle_store_update)
                
                # Wait for CC updates
                while True:
                    log(TAG_SETUP, f"Waiting for {len(self.expected_ccs)} CC updates - synthesizer not initialized...")
                    self.wait_start_time = time.monotonic()
                    
                    # Wait for CC updates or timeout
                    if self.wait_for_cc_updates():
                        log(TAG_SETUP, "Store populated with MIDI values")
                        break
                    
                    log(TAG_SETUP, "Retrying CC updates...")
                
                # Clear callback now that we're done waiting for updates
                self.synthesizer.state.set_store_update_callback(None)
                
                # Now send startup values after MIDI updates
                log(TAG_SETUP, "Sending startup values...")
                self.synthesizer.midi_handler.send_startup_values()
                
            else:
                log(TAG_SETUP, "No base station connection - initializing with startup values only")
                # Send startup values directly
                self.synthesizer.midi_handler.send_startup_values()
            
            # Create new synth with populated store
            log(TAG_SETUP, "Creating new synthesizer instance...")
            self.synthesizer.synth = self.setup_synthio(self.synthesizer.state)
            
            log(TAG_SETUP, "=== Instrument Update Complete ===")
            
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
