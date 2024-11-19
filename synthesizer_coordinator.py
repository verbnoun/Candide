"""Synthesizer coordinator that interfaces note state with synthio"""
import time
import synthio
from synth_constants import Constants
from mpe_handling import MPEVoiceManager, MPEMessageRouter
from fixed_point_math import FixedPoint
from synthesis_engine import WaveformManager

class MPESynthesizer:
    """Manages synthesis based purely on config and note state"""
    def __init__(self, output_manager):
        if Constants.DEBUG:
            print("\n[SYNTH] Initializing MPE Synthesizer")
            
        if not output_manager:
            raise ValueError("AudioOutputManager required")
            
        self.output_manager = output_manager

        # Initialize synthio
        self.synth = synthio.Synthesizer(
            sample_rate=Constants.SAMPLE_RATE,
            channel_count=2
        )
        
        # Initialize voice management
        self.voice_manager = MPEVoiceManager()
        self.message_router = MPEMessageRouter(self.voice_manager)
        
        # Initialize WaveformManager
        self.waveform_manager = None
        
        # Connect to audio output
        self.output_manager.attach_synthesizer(self.synth)

        self.current_config = None
        self.active_notes = {}  # (channel, note): synthio.Note
        self._last_update = time.monotonic()

        if Constants.DEBUG:
            print("[SYNTH] Initialization complete")
            
    def _create_synthio_note(self, note_state):
        """Create synthio note from current note state"""
        if not note_state or not self.current_config or not self.waveform_manager:
            if Constants.DEBUG:
                print("[SYNTH] No note state, config, or waveform manager")
            return None
            
        try:
            # Get params according to config
            param_config = self.current_config.get('parameters', {})
            
            if not param_config:
                if Constants.DEBUG:
                    print("[SYNTH] No parameters in config")
                return None
            
            # Detailed debug logging of all parameter values
            if Constants.DEBUG:
                print("[SYNTH] Parameter Configuration:")
                for param_id, param_def in param_config.items():
                    print(f"      {param_id}:")
                    for key, value in param_def.items():
                        print(f"        {key}: {value}")
                
                print("\n[SYNTH] Parameter Values:")
                for param_id, value in note_state.parameter_values.items():
                    print(f"      {param_id}: {FixedPoint.to_float(value):.4f}")
            
            # Required parameters must exist in config and note state
            required = ['frequency', 'waveform']
            for param in required:
                if param not in param_config:
                    if Constants.DEBUG:
                        print(f"[SYNTH] Missing required parameter in config: {param}")
                    return None
                    
            # Get final parameter values
            frequency = FixedPoint.to_float(note_state.get_parameter_value('frequency'))
            amplitude = FixedPoint.to_float(note_state.get_parameter_value('amplitude'))
            
            # Get waveform
            waveform_type = param_config['waveform'].get('default', 'triangle')
            waveform_array = self.waveform_manager.get_waveform(waveform_type)
            
            if waveform_array is None:
                if Constants.DEBUG:
                    print(f"[SYNTH] Waveform not found: {waveform_type}")
                return None
                
            # Create synthio note with required params
            synth_note = synthio.Note(
                frequency=frequency,
                amplitude=amplitude,
                waveform=waveform_array
            )
            
            # Apply optional parameters according to config
            for param_id, param_def in param_config.items():
                if param_id in ['frequency', 'amplitude', 'waveform']:
                    continue
                    
                if param_def.get('synthio_param'):
                    value = note_state.get_parameter_value(param_id)
                    if value != FixedPoint.ZERO:
                        setattr(synth_note, param_def['synthio_param'], 
                               FixedPoint.to_float(value))
            
            if Constants.DEBUG:
                print(f"[SYNTH] Created synthio note:")
                print(f"      Channel: {note_state.channel}")
                print(f"      Note: {note_state.note}")
                print(f"      Freq: {frequency:.2f}Hz")
                print(f"      Amp: {amplitude:.3f}")
                print(f"      Waveform: {waveform_type}")

            return synth_note

        except Exception as e:
            print(f"[ERROR] Failed to create synthio note: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
            
    def set_instrument(self, config):
        """Set instrument configuration"""
        if not config:
            return
            
        try:
            if Constants.DEBUG:
                print(f"\n[SYNTH] Setting instrument: {config['name']}")
                
            self.current_config = config
            self.message_router.set_config(config)
            
            # Initialize WaveformManager with current config
            self.waveform_manager = WaveformManager(config)
            
            if Constants.DEBUG:
                print("[SYNTH] Configuration complete")
                
        except Exception as e:
            print(f"[ERROR] Config update failed: {str(e)}")

    # Rest of the class remains unchanged from the original file
    def _update_synthio_note(self, note_state):
        """Update synthio note parameters from note state"""
        if not note_state or not note_state.synth_note:
            return False
            
        try:
            note = note_state.synth_note
            param_config = self.current_config.get('parameters', {})
            updated = False
            
            # Update each parameter according to config
            for param_id, param_def in param_config.items():
                if not param_def.get('synthio_param'):
                    continue
                    
                new_value = FixedPoint.to_float(note_state.get_parameter_value(param_id))
                current_value = getattr(note, param_def['synthio_param'])
                
                # Only update if changed significantly
                if abs(new_value - current_value) > param_def.get('threshold', 0.001):
                    setattr(note, param_def['synthio_param'], new_value)
                    updated = True
                    
                    if Constants.DEBUG:
                        print(f"[SYNTH] Updated {param_id}: {new_value:.3f}")
                        
            return updated
            
        except Exception as e:
            print(f"[ERROR] Note update failed: {str(e)}")
            return False
            
    def _handle_voice_allocation(self, voice):
        """Create and start synthio note"""
        if not voice:
            return
            
        try:
            # Create synthio note
            synth_note = self._create_synthio_note(voice)
            if not synth_note:
                return
                
            # Store references
            voice.synth_note = synth_note
            self.active_notes[(voice.channel, voice.note)] = synth_note
            
            # Start note
            self.synth.press(synth_note)
            self.output_manager.performance.active_voices += 1
            
            if Constants.DEBUG:
                print(f"[SYNTH] Voice allocated ch:{voice.channel} note:{voice.note}")
                
        except Exception as e:
            print(f"[ERROR] Voice allocation failed: {str(e)}")
            
    def _handle_voice_release(self, voice):
        """Handle note release"""
        if not voice or not voice.synth_note:
            return
            
        try:
            if Constants.DEBUG:
                print(f"[SYNTH] Releasing voice ch:{voice.channel} note:{voice.note}")
                
            # Release synthio note
            self.synth.release(voice.synth_note)
            
            # Clean up references
            key = (voice.channel, voice.note)
            if key in self.active_notes:
                del self.active_notes[key]
                
            if self.output_manager.performance.active_voices > 0:
                self.output_manager.performance.active_voices -= 1
                
        except Exception as e:
            print(f"[ERROR] Voice release failed: {str(e)}")
            
    def update(self):
        """Update synth state"""
        try:
            current_time = time.monotonic()
            if (current_time - self._last_update) < 0.001:
                return
                
            # Process any pending updates
            self.message_router.process_updates()
            
            # Update synthio notes from note states
            for key, voice in self.voice_manager.active_notes.items():
                if voice.active and voice.synth_note:
                    self._update_synthio_note(voice)
                    
            self._last_update = current_time
            self.output_manager.update()
            
        except Exception as e:
            print(f"[ERROR] Update failed: {str(e)}")
            
    def process_mpe_events(self, events):
        """Process incoming MPE messages"""
        if not events:
            return
            
        try:
            if (Constants.DISABLE_THROTTLING or 
                not self.output_manager.performance.should_throttle()):
                
                for event in events:
                    result = self.message_router.route_message(event)
                    if result:
                        if result['type'] == 'voice_allocated':
                            self._handle_voice_allocation(result['voice'])
                        elif result['type'] == 'voice_released':
                            self._handle_voice_release(result['voice'])
                            
            else:
                # When throttling, only handle note events
                events = [e for e in events if e.get('type') in ('note_on', 'note_off')]
                if Constants.DEBUG:
                    print("[SYNTH] System loaded - throttling to note events only")
                    
                for event in events:
                    result = self.message_router.route_message(event)
                    if result:
                        if result['type'] == 'voice_allocated':
                            self._handle_voice_allocation(result['voice'])
                        elif result['type'] == 'voice_released':
                            self._handle_voice_release(result['voice'])
                            
        except Exception as e:
            print(f"[ERROR] Event processing failed: {str(e)}")

    def cleanup(self):
        """Clean shutdown"""
        try:
            if Constants.DEBUG:
                print("\n[SYNTH] Starting cleanup...")
                
            # Release all notes
            for voice in self.voice_manager.active_notes.values():
                if voice.active and voice.synth_note:
                    self.synth.release(voice.synth_note)
                    
            self.active_notes.clear()
            
            if Constants.DEBUG:
                print("[SYNTH] Cleanup complete")
                
        except Exception as e:
            print(f"[ERROR] Cleanup failed: {str(e)}")
