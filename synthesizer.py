import synthio
from synthesis_modules import (
    FixedPoint, Constants, Voice, SynthEngine, 
    SynthAudioOutputManager
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
        
        # New tracking dictionary for parameter states
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
        
        # Initialize voices with proper size array
        self.active_voices = [Voice() for _ in range(Constants.MAX_ACTIVE_NOTES)]

    def prepare_note_parameters(self, channel, velocity):
        """Handle MPE note setup sequence before note-on"""
        # Find an available voice
        target_voice = None
        for voice in self.active_voices:
            if not voice.active:
                target_voice = voice
                break
                
        if not target_voice:
            return None
            
        # Initialize the voice with channel and velocity
        target_voice.channel = channel
        target_voice.velocity = FixedPoint.normalize_midi_value(velocity)
        
        # Set initial pitch bend for the channel (from current_midi_values if exists)
        initial_bend = self.current_midi_values.get(f'pitch_bend_{channel}', 8192)
        
        # Set initial CC #74 timbre value
        initial_timbre = self.current_midi_values.get(f'cc74_{channel}', 0)
        
        # Set initial channel pressure - now getting from current_midi_values
        initial_pressure = self.current_midi_values.get(f'pressure_{channel}', 0)
        
        # Get current envelope settings for initial state
        initial_envelope = self.synth_engine.envelope_settings.copy()
        
        # Store all initial parameters in the voice
        target_voice.store_initial_parameters(
            pitch_bend=initial_bend,
            timbre=initial_timbre,
            pressure=initial_pressure,
            envelope=initial_envelope
        )
        
        return target_voice

    def _is_parameter_changed(self, param_name, new_value, tolerance=0.001):
        """
        Check if a parameter value has changed significantly.
        
        Args:
            param_name (str): Name of the parameter to check
            new_value (float): New parameter value
            tolerance (float): Acceptable variation threshold
        
        Returns:
            bool: True if parameter has changed, False otherwise
        """
        last_value = self.last_parameter_values.get(param_name)
        
        # First time setting the parameter
        if last_value is None:
            self.last_parameter_values[param_name] = new_value
            return True
        
        # Check if change is significant
        is_changed = abs(last_value - new_value) > tolerance
        
        if is_changed:
            self.last_parameter_values[param_name] = new_value
        
        return is_changed

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

    def process_mpe_events(self, events):
        """Process MPE events in new format"""
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
        
        # Input validation
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
                bend=0.0,  # Start with no bend, will be updated relative to initial
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

    def _handle_pressure(self, channel, pressure_value):
        """Handle per-channel pressure with significance thresholds"""
            
        if not self.synth_engine.pressure_enabled:
            return
            
        # Count active voices
        active_voice_count = sum(1 for voice in self.active_voices if voice.active)
        
        # Use optimized MIDI normalization
        norm_pressure = FixedPoint.normalize_midi_value(pressure_value)
            
        for voice in self.active_voices:
            if voice.active and voice.channel == channel:
                # Get pressure relative to initial value
                relative_pressure = voice.get_relative_pressure(pressure_value)
                
                # Check if pressure change is significant
                if voice.is_significant_change(voice.pressure, relative_pressure, active_voice_count):
                    voice.pressure = relative_pressure  # Store relative value
                    voice.refresh_timestamp()
                    
                    # Apply pressure modulation respecting initial envelope
                    self.synth_engine.apply_pressure(
                        FixedPoint.to_float(norm_pressure), 
                        initial_envelope=voice.initial_parameters['envelope']
                    )
                    
                    new_envelope = self.synth_engine.create_envelope()
                    voice.synth_note.envelope = new_envelope
                    if self.synth_engine.filter:
                        voice.synth_note.filter = self.synth_engine.filter(self.synth)

    def _handle_pitch_bend(self, channel, bend_value):
        """Handle per-channel pitch bend with significance thresholds"""
        if not self.synth_engine.pitch_bend_enabled:
            return
        
        # Store current pitch bend value for future note-ons
        self.current_midi_values[f'pitch_bend_{channel}'] = bend_value
        
        # Clamp bend value to valid range
        bend_value = max(0, min(16383, bend_value))
        
        # Count active voices
        active_voice_count = sum(1 for voice in self.active_voices if voice.active)
        
        for voice in self.active_voices:
            if voice.active and voice.channel == channel:
                # Get bend relative to initial value
                relative_bend = voice.get_relative_pitch_bend(bend_value)
                
                # Check if pitch bend change is significant
                if voice.is_significant_change(voice.pitch_bend, relative_bend, active_voice_count):
                    # Use optimized pitch bend normalization
                    norm_bend = FixedPoint.normalize_pitch_bend(relative_bend)
                    bend_range = FixedPoint.multiply(
                        self.synth_engine.pitch_bend_range,
                        FixedPoint.from_float(1.0 / 12.0)
                    )
                    voice.pitch_bend = relative_bend  # Store relative value
                    voice.synth_note.bend = FixedPoint.to_float(
                        FixedPoint.multiply(norm_bend, bend_range)
                    )
                    voice.refresh_timestamp()

    def _handle_cc(self, channel, cc_number, value):
        """Optimized CC handling with parameter change tracking"""
            
        # Use optimized MIDI normalization
        norm_value = FixedPoint.normalize_midi_value(value)
        self.current_midi_values[cc_number] = value
        found_parameter = False

        for pot_index, pot_config in self.instrument.pots.items():
            if pot_config['cc'] == cc_number:
                found_parameter = True
                param_name = pot_config['name']
                min_val = FixedPoint.from_float(pot_config['min'])
                max_val = FixedPoint.from_float(pot_config['max'])
                range_val = max_val - min_val
                scaled_value = min_val + FixedPoint.multiply(norm_value, range_val)

                # Only update if parameter actually changes
                if self._apply_cc_parameter(param_name, scaled_value):
                    self._update_active_voices()
                break

    def _apply_cc_parameter(self, param_name, scaled_value):
        """Apply CC parameter changes to the synth engine with change tracking"""
        param_handlers = {
            'Filter Cutoff': (
                lambda: self.synth_engine.set_filter_cutoff(FixedPoint.to_float(scaled_value)),
                'filter_cutoff'
            ),
            'Filter Resonance': (
                lambda: self.synth_engine.set_filter_resonance(FixedPoint.to_float(scaled_value)),
                'filter_resonance'
            ),
            'Detune Amount': (
                lambda: self.synth_engine.set_detune(scaled_value),
                'detune_amount'
            ),
            'Attack Time': (
                lambda: self.synth_engine.set_envelope_param('attack', FixedPoint.to_float(scaled_value)),
                'attack_time'
            ),
            'Decay Time': (
                lambda: self.synth_engine.set_envelope_param('decay', FixedPoint.to_float(scaled_value)),
                'decay_time'
            ),
            'Sustain Level': (
                lambda: self.synth_engine.set_envelope_param('sustain', FixedPoint.to_float(scaled_value)),
                'sustain_level'
            ),
            'Release Time': (
                lambda: self.synth_engine.set_envelope_param('release', FixedPoint.to_float(scaled_value)),
                'release_time'
            ),
            'Bend Range': (
                lambda: setattr(self.synth_engine, 'pitch_bend_range', scaled_value),
                'bend_range'
            ),
            'Bend Curve': (
                lambda: setattr(self.synth_engine, 'pitch_bend_curve', scaled_value),
                'bend_curve'
            )
        }
        
        if param_name in param_handlers:
            handler, tracking_key = param_handlers[param_name]
            new_value = FixedPoint.to_float(scaled_value)
            
            # Only apply and update voices if parameter has changed
            if self._is_parameter_changed(tracking_key, new_value):
                handler()
                return True
        
        return False

    def _update_active_voices(self):
        """Optimized update for active voices with change tracking"""
        if not any(voice.active for voice in self.active_voices):
            return

        try:
            new_envelope = self.synth_engine.create_envelope()
            for voice in self.active_voices:
                if voice.active and voice.synth_note:
                    voice.synth_note.envelope = new_envelope
                    if self.synth_engine.filter:
                        voice.synth_note.filter = self.synth_engine.filter(self.synth)
        except Exception as e:
            pass

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
