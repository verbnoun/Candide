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
        # Initialize voices with proper size array
        self.active_voices = [Voice() for _ in range(Constants.MAX_ACTIVE_NOTES)]

    def set_instrument(self, instrument):
        if Constants.DEBUG:
            print(f"\nSetting instrument to {instrument.name}")
            print(f"CC Mappings: {instrument.pots}")

        self.instrument = instrument
        self.synth_engine.set_instrument(instrument)
        self._configure_synthesizer()
        self._re_evaluate_midi_values()

    def _configure_synthesizer(self):
        if self.instrument:
            config = self.instrument.get_configuration()
            if Constants.DEBUG:
                print(f"Configuring synth with: {config}")

            if 'oscillator' in config:
                self.synth_engine.configure_oscillator(config['oscillator'])
            if 'filter' in config:
                self.synth_engine.set_filter(config['filter'])

    def _re_evaluate_midi_values(self):
        if Constants.DEBUG:
            print(f"Re-evaluating MIDI values: {self.current_midi_values}")
        for cc_number, midi_value in self.current_midi_values.items():
            self._handle_cc(0, cc_number, midi_value)

    def process_mpe_events(self, events):
        """Process MPE events in new format"""
        if not events:
            return
            
        for event in events:
            if not isinstance(event, dict):
                if Constants.DEBUG:
                    print(f"Invalid event format: {event}")
                continue
                
            event_type = event.get('type')
            channel = event.get('channel')
            data = event.get('data', {})
            
            if not all([event_type, channel is not None, data]):
                if Constants.DEBUG:
                    print(f"Missing required event data: {event}")
                continue

            if event_type == 'note_on':
                if all(voice.active for voice in self.active_voices):
                    if Constants.DEBUG:
                        print(f"Reached maximum voices ({Constants.MAX_ACTIVE_NOTES}), ignoring note")
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
        """Handle MPE note-on event"""
        if Constants.DEBUG:
            print(f"\nMPE Note On - Channel: {channel}, Note: {note}, Velocity: {velocity}")
        
        # Input validation
        if note is None or not isinstance(note, int):
            if Constants.DEBUG:
                print("Invalid note value")
            return
            
        # Use optimized MIDI normalization
        norm_velocity = FixedPoint.normalize_midi_value(velocity)
        
        # Find an inactive voice
        target_voice = None
        for voice in self.active_voices:
            if not voice.active:
                target_voice = voice
                break
        
        if not target_voice:
            if Constants.DEBUG:
                print("No available voices")
            return
            
        # Configure the voice
        target_voice.note = note
        target_voice.channel = channel
        target_voice.velocity = norm_velocity
        target_voice.active = True
        
        try:
            # Create synthio note
            frequency = self._fractional_midi_to_hz(note)
            envelope = self.synth_engine.create_envelope()
            waveform = self.synth_engine.get_waveform(self.instrument.oscillator['waveform'])
            
            if Constants.NOTE_TRACKER:
                print(f"[NOTE_TRACKER] Note Parameters:")
                print(f"  Frequency: {frequency:.2f}Hz")
                print(f"  Waveform: {self.instrument.oscillator['waveform']}")
                print(f"  Filter Type: {self.synth_engine.filter_config['type']}")
                print(f"  Filter Cutoff: {FixedPoint.to_float(self.synth_engine.filter_config['cutoff'])}Hz")
                print(f"  Filter Resonance: {FixedPoint.to_float(self.synth_engine.filter_config['resonance']):.3f}")
            
            synth_note = synthio.Note(
                frequency=frequency,
                envelope=envelope,
                amplitude=FixedPoint.to_float(norm_velocity),
                waveform=waveform,
                bend=0.0,
                panning=0.0
            )
            
            if self.synth_engine.filter:
                synth_note.filter = self.synth_engine.filter(self.synth)
                
            target_voice.synth_note = synth_note
            target_voice.log_envelope_update(envelope)
            self.synth.press([synth_note])
            
        except Exception as e:
            print(f"Error creating note: {str(e)}")
            target_voice.active = False

    def _handle_note_off(self, channel, note):
        """Handle MPE note-off event"""
        if Constants.DEBUG:
            print(f"\nMPE Note Off - Channel: {channel}, Note: {note}")
            
        for voice in self.active_voices:
            if voice.active and voice.channel == channel and voice.note == note:
                if voice.synth_note:
                    voice.log_release()
                    self.synth.release([voice.synth_note])
                voice.active = False
                break

    def _handle_pressure(self, channel, pressure_value):
        """Handle per-channel pressure"""
        if not self.synth_engine.pressure_enabled:
            return
            
        if Constants.DEBUG:
            print(f"\nMPE Pressure - Channel: {channel}, Value: {pressure_value}")
            
        # Use optimized MIDI normalization
        norm_pressure = FixedPoint.normalize_midi_value(pressure_value)
            
        for voice in self.active_voices:
            if voice.active and voice.channel == channel:
                voice.pressure = pressure_value  # Store raw value
                voice.refresh_timestamp()
                
                self.synth_engine.apply_pressure(FixedPoint.to_float(norm_pressure))
                
                new_envelope = self.synth_engine.create_envelope()
                voice.log_envelope_update(new_envelope)
                voice.synth_note.envelope = new_envelope
                if self.synth_engine.filter:
                    voice.synth_note.filter = self.synth_engine.filter(self.synth)

    def _handle_pitch_bend(self, channel, bend_value):
        """Handle per-channel pitch bend with safe calculations"""
        if not self.synth_engine.pitch_bend_enabled:
            return
            
        if Constants.DEBUG:
            print(f"\nMPE Pitch Bend - Channel: {channel}, Value: {bend_value}")
        
        bend_value = max(0, min(16383, bend_value))
        
        for voice in self.active_voices:
            if voice.active and voice.channel == channel:
                # Use optimized pitch bend normalization
                norm_bend = FixedPoint.normalize_pitch_bend(bend_value)
                bend_range = FixedPoint.multiply(
                    self.synth_engine.pitch_bend_range,
                    FixedPoint.from_float(1.0 / 12.0)
                )
                voice.pitch_bend = bend_value  # Store raw value
                voice.synth_note.bend = FixedPoint.to_float(
                    FixedPoint.multiply(norm_bend, bend_range)
                )
                voice.refresh_timestamp()

    def _handle_cc(self, channel, cc_number, value):
        """Handle MIDI CC messages"""
        if Constants.DEBUG:
            print(f"\nMPE CC - Channel: {channel}, CC: {cc_number}, Value: {value}")
            
        # Use optimized MIDI normalization
        norm_value = FixedPoint.normalize_midi_value(value)
        self.current_midi_values[cc_number] = value
        found_parameter = False

        if Constants.DEBUG:
            print(f"- Checking pot mappings for CC {cc_number}:")
        if Constants.NOTE_TRACKER:
            print(f"[NOTE_TRACKER] CC Update:")
            print(f"  Channel: {channel}")
            print(f"  CC: {cc_number}")
            print(f"  Value: {value}")
            print(f"  Normalized: {FixedPoint.to_float(norm_value):.3f}")

        for pot_index, pot_config in self.instrument.pots.items():
            if Constants.DEBUG:
                print(f"  - Checking pot {pot_index}: CC {pot_config['cc']} ({pot_config['name']})")

            if pot_config['cc'] == cc_number:
                found_parameter = True
                param_name = pot_config['name']
                min_val = FixedPoint.from_float(pot_config['min'])
                max_val = FixedPoint.from_float(pot_config['max'])
                range_val = max_val - min_val
                scaled_value = min_val + FixedPoint.multiply(norm_value, range_val)
                
                if Constants.DEBUG:
                    print(f"  - Found mapping! Pot {pot_index}")
                    print(f"  - Parameter: {param_name}")
                    print(f"  - Value range: {FixedPoint.to_float(min_val)} to {FixedPoint.to_float(max_val)}")
                    print(f"  - Scaled value: {FixedPoint.to_float(scaled_value):.3f}")

                self._apply_cc_parameter(param_name, scaled_value)
                self._update_active_voices()
                break
                
        if not found_parameter and Constants.DEBUG:
            print(f"- No mapping found for CC {cc_number}")

    def _apply_cc_parameter(self, param_name, scaled_value):
        """Apply CC parameter changes to the synth engine"""
        param_handlers = {
            'Filter Cutoff': lambda: self.synth_engine.set_filter_cutoff(FixedPoint.to_float(scaled_value)),
            'Filter Resonance': lambda: self.synth_engine.set_filter_resonance(FixedPoint.to_float(scaled_value)),
            'Detune Amount': lambda: self.synth_engine.set_detune(scaled_value),
            'Attack Time': lambda: self.synth_engine.set_envelope_param('attack', FixedPoint.to_float(scaled_value)),
            'Decay Time': lambda: self.synth_engine.set_envelope_param('decay', FixedPoint.to_float(scaled_value)),
            'Sustain Level': lambda: self.synth_engine.set_envelope_param('sustain', FixedPoint.to_float(scaled_value)),
            'Release Time': lambda: self.synth_engine.set_envelope_param('release', FixedPoint.to_float(scaled_value)),
            'Bend Range': lambda: setattr(self.synth_engine, 'pitch_bend_range', scaled_value),
            'Bend Curve': lambda: setattr(self.synth_engine, 'pitch_bend_curve', scaled_value)
        }
        
        if param_name in param_handlers:
            if Constants.DEBUG:
                print(f"  - Setting {param_name}")
            param_handlers[param_name]()

    def _update_active_voices(self):
        """Update all active voices with current synth engine settings"""
        if not any(voice.active for voice in self.active_voices):
            if Constants.DEBUG:
                print("No active voices to update")
            return
        
        if Constants.DEBUG:    
            print(f"Updating active voices with new parameters")

        try:
            new_envelope = self.synth_engine.create_envelope()
            for voice in self.active_voices:
                if voice.active and voice.synth_note:
                    voice.log_envelope_update(new_envelope)
                    voice.synth_note.envelope = new_envelope
                    if self.synth_engine.filter:
                        voice.synth_note.filter = self.synth_engine.filter(self.synth)
        except Exception as e:
            print(f"Error updating voices: {str(e)}")

    def update(self):
        """Main update loop for synth engine"""
        current_time = supervisor.ticks_ms()
        
        # Handle timeouts and voice updates
        try:
            for voice in self.active_voices:
                if voice.active:
                    # Check for timeout
                    if current_time - voice.timestamp >= Constants.NOTE_TIMEOUT_MS:
                        if Constants.DEBUG:
                            print(f"Note timeout: Channel {voice.channel}, Note {voice.note}")
                        if Constants.NOTE_TRACKER:
                            print(f"[NOTE_TRACKER] Note Timeout:")
                            print(f"  Channel: {voice.channel}")
                            print(f"  Note: {voice.note}")
                            print(f"  Duration: {Constants.NOTE_TIMEOUT_MS}ms")
                        self._handle_note_off(voice.channel, voice.note)
                    
                    # Track release progression and handle modulations
                    voice.log_release_progression(self.synth)
                    
                    if voice.pressure > 0:
                        self._handle_pressure(voice.channel, voice.pressure)
                    if voice.pitch_bend != 0:
                        self._handle_pitch_bend(voice.channel, voice.pitch_bend)
            
            self.synth_engine.update()
            
        except Exception as e:
            print(f"Error in synth update: {str(e)}")

    def stop(self):
        """Clean shutdown"""
        print("\nStopping synthesizer")
        if Constants.NOTE_TRACKER:
            print("[NOTE_TRACKER] Synthesizer stopping")
            print(f"  Active voices being released: {sum(voice.active for voice in self.active_voices)}")
            
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
            print(f"Error during shutdown: {str(e)}")

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
