import time
import synthio
from synth_constants import Constants, ModSource, ModTarget
from mpe_handling import MPEVoiceManager, MPEParameterProcessor, MPEMessageRouter
from modulation_system import ModulationMatrix, LFOManager
from synthesis_engine import SynthesisEngine
from output_system import AudioOutputManager
from fixed_point_math import FixedPoint

class MPESynthesizer:
    """Main synthesizer coordinator"""
    def __init__(self, output_manager=None):
        # Use provided output manager or create new one
        self.output_manager = output_manager or AudioOutputManager()
        self.synth = synthio.Synthesizer(
            sample_rate=Constants.SAMPLE_RATE,
            channel_count=2
        )
        
        # Initialize modulation system
        self.mod_matrix = ModulationMatrix()
        self.lfo_manager = LFOManager(self.mod_matrix)
        
        # Initialize voice management
        self.voice_manager = MPEVoiceManager()
        self.parameter_processor = MPEParameterProcessor(
            self.voice_manager,
            self.mod_matrix
        )
        self.message_router = MPEMessageRouter(
            self.voice_manager,
            self.parameter_processor
        )
        
        # Initialize synthesis engine
        self.engine = SynthesisEngine(self.synth)
        
        # Set up audio chain
        self.output_manager.attach_synthesizer(self.synth)
        
        # Attach global LFOs
        self.lfo_manager.attach_to_synth(self.synth)
        
    def process_mpe_events(self, events):
        """Process incoming MPE messages"""
        if not events:
            return
            
        if self.output_manager.performance.should_throttle():
            # If system is heavily loaded, prioritize note events
            events = [e for e in events if e.get('type') in ('note_on', 'note_off')]
            
        for event in events:
            result = self.message_router.route_message(event)
            if result:
                if result['type'] == 'voice_allocated':
                    self._handle_voice_allocation(result['voice'])
                elif result['type'] == 'voice_released':
                    self._handle_voice_release(result['voice'])
                    
    def _handle_voice_allocation(self, voice):
        """Handle new voice allocation"""
        if voice and not voice.synth_note:
            # Create new synthio note
            frequency = FixedPoint.to_float(
                self.mod_matrix.get_target_value(ModTarget.OSC_PITCH, voice.channel)
            )
            
            voice.synth_note = self.engine.create_note(frequency, voice.velocity)
            self.synth.press(voice.synth_note)
            self.output_manager.performance.active_voices += 1
            
    def _handle_voice_release(self, voice):
        """Handle voice release"""
        if voice and voice.synth_note:
            self.synth.release(voice.synth_note)
            self.output_manager.performance.active_voices -= 1
            
    def update(self):
        """Main update loop"""
        try:
            # Update modulation
            for key, route in self.mod_matrix.routes.items():
                if route.needs_update:
                    route.update()
                    
            # Update synthesis engine parameters for active voices
            for voice in self.voice_manager.active_voices.values():
                if voice.active and voice.synth_note:
                    params = self._collect_voice_parameters(voice)
                    self.engine.update_note_parameters(voice, params)
                    
            # Update audio system
            self.output_manager.update()
            
        except Exception as e:
            print(f"Update error: {str(e)}")
            
    def _collect_voice_parameters(self, voice):
        """Collect all modulated parameters for a voice"""
        return {
            'frequency': self.mod_matrix.get_target_value(ModTarget.OSC_PITCH, voice.channel),
            'amplitude': self.mod_matrix.get_target_value(ModTarget.AMPLITUDE, voice.channel),
            'filter_cutoff': self.mod_matrix.get_target_value(ModTarget.FILTER_CUTOFF, voice.channel),
            'filter_resonance': self.mod_matrix.get_target_value(ModTarget.FILTER_RESONANCE, voice.channel)
        }
        
    def set_instrument(self, instrument_config):
        """Configure synthesizer with new instrument settings"""
        if not instrument_config:
            return
            
        # Update synthesis parameters
        if 'oscillator' in instrument_config:
            osc = instrument_config['oscillator']
            if 'waveform' in osc:
                self.engine.waveform_manager.get_waveform(osc['waveform'])
                
        # Update modulation routings
        self.mod_matrix.routes.clear()
        if 'modulation' in instrument_config:
            for route in instrument_config['modulation']:
                self.mod_matrix.add_route(
                    route['source'],
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
            
    def cleanup(self):
        """Clean shutdown"""
        try:
            # Release all active voices
            for voice in self.voice_manager.active_voices.values():
                if voice.active and voice.synth_note:
                    self.synth.release(voice.synth_note)
                    
            # Clean up audio system only if we created it
            if not hasattr(self, '_output_manager_provided'):
                self.output_manager.cleanup()
            
        except Exception as e:
            print(f"Cleanup error: {str(e)}")
