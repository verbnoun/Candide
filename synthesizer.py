import synthio
from synthesis_modules import (
    FixedPoint, Constants, Voice, SynthEngine, 
    SynthAudioOutputManager, ModulationMatrix,
    MPEProcessor, ModSource, ModTarget
)
import supervisor

class Synthesizer:
    def __init__(self, audio_output_manager):
        self.synth_engine = SynthEngine()
        self.audio_output_manager = audio_output_manager
        self.synth = self.audio_output_manager.get_synth()
        self.max_amplitude = FixedPoint.from_float(0.9)
        self.instrument = None
        self.current_midi_values = {}
        
        # Initialize modulation system
        self.mod_matrix = ModulationMatrix()
        self.mpe_processor = MPEProcessor(self.mod_matrix)
        
        # Set up default modulation routes
        self._setup_default_modulation_routes()
        
        # Initialize parameter tracking
        self.last_parameter_values = {
            'filter_cutoff': None,
            'filter_resonance': None,
            'detune_amount': None,
            'attack_time': None,
            'decay_time': None,
            'sustain_level': None,
            'release_time': None,
            'bend_range': None,
            'bend_curve': None
        }
        
        # Initialize voices with output manager reference
        self.active_voices = [Voice(output_manager=self.audio_output_manager) for _ in range(Constants.MAX_ACTIVE_NOTES)]

    def _setup_default_modulation_routes(self):
        """Set up default modulation routing"""
        # Pressure modulation defaults
        self.mod_matrix.add_route(ModSource.PRESSURE, ModTarget.FILTER_CUTOFF, 0.5)
        self.mod_matrix.add_route(ModSource.PRESSURE, ModTarget.AMP_LEVEL, 0.3)
        
        # Pitch bend defaults
        self.mod_matrix.add_route(ModSource.PITCH_BEND, ModTarget.OSC_DETUNE, 1.0)
        
        # Timbre modulation defaults
        self.mod_matrix.add_route(ModSource.TIMBRE, ModTarget.FILTER_RESONANCE, 0.4)
        
        # Velocity modulation
        self.mod_matrix.add_route(ModSource.VELOCITY, ModTarget.AMP_LEVEL, 1.0)
        self.mod_matrix.add_route(ModSource.VELOCITY, ModTarget.ENV_ATTACK, -0.3)

    def prepare_note_parameters(self, channel, velocity):
        """Handle MPE note setup sequence before note-on"""
        target_voice = None
        for voice in self.active_voices:
            if not voice.active:
                target_voice = voice
                break
                
        if not target_voice:
            return None
            
        # Initialize the voice
        target_voice.channel = channel
        target_voice.velocity = FixedPoint.normalize_midi_value(velocity)
        self.mod_matrix.set_source_value(ModSource.VELOCITY, FixedPoint.to_float(target_voice.velocity))
        
        # Store initial MPE values
        initial_bend = self.current_midi_values.get(f'pitch_bend_{channel}', 8192)
        initial_timbre = self.current_midi_values.get(f'cc74_{channel}', 0)
        initial_pressure = self.current_midi_values.get(f'pressure_{channel}', 0)
        initial_envelope = self.synth_engine.envelope_settings.copy()
        
        target_voice.store_initial_parameters(
            pitch_bend=initial_bend,
            timbre=initial_timbre,
            pressure=initial_pressure,
            envelope=initial_envelope
        )
        
        return target_voice

    def _handle_pressure(self, channel, pressure_value):
        """Handle per-channel pressure using MPE processor"""
        for voice in self.active_voices:
            if voice.active and voice.channel == channel:
                if self.mpe_processor.process_pressure(voice, pressure_value):
                    self._update_voice_parameters(voice)

    def _handle_pitch_bend(self, channel, bend_value):
        """Handle per-channel pitch bend using MPE processor"""
        self.current_midi_values[f'pitch_bend_{channel}'] = bend_value
        bend_value = max(0, min(16383, bend_value))
        
        for voice in self.active_voices:
            if voice.active and voice.channel == channel:
                if self.mpe_processor.process_pitch_bend(voice, bend_value):
                    voice.synth_note.bend = FixedPoint.to_float(
                        self.mod_matrix.get_target_value(ModTarget.OSC_DETUNE)
                    )

    def _handle_cc(self, channel, cc_number, value):
        """Handle CC messages with modulation matrix integration"""
        norm_value = FixedPoint.normalize_midi_value(value)
        self.current_midi_values[cc_number] = value
        
        # Handle timbre (CC 74)
        if cc_number == 74:
            for voice in self.active_voices:
                if voice.active and voice.channel == channel:
                    if self.mpe_processor.process_timbre(voice, value):
                        # Update filter resonance based on timbre route
                        self.synth_engine.set_filter_resonance(
                            FixedPoint.to_float(
                                self.mod_matrix.get_target_value(ModTarget.FILTER_RESONANCE)
                            )
                        )

    def _update_voice_parameters(self, voice):
        """Update voice parameters based on modulation matrix"""
        if voice.synth_note:
            # Update filter cutoff
            cutoff = FixedPoint.to_float(
                self.mod_matrix.get_target_value(ModTarget.FILTER_CUTOFF)
            )
            self.synth_engine.set_filter_cutoff(cutoff)
            
            # Update amplitude
            amp_level = FixedPoint.to_float(
                self.mod_matrix.get_target_value(ModTarget.AMP_LEVEL)
            )
            voice.synth_note.amplitude = amp_level
            
            # Recreate envelope with modulated attack
            attack_time = FixedPoint.to_float(
                self.mod_matrix.get_target_value(ModTarget.ENV_ATTACK)
            )
            current_envelope = self.synth_engine.envelope_settings
            current_envelope['attack'] = FixedPoint.from_float(
                max(0.001, min(10.0, current_envelope['attack'] + attack_time))
            )
            
            new_envelope = self.synth_engine.create_envelope()
            voice.synth_note.envelope = new_envelope

    def process_mpe_events(self, events):
        """Process MPE events"""
        if not events:
            return
            
        for event in events:
            if not isinstance(event, dict):
                continue
                
            event_type = event.get('type')
            channel = event.get('channel')
            data = event.get('data', {})
            
            if not all([event_type, channel is not None, data]):
                continue

            if event_type == 'note_on':
                if all(voice.active for voice in self.active_voices):
                    continue
                self._handle_note_on(channel, data['note'], data['velocity'])
            elif event_type == 'note_off':
                self._handle_note_off(channel, data['note'])
            elif event_type == 'pressure':
                self._handle_pressure(channel, data['value'])
            elif event_type == 'pitch_bend':
                self._handle_pitch_bend(channel, data['value'])
            elif event_type == 'cc':
                self._handle_cc(channel, data['number'], data['value'])

    def _handle_note_on(self, channel, note, velocity):
        """Handle MPE note-on event with proper initialization"""
        if note is None or not isinstance(note, int):
            return
            
        # Prepare the voice with initial MPE parameters
        target_voice = self.prepare_note_parameters(channel, velocity)
        
        if not target_voice:
            return
            
        # Configure the voice with note information
        target_voice.note = note
        target_voice.active = True
        
        try:
            # Create synthio note with initial parameters
            frequency = self._fractional_midi_to_hz(note)
            
            # Use initial envelope settings from prepared voice
            initial_envelope_settings = target_voice.initial_parameters['envelope']
            self.synth_engine.envelope_settings = initial_envelope_settings
            
            envelope = self.synth_engine.create_envelope()
            waveform = self.synth_engine.get_waveform(self.instrument.oscillator['waveform'])
            
            synth_note = synthio.Note(
                frequency=frequency,
                envelope=envelope,
                amplitude=FixedPoint.to_float(target_voice.velocity),
                waveform=waveform,
                bend=0.0,
                panning=0.0
            )
            
            if self.synth_engine.filter:
                synth_note.filter = self.synth_engine.filter(self.synth)
                
            target_voice.synth_note = synth_note
            self.synth.press([synth_note])
            
        except Exception as e:
            target_voice.active = False

    def _handle_note_off(self, channel, note):
        """Handle MPE note-off event"""
        for voice in self.active_voices:
            if voice.active and voice.channel == channel and voice.note == note:
                if voice.synth_note:
                    self.synth.release([voice.synth_note])
                voice.active = False
                break

    def set_instrument(self, instrument):
        self.instrument = instrument
        self.synth_engine.set_instrument(instrument)
        self._configure_synthesizer()
        self._re_evaluate_midi_values()

    def _configure_synthesizer(self):
        if self.instrument:
            config = self.instrument.get_configuration()

            if 'oscillator' in config:
                self.synth_engine.configure_oscillator(config['oscillator'])
            if 'filter' in config:
                self.synth_engine.set_filter(config['filter'])

    def _re_evaluate_midi_values(self):
        for cc_number, midi_value in self.current_midi_values.items():
            self._handle_cc(0, cc_number, midi_value)

    def update(self):
        """Main update loop for synth engine"""
        current_time = supervisor.ticks_ms()
        
        # Handle timeouts and voice updates
        try:
            for voice in self.active_voices:
                if voice.active:
                    # Check for timeout
                    if current_time - voice.timestamp >= Constants.NOTE_TIMEOUT_MS:
                        self._handle_note_off(voice.channel, voice.note)
                    
                    if voice.pressure > 0:
                        self._handle_pressure(voice.channel, voice.pressure)
                    if voice.pitch_bend != 0:
                        self._handle_pitch_bend(voice.channel, voice.pitch_bend)
            
            self.synth_engine.update()
            
        except Exception as e:
            pass

    def stop(self):
        """Clean shutdown"""
        try:
            active_notes = []
            for voice in self.active_voices:
                if voice.active and voice.synth_note:
                    active_notes.append(voice.synth_note)
                    voice.active = False
                    
            if active_notes:
                self.synth.release(active_notes)
                
            self.audio_output_manager.stop()
            
        except Exception as e:
            pass

    def _fractional_midi_to_hz(self, midi_note):
        # First, check if it's an exact MIDI note in the lookup table
        if isinstance(midi_note, int) and midi_note in Constants.MIDI_FREQUENCIES:
            return Constants.MIDI_FREQUENCIES[midi_note]
        
        # For fractional notes, use the existing approximation method
        # Fixed-point constants
        A4_MIDI_NOTE = FixedPoint.from_float(69.0)
        A4_FREQUENCY = FixedPoint.from_float(440.0)
        
        # Calculate note difference from A4 using fixed-point math
        note_diff = FixedPoint.from_float(float(midi_note)) - A4_MIDI_NOTE
        
        # Replace divide with multiplication by reciprocal
        octave_fraction = FixedPoint.multiply(note_diff, FixedPoint.from_float(1.0 / 12.0))
        
        # Improved fixed-point power approximation
        # Use a more accurate Taylor series approximation for 2^x
        # 2^x ≈ 1 + x * ln(2) + (x^2 * ln(2)^2 / 2!) 
        LN2 = FixedPoint.from_float(0.69314718)
        LN2_SQUARED = FixedPoint.multiply(LN2, LN2)
        
        power_approx = (
            FixedPoint.ONE + 
            FixedPoint.multiply(octave_fraction, LN2) + 
            FixedPoint.multiply(
                FixedPoint.multiply(octave_fraction, octave_fraction), 
                FixedPoint.multiply(LN2_SQUARED, FixedPoint.HALF)
            )
        )
        
        # Calculate frequency using fixed-point multiplication
        frequency = FixedPoint.multiply(A4_FREQUENCY, power_approx)
        
        return FixedPoint.to_float(frequency)
