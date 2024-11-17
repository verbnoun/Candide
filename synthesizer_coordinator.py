"""Main synthesizer coordinator with fixed voice handling and parameter updates"""
import time
import synthio
from synth_constants import Constants, ModSource, ModTarget
from mpe_handling import MPEVoiceManager, MPEParameterProcessor, MPEMessageRouter
from modulation_system import ModulationMatrix, LFOManager
from synthesis_engine import SynthesisEngine
from output_system import AudioOutputManager
from fixed_point_math import FixedPoint

class MPESynthesizer:
    def __init__(self, output_manager=None):
        self.output_manager = output_manager or AudioOutputManager()
        self.synth = synthio.Synthesizer(
            sample_rate=Constants.SAMPLE_RATE,
            channel_count=2
        )
        
        if Constants.DEBUG:
            print("[SYNTH] Synthesizer initialized")
        
        self.mod_matrix = ModulationMatrix()
        self.lfo_manager = LFOManager(self.mod_matrix)
        self.voice_manager = MPEVoiceManager()
        self.parameter_processor = MPEParameterProcessor(
            self.voice_manager,
            self.mod_matrix
        )
        self.message_router = MPEMessageRouter(
            self.voice_manager,
            self.parameter_processor
        )
        
        self.engine = SynthesisEngine(self.synth)
        self.output_manager.attach_synthesizer(self.synth)
        self.lfo_manager.attach_to_synth(self.synth)

        self.current_instrument = None
        self.active_notes = {}  # {(channel, note): last_params}
        self._last_update = time.monotonic()
        
    def _handle_voice_allocation(self, voice):
        if not voice:
            return
            
        channel_note = (voice.channel, voice.note)
        if channel_note in self.active_notes:
            if Constants.DEBUG:
                print(f"[SYNTH] Note already active: ch:{voice.channel} note:{voice.note}")
            return
            
        try:
            # Calculate initial frequency from MIDI note
            midi_note = voice.note
            frequency = synthio.midi_to_hz(midi_note)
            
            # Calculate initial amplitude from velocity (0-1)
            initial_velocity = voice.initial_state.get('velocity', 1.0)
            self.mod_matrix.set_source_value(ModSource.NOTE, voice.channel, midi_note)
            self.mod_matrix.set_source_value(ModSource.VELOCITY, voice.channel, initial_velocity)
            
            # Get base parameters through modulation
            params = self._collect_voice_parameters(voice)
            
            # Create note with proper frequency
            voice.synth_note = self.engine.create_note(
                frequency=frequency,
                amplitude=min(1.0, params['amplitude']),
                waveform_name=self.current_instrument.get('oscillator', {}).get('waveform', 'sine')
            )
            
            # Store initial parameter state
            self.active_notes[channel_note] = {
                'params': params,
                'last_update': time.monotonic()
            }
            
            self.synth.press(voice.synth_note)
            self.output_manager.performance.active_voices += 1

            if Constants.DEBUG:
                print(f"[SYNTH] Voice allocated - ch:{voice.channel} note:{voice.note}")
                print(f"[SYNTH] Initial freq:{frequency:.1f}Hz amp:{params['amplitude']:.3f}")
            
        except Exception as e:
            print(f"[ERROR] Voice allocation failed: {str(e)}")
            if channel_note in self.active_notes:
                del self.active_notes[channel_note]
            
    def _handle_voice_release(self, voice):
        if not voice:
            return
            
        channel_note = (voice.channel, voice.note)
        
        try:
            if voice.synth_note and channel_note in self.active_notes:
                if Constants.DEBUG:
                    print(f"[SYNTH] Releasing voice - ch:{voice.channel} note:{voice.note}")
                    
                self.synth.release(voice.synth_note)
                del self.active_notes[channel_note]
                
                if self.output_manager.performance.active_voices > 0:
                    self.output_manager.performance.active_voices -= 1
                    
        except Exception as e:
            print(f"[ERROR] Voice release failed: {str(e)}")
            
    def _should_update_params(self, old_params, new_params):
        """Check if parameter update is needed"""
        if not old_params or not new_params:
            return True
            
        for key in ('frequency', 'amplitude', 'filter_cutoff', 'filter_resonance'):
            if key not in old_params or key not in new_params:
                continue
                
            if abs(new_params[key] - old_params[key]) > 0.001:
                return True
                
        return False
        
    def update(self):
        try:
            current_time = time.monotonic()
            if (current_time - self._last_update) < 0.001:  # Limit update rate
                return
                
            # Update modulation
            for key, route in self.mod_matrix.routes.items():
                source, target, channel = key
                if route.needs_update:
                    source_value = self.mod_matrix.source_values.get(source, {}).get(channel, 0.0)
                    route.process(source_value)
                        
            # Update voices
            for channel_note, note_data in list(self.active_notes.items()):
                voice = self.voice_manager.get_voice(*channel_note)
                if not voice or not voice.active or not voice.synth_note:
                    continue
                    
                # Get new parameters
                new_params = self._collect_voice_parameters(voice)
                old_params = note_data['params']
                
                # Only update if parameters changed significantly
                if self._should_update_params(old_params, new_params):
                    if Constants.DEBUG:
                        print(f"[SYNTH] Updating parameters - ch:{channel_note[0]} note:{channel_note[1]}")
                    self.engine.update_note_parameters(voice, new_params)
                    note_data['params'] = new_params
                    note_data['last_update'] = current_time
                    
            self._last_update = current_time
            self.output_manager.update()
            
        except Exception as e:
            print(f"Update error: {str(e)}")
            
    def _collect_voice_parameters(self, voice):
        """Get all modulated parameters for a voice"""
        try:
            params = {
                'frequency': FixedPoint.to_float(
                    self.mod_matrix.get_target_value(ModTarget.OSC_PITCH, voice.channel)
                ),
                'amplitude': min(1.0, FixedPoint.to_float(
                    self.mod_matrix.get_target_value(ModTarget.AMPLITUDE, voice.channel)
                )),
                'filter_cutoff': FixedPoint.to_float(
                    self.mod_matrix.get_target_value(ModTarget.FILTER_CUTOFF, voice.channel)
                ),
                'filter_resonance': FixedPoint.to_float(
                    self.mod_matrix.get_target_value(ModTarget.FILTER_RESONANCE, voice.channel)
                )
            }
            return params
        except Exception as e:
            print(f"[ERROR] Parameter collection failed: {str(e)}")
            return {}

    def set_instrument(self, instrument_config):
        if not instrument_config:
            return
            
        if Constants.DEBUG:
            print("[SYNTH] Setting new instrument configuration")
        
        self.current_instrument = instrument_config
        self.engine.current_instrument = instrument_config
        self.message_router.set_instrument_config(instrument_config)
            
        # Clear and rebuild modulation routing
        self.mod_matrix.routes.clear()
        self.mod_matrix.add_route(ModSource.NOTE, ModTarget.OSC_PITCH, amount=1.0)
        
        # Get performance settings
        perf = instrument_config.get('performance', {})
        velocity_sensitivity = perf.get('velocity_sensitivity', 1.0)
        
        if velocity_sensitivity > 0:
            self.mod_matrix.add_route(
                ModSource.VELOCITY, 
                ModTarget.AMPLITUDE,
                amount=velocity_sensitivity
            )
        
        # Add performance-based routes
        if perf.get('pressure_enabled', False):
            if perf.get('pressure_sensitivity', 0) > 0:
                self.mod_matrix.add_route(
                    ModSource.PRESSURE,
                    ModTarget.AMPLITUDE,
                    amount=perf.get('pressure_sensitivity', Constants.DEFAULT_PRESSURE_SENSITIVITY)
                )
        
        if perf.get('pitch_bend_enabled', False):
            if perf.get('pitch_bend_range', 0) > 0:
                self.mod_matrix.add_route(
                    ModSource.PITCH_BEND,
                    ModTarget.OSC_PITCH,
                    amount=perf.get('pitch_bend_range', 2) / 12.0
                )
        
        # Add custom modulation routes
        if 'modulation' in instrument_config:
            for route in instrument_config['modulation']:
                source = route['source']
                if ((source == ModSource.PRESSURE and not perf.get('pressure_enabled', False)) or
                    (source == ModSource.PITCH_BEND and not perf.get('pitch_bend_enabled', False))):
                    continue
                    
                self.mod_matrix.add_route(
                    source,
                    route['target'],
                    route.get('amount', 1.0)
                )

    def process_mpe_events(self, events):
        if not events:
            return
            
        if self.output_manager.performance.should_throttle():
            events = [e for e in events if e.get('type') in ('note_on', 'note_off')]
            if Constants.DEBUG:
                print("[SYNTH] System loaded - throttling messages")
            
        for event in events:
            result = self.message_router.route_message(event)
            if result:
                if result['type'] == 'voice_allocated':
                    self._handle_voice_allocation(result['voice'])
                elif result['type'] == 'voice_released':
                    self._handle_voice_release(result['voice'])

    def cleanup(self):
        try:
            if Constants.DEBUG:
                print("[SYNTH] Starting cleanup...")
                
            # Release all active notes
            for voice in self.voice_manager.active_voices.values():
                if voice.active and voice.synth_note:
                    self.synth.release(voice.synth_note)
                    
            self.active_notes.clear()
                    
            if not hasattr(self, '_output_manager_provided'):
                self.output_manager.cleanup()
                
            if Constants.DEBUG:
                print("[SYNTH] Cleanup complete")
            
        except Exception as e:
            print(f"Cleanup error: {str(e)}")