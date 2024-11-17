import time
import synthio
from synth_constants import Constants, ModSource, ModTarget
from mpe_handling import MPEVoiceManager, MPEParameterProcessor, MPEMessageRouter
from modulation_system import ModulationMatrix, LFOManager
from synthesis_engine import SynthesisEngine
from output_system import AudioOutputManager
from fixed_point_math import FixedPoint

class MPESynthesizer:
    """Main synthesizer coordinator
    
    MPE Signal Flow Overview:
    1. MIDI Input -> MPEMessageRouter
       Routes note on/off and control messages
       Captures initial control values before note-on
       Filters out MPE messages based on instrument config
    
    2. MPEVoiceManager
       Tracks voice/channel mapping and initial control state
       Stores pre-note control values
       Applies initial values during voice allocation
    
    3. MPEParameterProcessor -> ModulationMatrix
       Handles ongoing control value updates after note-on
       Routes modulation based on instrument config
    
    4. ModulationMatrix -> SynthesisEngine
       Applies modulation only for enabled performance features
       Note: initial values bypass modulation matrix
    """
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

        # Track current instrument configuration
        self.current_instrument = None
        
    def _handle_voice_allocation(self, voice):
        """Handle new voice allocation with initial control values"""
        if voice and not voice.synth_note:
            initial_state = voice.initial_state

            # Get base frequency from note number
            frequency = FixedPoint.to_float(
                self.mod_matrix.get_target_value(ModTarget.OSC_PITCH, voice.channel)
            )

            # Apply initial pitch bend if enabled
            if self.current_instrument and \
            self.current_instrument['performance'].get('pitch_bend_enabled', False):
                bend_range = self.current_instrument['performance'].get('pitch_bend_range', 2)
                bend_amount = initial_state['bend'] * (bend_range / 12.0)  # convert semitones to ratio
                frequency *= pow(2, bend_amount)

            # Ensure frequency is in valid range
            frequency = max(20.0, min(frequency, 20000.0))

            # Get velocity-based amplitude
            amplitude = initial_state['velocity']

            # Apply initial pressure if enabled
            if self.current_instrument and \
            self.current_instrument['performance'].get('pressure_enabled', False):
                pressure_sens = self.current_instrument['performance'].get('pressure_sensitivity', 1.0)
                amplitude *= (1.0 + (initial_state['pressure'] * pressure_sens))

            # Clamp final amplitude
            amplitude = max(0.0, min(amplitude, 1.0))

            # Create the note with initial values
            voice.synth_note = self.engine.create_note(frequency, amplitude)

            # Apply initial timbre via filter if configured
            if self.current_instrument and 'filter' in self.current_instrument:
                filter_config = self.current_instrument['filter']
                cutoff = filter_config['cutoff']
                if self.current_instrument['performance'].get('pressure_enabled', False):
                    # Modify cutoff based on initial timbre value
                    cutoff *= (1.0 + initial_state['timbre'])
                voice.synth_note.filter = self.engine.filter_manager.create_filter(
                    cutoff=cutoff,
                    resonance=filter_config.get('resonance', 0.7)
                )

            # Start the note
            self.synth.press(voice.synth_note)
            self.output_manager.performance.active_voices += 1

            if Constants.DEBUG:
                print("[SYNTH] Voice allocated: ch={0}, note={1}, freq={2:.2f}Hz, amp={3:.2f}".format(
                    voice.channel, voice.note, frequency, amplitude))
            
    def _handle_voice_release(self, voice):
        """Handle voice release"""
        if voice and voice.synth_note:
            self.synth.release(voice.synth_note)
            self.output_manager.performance.active_voices -= 1
            
            if Constants.DEBUG:
                print(f"[SYNTH] Voice released: ch={voice.channel}, note={voice.note}")
    
    def set_instrument(self, instrument_config):
        """Configure synthesizer with new instrument settings"""
        if not instrument_config:
            return
            
        if Constants.DEBUG:
            print("[SYNTH] Setting new instrument configuration")
        
        self.current_instrument = instrument_config
        
        # Update message router with new instrument config
        self.message_router.set_instrument_config(instrument_config)
            
        # Update synthesis parameters
        if 'oscillator' in instrument_config:
            osc = instrument_config['oscillator']
            if 'waveform' in osc:
                self.engine.waveform_manager.get_waveform(osc['waveform'])
                
        # Clear ALL existing routes
        self.mod_matrix.routes.clear()
        
        # Essential routes that are ALWAYS active
        self.mod_matrix.add_route(ModSource.NOTE, ModTarget.OSC_PITCH, amount=1.0)
        
        # Get performance settings
        perf = instrument_config.get('performance', {})
        velocity_sensitivity = perf.get('velocity_sensitivity', 1.0)
        
        # Velocity to amplitude (if velocity sensitivity > 0)
        if velocity_sensitivity > 0:
            self.mod_matrix.add_route(
                ModSource.VELOCITY, 
                ModTarget.AMPLITUDE,
                amount=velocity_sensitivity
            )

        # Only add performance-based routes if explicitly enabled
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
        
        # Add custom modulation routings if allowed by performance settings
        if 'modulation' in instrument_config:
            for route in instrument_config['modulation']:
                source = route['source']
                if ((source == ModSource.PRESSURE and not perf.get('pressure_enabled', False)) or
                    (source == ModSource.PITCH_BEND and not perf.get('pitch_bend_enabled', False))):
                    if Constants.DEBUG:
                        print(f"[SYNTH] Skipping disabled route source: {source}")
                    continue
                    
                self.mod_matrix.add_route(
                    source,
                    route['target'],
                    route.get('amount', 1.0)
                )
                
        # Update performance settings
        if 'performance' in instrument_config:
            perf = instrument_config['performance']
            self.parameter_processor.config.pressure_sensitivity = perf.get(
                'pressure_sensitivity',
                Constants.DEFAULT_PRESSURE_SENSITIVITY
            )
            
    def process_mpe_events(self, events):
        """Process incoming MPE messages"""
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
                    
    def update(self):
        """Main update loop
        
        Note: Initial control values bypass modulation matrix.
        Only ongoing control changes after note-on use modulation.
        """
        try:
            # Update modulation from MPE parameters
            for key, route in self.mod_matrix.routes.items():
                if route.needs_update:
                    source_value = self.mod_matrix.source_values.get(key[0], {}).get(key[2], 0.0)
                    route.process(source_value)
                    
            # Update synthesis engine parameters for active voices
            for voice in self.voice_manager.active_voices.values():
                if voice.active and voice.synth_note:
                    params = self._collect_voice_parameters(voice)
                    self.engine.update_note_parameters(voice, params)
                    
            # Update audio system
            self.output_manager.update()
            
        except Exception as e:
            print("Update error: {0}".format(str(e)))
            
    def _collect_voice_parameters(self, voice):
        """Collect all modulated parameters for a voice"""
        return {
            'frequency': FixedPoint.to_float(self.mod_matrix.get_target_value(ModTarget.OSC_PITCH, voice.channel)),
            'amplitude': FixedPoint.to_float(self.mod_matrix.get_target_value(ModTarget.AMPLITUDE, voice.channel)),
            'filter_cutoff': FixedPoint.to_float(self.mod_matrix.get_target_value(ModTarget.FILTER_CUTOFF, voice.channel)),
            'filter_resonance': FixedPoint.to_float(self.mod_matrix.get_target_value(ModTarget.FILTER_RESONANCE, voice.channel))
        }

    def cleanup(self):
        """Clean shutdown"""
        try:
            if Constants.DEBUG:
                print("[SYNTH] Starting cleanup...")
                
            for voice in self.voice_manager.active_voices.values():
                if voice.active and voice.synth_note:
                    self.synth.release(voice.synth_note)
                    
            if not hasattr(self, '_output_manager_provided'):
                self.output_manager.cleanup()
                
            if Constants.DEBUG:
                print("[SYNTH] Cleanup complete")
            
        except Exception as e:
            print("Cleanup error: {0}".format(str(e)))
