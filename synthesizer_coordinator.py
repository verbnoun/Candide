"""Main synthesizer coordinator with gate-based envelope and config-driven routing"""
import time
import synthio
from synth_constants import Constants, ModSource, ModTarget, CCMapping
from mpe_handling import MPEVoiceManager, MPEParameterProcessor, MPEMessageRouter
from modulation_system import ModulationMatrix, LFOManager
from synthesis_engine import SynthesisEngine
from fixed_point_math import FixedPoint

class MPESynthesizer:
    def __init__(self, output_manager):
        if Constants.DEBUG:
            print("\n[SYNTH] Initializing MPE Synthesizer")
            
        if not output_manager:
            raise ValueError("AudioOutputManager required")
            
        self.output_manager = output_manager

        # Initialize base synthesizer
        self.synth = synthio.Synthesizer(
            sample_rate=Constants.SAMPLE_RATE,
            channel_count=2
        )
        
        if Constants.DEBUG:
            print("[SYNTH] Base synthesizer initialized")

        # Initialize synthesis components in dependency order
        self.voice_manager = MPEVoiceManager()
        self.parameter_processor = MPEParameterProcessor(self.voice_manager, None)  # mod_matrix added later
        self.lfo_manager = LFOManager(None, None, None, self.synth)  # mod_matrix added later
        
        self.mod_matrix = ModulationMatrix(
            self.voice_manager,
            self.parameter_processor, 
            self.lfo_manager,
            self.synth,
            self.output_manager
        )
        
        # Update components with mod_matrix reference 
        self.parameter_processor.mod_matrix = self.mod_matrix
        self.lfo_manager.mod_matrix = self.mod_matrix

        self.message_router = MPEMessageRouter(
            self.voice_manager,
            self.parameter_processor,
            self.mod_matrix
        )

        # Initialize synthesis engine
        self.engine = SynthesisEngine(self.synth)
        
        # Attach to audio output
        self.output_manager.attach_synthesizer(self.synth)

        self.current_instrument = None
        self.active_notes = {}
        self._last_update = time.monotonic()
        self._cc_values = {}  # Track CC values per channel

        if Constants.DEBUG:
            print("[SYNTH] All subsystems initialized")
            
    def _handle_voice_allocation(self, voice):
        """Handle new voice allocation with envelope gating"""
        if not voice:
            return
            
        channel_note = (voice.channel, voice.note)
        if channel_note in self.active_notes:
            if Constants.DEBUG:
                print(f"[SYNTH] Note already active: ch:{voice.channel} note:{voice.note}")
            return
            
        try:
            if Constants.DEBUG:
                print(f"\n[SYNTH] Allocating voice:")
                print(f"      Channel: {voice.channel}")
                print(f"      Note: {voice.note}")
                print(f"      Velocity: {FixedPoint.to_float(voice.initial_state['velocity']):.3f}")
            
            # Calculate initial frequency
            frequency = synthio.midi_to_hz(voice.note)
            
            # Set initial modulation values
            self.mod_matrix.set_source_value(
                ModSource.NOTE, 
                voice.channel,
                FixedPoint.to_float(FixedPoint.midi_note_to_fixed(voice.note))
            )
            
            initial_velocity = FixedPoint.to_float(voice.initial_state['velocity'])
            self.mod_matrix.set_source_value(
                ModSource.VELOCITY,
                voice.channel,
                initial_velocity
            )
            
            # Get initial parameters through modulation
            params = self._collect_voice_parameters(voice)
            
            # Create note with instrument's config
            voice.synth_note = self.engine.create_note(
                frequency=params.get('frequency', frequency),
                amplitude=min(1.0, params['amplitude']),
                waveform_name=self.current_instrument.get('oscillator', {}).get('waveform', 'sine')
            )
            
            # Store initial state
            self.active_notes[channel_note] = {
                'params': params,
                'last_update': time.monotonic(),
                'note_obj': voice.synth_note
            }
            
            # Start note and trigger envelope
            self.synth.press(voice.synth_note)
            self.mod_matrix.set_gate_state(voice.channel, 'note_on', True)
            self.lfo_manager.handle_gate('note_on', True)
            
            self.output_manager.performance.active_voices += 1

            if Constants.DEBUG:
                print("[SYNTH] Voice successfully allocated")
            
        except Exception as e:
            print(f"[ERROR] Voice allocation failed: {str(e)}")
            if channel_note in self.active_notes:
                del self.active_notes[channel_note]
            
    def _handle_voice_release(self, voice):
        """Handle voice release with envelope gating"""
        if not voice:
            return
            
        channel_note = (voice.channel, voice.note)
        
        try:
            if voice.synth_note and channel_note in self.active_notes:
                if Constants.DEBUG:
                    print(f"\n[SYNTH] Releasing voice:")
                    print(f"      Channel: {voice.channel}")
                    print(f"      Note: {voice.note}")
                    
                # Trigger release
                self.mod_matrix.set_gate_state(voice.channel, 'note_off', True)
                self.synth.release(voice.synth_note)
                
                del self.active_notes[channel_note]
                
                if self.output_manager.performance.active_voices > 0:
                    self.output_manager.performance.active_voices -= 1
                    
                if Constants.DEBUG:
                    print("[SYNTH] Voice successfully released")
                    
        except Exception as e:
            print(f"[ERROR] Voice release failed: {str(e)}")
            
    def _should_update_params(self, old_params, new_params):
        """Check if parameter update is needed"""
        if not old_params or not new_params:
            return True
            
        for key in ('frequency', 'amplitude', 'filter_cutoff', 'filter_resonance', 'detune'):
            if key not in old_params or key not in new_params:
                continue
                
            if abs(new_params[key] - old_params[key]) > 0.001:
                return True
                
        return False
        
    def update(self):
        """Update all voice parameters and modulation"""
        try:
            current_time = time.monotonic()
            if (current_time - self._last_update) < 0.001:
                return
                
            # Process envelope gates
            self.message_router.process_updates()
                
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
                
                # Update if needed
                if self._should_update_params(old_params, new_params):
                    if Constants.DEBUG:
                        print(f"\n[SYNTH] Updating voice parameters:")
                        print(f"      Channel: {channel_note[0]}")
                        print(f"      Note: {channel_note[1]}")
                        for k, v in new_params.items():
                            if old_params.get(k) != v:
                                print(f"      {k}: {v:.3f} (was {old_params.get(k, 0):.3f})")
                                
                    self.engine.update_note_parameters(voice, new_params)
                    note_data['params'] = new_params
                    note_data['last_update'] = current_time
                    
            self._last_update = current_time
            self.output_manager.update()
            
        except Exception as e:
            print(f"[ERROR] Update error: {str(e)}")
            
    def _collect_voice_parameters(self, voice):
        """Get all modulated parameters for a voice"""
        try:
            # Get envelope level using note_info
            envelope_level = 1.0
            current_stage = 'attack'
            
            if voice.synth_note:
                envelope_state, envelope_value = self.synth.note_info(voice.synth_note)
                
                if envelope_state is not None:
                    # Map envelope state to stage names
                    stage_map = {
                        synthio.EnvelopeState.ATTACK: 'attack',
                        synthio.EnvelopeState.DECAY: 'decay',
                        synthio.EnvelopeState.SUSTAIN: 'sustain',
                        synthio.EnvelopeState.RELEASE: 'release'
                    }
                    
                    envelope_level = envelope_value
                    current_stage = stage_map.get(envelope_state, 'attack')
                    
                    if Constants.DEBUG:
                        print(f"[ENV] Envelope State: {current_stage}")
                        print(f"[ENV] Envelope Level: {envelope_level:.3f}")
            
            # Retrieve base frequency from modulation matrix
            base_frequency = FixedPoint.to_float(
                self.mod_matrix.get_target_value(ModTarget.OSC_PITCH, voice.channel)
            )
            
            # Handle detune configuration
            detune_value = 0.0
            if (self.current_instrument and 
                'oscillator' in self.current_instrument and 
                'detune_control' in self.current_instrument['oscillator']):
                detune_config = self.current_instrument['oscillator']['detune_control']
                
                # Check for initial static value
                detune_value = detune_config.get('initial_value', 0.0)
                
                # If CC is defined, it takes precedence
                if 'cc' in detune_config:
                    # Retrieve CC value from tracked values
                    cc_value = self._cc_values.get((voice.channel, detune_config['cc']), 0.0)
                    
                    # Map CC value to detune range
                    min_detune = detune_config.get('range', {}).get('min', -0.01)
                    max_detune = detune_config.get('range', {}).get('max', 0.01)
                    detune_value = min_detune + cc_value * (max_detune - min_detune)
            
            # Collect parameters
            params = {
                'frequency': base_frequency * (1 + detune_value),
                'amplitude': min(1.0, FixedPoint.to_float(
                    self.mod_matrix.get_target_value(ModTarget.AMPLITUDE, voice.channel)
                ) * envelope_level),
                'filter_cutoff': FixedPoint.to_float(
                    self.mod_matrix.get_target_value(ModTarget.FILTER_CUTOFF, voice.channel)
                ),
                'filter_resonance': FixedPoint.to_float(
                    self.mod_matrix.get_target_value(ModTarget.FILTER_RESONANCE, voice.channel)
                ),
                'detune': detune_value
            }
            
            if Constants.DEBUG:
                print(f"\n[SYNTH] Collected parameters for voice:")
                print(f"      Channel: {voice.channel}")
                print(f"      Note: {voice.note}")
                print(f"      Base Frequency: {base_frequency:.3f}")
                print(f"      Detune Value: {detune_value:.3f}")
                print(f"      Final Frequency: {params['frequency']:.3f}")
                print(f"      Envelope Stage: {current_stage}")
                print(f"      Envelope Level: {envelope_level:.3f}")
                for k, v in params.items():
                    print(f"      {k}: {v:.3f}")
                    
            return params
            
        except Exception as e:
            print(f"[ERROR] Parameter collection failed: {str(e)}")
            return {}

    def process_mpe_events(self, events):
        """Process incoming MPE messages"""
        if not events:
            return
            
        if Constants.DISABLE_THROTTLING or not self.output_manager.performance.should_throttle():
            for event in events:
                # Track CC values only for routed CCs
                if event.get('type') == 'cc':
                    channel = event.get('channel', 0)
                    cc_number = event.get('cc', 0)
                    
                    # Process CC through modulation matrix
                    processed_value = self.mod_matrix.process_cc(cc_number, event.get('value', 0), channel)
                    
                    # Only store and track if CC is routed
                    if processed_value is not None:
                        self._cc_values[(channel, cc_number)] = processed_value
                        
                        if Constants.DEBUG:
                            print(f"[SYNTH] Tracked routed CC: {cc_number}, Value: {processed_value:.3f}")
                
                result = self.message_router.route_message(event)
                if result:
                    if result['type'] == 'voice_allocated':
                        self._handle_voice_allocation(result['voice'])
                    elif result['type'] == 'voice_released':
                        self._handle_voice_release(result['voice'])
        else:
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

    def set_instrument(self, instrument_config):
        """Configure synthesizer from instrument config"""
        if not instrument_config:
            return
            
        if Constants.DEBUG:
            print(f"\n[SYNTH] Setting instrument: {instrument_config['name']}")
        
        self.current_instrument = instrument_config
        self.engine.current_instrument = instrument_config
        
        # Configure subsystems in correct order
        self.voice_manager.set_instrument_config(instrument_config)
        self.parameter_processor.set_instrument_config(instrument_config)
        
        # Let message router handle all modulation configuration
        self.message_router.set_instrument_config(instrument_config)
        
        # Configure LFOs after modulation matrix is set up
        self.lfo_manager.configure_from_instrument(instrument_config, self.synth)
            
        if Constants.DEBUG:
            print("[SYNTH] Instrument configuration complete")

    def cleanup(self):
        """Clean shutdown"""
        try:
            if Constants.DEBUG:
                print("\n[SYNTH] Starting cleanup...")
                
            # Release all notes
            for voice in list(self.voice_manager.active_voices.values()):
                if voice.active and voice.synth_note:
                    self.synth.release(voice.synth_note)
                    
            self.active_notes.clear()
                
            if Constants.DEBUG:
                print("[SYNTH] Cleanup complete")
            
        except Exception as e:
            print(f"Cleanup error: {str(e)}")
