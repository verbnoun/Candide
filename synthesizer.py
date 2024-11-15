import board
import synthio
import audiobusio
import math
import array
import audiomixer
import supervisor  # Added for ticks_ms()

class Constants:
    DEBUG = False
    # Audio Pins (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2
    I2S_DATA = board.GP0

    # Synthesizer Constants
    AUDIO_BUFFER_SIZE = 8192 #4096
    SAMPLE_RATE = 44100
    
    # Note Management Constants
    MAX_ACTIVE_NOTES = 8  # Maximum simultaneous voices
    NOTE_TIMEOUT_MS = 5000  # 5 seconds in milliseconds before force note-off

class Voice:
    def __init__(self, note, channel, velocity=1.0):
        self.note = note
        self.channel = channel
        self.velocity = velocity
        self.pressure = 0.0
        self.pitch_bend = 0.0
        self.synth_note = None  # Will hold the synthio.Note instance
        self.timestamp = supervisor.ticks_ms()  # Added timestamp field

    def refresh_timestamp(self):
        """Update the timestamp to current time"""
        self.timestamp = supervisor.ticks_ms()

class SynthEngine:
    def __init__(self):
        self.envelope_settings = {}
        self.instrument = None
        self.detune = 0
        self.filter = None
        self.waveforms = {}
        self.filter_config = {'type': 'low_pass', 'cutoff': 1000, 'resonance': 0.5}
        self.current_waveform = 'sine'
        self.pitch_bend_enabled = True
        self.pitch_bend_range = 48
        self.pitch_bend_curve = 2
        self.pressure_enabled = True
        self.pressure_sensitivity = 0.5
        self.pressure_targets = []
        self.current_pressure = 0.0

    def set_instrument(self, instrument):
        self.instrument = instrument
        self._configure_from_instrument()

    def _configure_from_instrument(self):
        if self.instrument:
            config = self.instrument.get_configuration()
            if 'envelope' in config:
                self.set_envelope(config['envelope'])
            if 'oscillator' in config:
                self.configure_oscillator(config['oscillator'])
            if 'filter' in config:
                self.set_filter(config['filter'])
            if 'pitch_bend' in config:
                self.pitch_bend_enabled = config['pitch_bend'].get('enabled', True)
                self.pitch_bend_range = config['pitch_bend'].get('range', 48)
                self.pitch_bend_curve = config['pitch_bend'].get('curve', 2)
            if 'pressure' in config:
                pressure_config = config['pressure']
                self.pressure_enabled = pressure_config.get('enabled', True)
                self.pressure_sensitivity = pressure_config.get('sensitivity', 0.5)
                self.pressure_targets = pressure_config.get('targets', [])

    def apply_pressure(self, pressure_value):
        if not self.pressure_enabled:
            return
            
        self.current_pressure = pressure_value * self.pressure_sensitivity
        
        for target in self.pressure_targets:
            param = target['param']
            min_val = target['min']
            max_val = target['max']
            curve = target.get('curve', 'linear')
            
            if curve == 'exponential':
                scaled_value = min_val + (max_val - min_val) * (self.current_pressure ** 2)
            else:  # linear
                scaled_value = min_val + (max_val - min_val) * self.current_pressure
            
            if param.startswith('envelope.'):
                param_name = param.split('.')[1]
                self.set_envelope_param(param_name, scaled_value)
            elif param.startswith('filter.'):
                param_name = param.split('.')[1]
                if param_name == 'cutoff':
                    self.set_filter_cutoff(scaled_value)
                elif param_name == 'resonance':
                    self.set_filter_resonance(scaled_value)

    def configure_oscillator(self, osc_config):
        if 'detune' in osc_config:
            self.set_detune(osc_config['detune'])
        if 'waveform' in osc_config:
            self.set_waveform(osc_config['waveform'])

    def set_filter(self, filter_config):
        self.filter_config.update(filter_config)
        self._update_filter()

    def set_filter_resonance(self, resonance):
        self.filter_config['resonance'] = resonance
        self._update_filter()

    def set_filter_cutoff(self, cutoff):
        safe_cutoff = max(20, min(20000, float(cutoff)))
        self.filter_config['cutoff'] = safe_cutoff
        self._update_filter()

    def _update_filter(self):
        if self.filter_config['type'] == 'low_pass':
            self.filter = lambda synth: synth.low_pass_filter(
                self.filter_config['cutoff'], 
                self.filter_config['resonance']
            )
        elif self.filter_config['type'] == 'high_pass':
            self.filter = lambda synth: synth.high_pass_filter(
                self.filter_config['cutoff'],
                self.filter_config['resonance']
            )
        elif self.filter_config['type'] == 'band_pass':
            self.filter = lambda synth: synth.band_pass_filter(
                self.filter_config['cutoff'],
                self.filter_config['resonance']
            )
        else:
            self.filter = None

    def set_detune(self, detune):
        self.detune = detune

    def set_envelope(self, env_config):
        self.envelope_settings.update(env_config)

    def set_envelope_param(self, param, value):
        if param in self.envelope_settings:
            self.envelope_settings[param] = value
    
    def create_envelope(self):
        return synthio.Envelope(
            attack_time=self.envelope_settings.get('attack', 0.01),
            decay_time=self.envelope_settings.get('decay', 0.1),
            release_time=self.envelope_settings.get('release', 0.1),
            attack_level=1.0,
            sustain_level=self.envelope_settings.get('sustain', 0.8)
        )

    def set_waveform(self, waveform_type):
        self.current_waveform = waveform_type
        self.generate_waveform(waveform_type)

    def generate_waveform(self, waveform_type, sample_size=256):
        if waveform_type not in self.waveforms:
            if waveform_type == 'sine':
                self.waveforms[waveform_type] = self.generate_sine_wave(sample_size)
            elif waveform_type == 'saw':
                self.waveforms[waveform_type] = self.generate_saw_wave(sample_size)
            elif waveform_type == 'square':
                self.waveforms[waveform_type] = self.generate_square_wave(sample_size)
            elif waveform_type == 'triangle':
                self.waveforms[waveform_type] = self.generate_triangle_wave(sample_size)
            else:
                self.waveforms[waveform_type] = self.generate_sine_wave(sample_size)

    def get_waveform(self, waveform_type):
        if waveform_type not in self.waveforms:
            self.generate_waveform(waveform_type)
        return self.waveforms[waveform_type]

    def generate_sine_wave(self, sample_size=256):
        return array.array("h", 
            [int(math.sin(math.pi * 2 * i / sample_size) * 32767) 
             for i in range(sample_size)])

    def generate_saw_wave(self, sample_size=256):
        return array.array("h", 
            [int((i / sample_size * 2 - 1) * 32767) 
             for i in range(sample_size)])

    def generate_square_wave(self, sample_size=256, duty_cycle=0.5):
        return array.array("h", 
            [32767 if i / sample_size < duty_cycle else -32767 
             for i in range(sample_size)])

    def generate_triangle_wave(self, sample_size=256):
        return array.array("h", 
            [int(((2 * i / sample_size - 1) if i < sample_size / 2 
                 else (2 - 2 * i / sample_size) - 1) * 32767) 
             for i in range(sample_size)])

    def update(self):
        # Any continuous updates needed for the synth engine
        pass

class SynthAudioOutputManager:
    def __init__(self):
        self.mixer = audiomixer.Mixer(
            sample_rate=Constants.SAMPLE_RATE,
            buffer_size=Constants.AUDIO_BUFFER_SIZE,
            channel_count=2
        )
        self.audio = None
        self.synth = synthio.Synthesizer(
            sample_rate=Constants.SAMPLE_RATE,
            channel_count=2
        )
        self.volume = 1.0
        self._setup_audio()

    def _setup_audio(self):
        if self.audio is not None:
            self.audio.deinit()  # Deinitialize the audio output if it was previously initialized

        self.audio = audiobusio.I2SOut(
            bit_clock=Constants.I2S_BIT_CLOCK,
            word_select=Constants.I2S_WORD_SELECT,
            data=Constants.I2S_DATA
        )
        self.audio.play(self.mixer)
        self.mixer.voice[0].play(self.synth)
        self.set_volume(self.volume)

    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, volume))
        self.mixer.voice[0].level = self.volume

    def get_volume(self):
        return self.volume

    def get_synth(self):
        return self.synth

    def stop(self):
        self.audio.stop()

class Synthesizer:
    def __init__(self, audio_output_manager):
        self.synth_engine = SynthEngine()
        self.audio_output_manager = audio_output_manager
        self.synth = self.audio_output_manager.get_synth()
        self.max_amplitude = 0.9
        self.instrument = None
        self.current_midi_values = {}
        self.active_voices = {}  # {(channel, note): Voice}

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
            self._handle_cc(0, cc_number, midi_value)  # Use channel 0 for global CCs

    def process_mpe_events(self, events):
        """Process MPE events in new format"""
        for event in events:
            event_type = event['type']
            channel = event['channel']
            data = event['data']
            
            if event_type == 'note_on':
                # Check if we're at the voice limit
                if len(self.active_voices) >= Constants.MAX_ACTIVE_NOTES:
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
        
        # Normalize velocity
        norm_velocity = velocity / 127.0
        
        # Create new voice
        voice = Voice(note, channel, norm_velocity)
        
        # Create synthio note
        frequency = self._fractional_midi_to_hz(note)
        envelope = self.synth_engine.create_envelope()
        waveform = self.synth_engine.get_waveform(self.instrument.oscillator['waveform'])
        
        synth_note = synthio.Note(
            frequency=frequency,
            envelope=envelope,
            amplitude=norm_velocity,
            waveform=waveform,
            bend=0.0,
            panning=0.0
        )
        
        if self.synth_engine.filter:
            synth_note.filter = self.synth_engine.filter(self.synth)
            
        voice.synth_note = synth_note
        self.active_voices[(channel, note)] = voice
        self.synth.press([synth_note])

    def _handle_note_off(self, channel, note):
        """Handle MPE note-off event"""
        if Constants.DEBUG:
            print(f"\nMPE Note Off - Channel: {channel}, Note: {note}")
            
        voice_key = (channel, note)
        if voice_key in self.active_voices:
            voice = self.active_voices[voice_key]
            self.synth.release([voice.synth_note])
            del self.active_voices[voice_key]

    def _handle_pressure(self, channel, pressure_value):
        """Handle per-channel pressure"""
        if not self.synth_engine.pressure_enabled:
            return
            
        if Constants.DEBUG:
            print(f"\nMPE Pressure - Channel: {channel}, Value: {pressure_value}")
            
        for (ch, note), voice in self.active_voices.items():
            if ch == channel:
                norm_pressure = pressure_value / 127.0
                voice.pressure = norm_pressure
                voice.refresh_timestamp()  # Refresh timestamp on pressure activity
                
                # Apply pressure modulation from instrument config
                self.synth_engine.apply_pressure(norm_pressure)
                
                # Update voice parameters
                voice.synth_note.envelope = self.synth_engine.create_envelope()
                if self.synth_engine.filter:
                    voice.synth_note.filter = self.synth_engine.filter(self.synth)

    def _handle_pitch_bend(self, channel, bend_value):
        """Handle per-channel pitch bend"""
        if not self.synth_engine.pitch_bend_enabled:
            return
            
        if Constants.DEBUG:
            print(f"\nMPE Pitch Bend - Channel: {channel}, Value: {bend_value}")
            
        for (ch, note), voice in self.active_voices.items():
            if ch == channel:
                # Normalize to -1.0 to 1.0 range
                norm_bend = (bend_value - 8192) / 8192.0
                # Scale by semitone range and convert to frequency ratio
                bend_range = self.synth_engine.pitch_bend_range / 12.0
                voice.pitch_bend = norm_bend
                voice.synth_note.bend = norm_bend * bend_range
                voice.refresh_timestamp()  # Refresh timestamp on pitch bend activity

    def _handle_cc(self, channel, cc_number, value):
        """Handle MIDI CC messages"""
        if Constants.DEBUG:
            print(f"\nMPE CC - Channel: {channel}, CC: {cc_number}, Value: {value}")
            
        # Normalize value
        norm_value = value / 127.0
        
        # Store for recall
        self.current_midi_values[cc_number] = value
        
        found_parameter = False

        if Constants.DEBUG:
            print(f"- Checking pot mappings for CC {cc_number}:")

        for pot_index, pot_config in self.instrument.pots.items():
            if Constants.DEBUG:
                print(f"  - Checking pot {pot_index}: CC {pot_config['cc']} ({pot_config['name']})")

            if pot_config['cc'] == cc_number:
                found_parameter = True
                param_name = pot_config['name']
                min_val = pot_config['min']
                max_val = pot_config['max']
                scaled_value = min_val + norm_value * (max_val - min_val)
                
                if Constants.DEBUG:
                    print(f"  - Found mapping! Pot {pot_index}")
                    print(f"  - Parameter: {param_name}")
                    print(f"  - Value range: {min_val} to {max_val}")
                    print(f"  - Scaled value: {scaled_value:.3f}")

                if param_name == 'Filter Cutoff':
                    if Constants.DEBUG:
                        print("  - Setting filter cutoff")
                    self.synth_engine.set_filter_cutoff(scaled_value)
                elif param_name == 'Filter Resonance':
                    if Constants.DEBUG:
                        print("  - Setting filter resonance")
                    self.synth_engine.set_filter_resonance(scaled_value)
                elif param_name == 'Detune Amount':
                    if Constants.DEBUG:
                        print("  - Setting detune")
                    self.synth_engine.set_detune(scaled_value)
                elif param_name == 'Attack Time':
                    if Constants.DEBUG:
                        print("  - Setting attack time")
                    self.synth_engine.set_envelope_param('attack', scaled_value)
                elif param_name == 'Decay Time':
                    if Constants.DEBUG:
                        print("  - Setting decay time")
                    self.synth_engine.set_envelope_param('decay', scaled_value)
                elif param_name == 'Sustain Level':
                    if Constants.DEBUG:
                        print("  - Setting sustain level")
                    self.synth_engine.set_envelope_param('sustain', scaled_value)
                elif param_name == 'Release Time':
                    if Constants.DEBUG:
                        print("  - Setting release time")
                    self.synth_engine.set_envelope_param('release', scaled_value)
                elif param_name == 'Bend Range':
                    if Constants.DEBUG:
                        print("  - Setting bend range")
                    self.synth_engine.pitch_bend_range = scaled_value
                elif param_name == 'Bend Curve':
                    if Constants.DEBUG:
                        print("  - Setting bend curve")
                    self.synth_engine.pitch_bend_curve = scaled_value
                
                if Constants.DEBUG:
                    print("  - Updating active voices")
                
                self._update_active_voices()
                break
                
        if not found_parameter and Constants.DEBUG:
            print(f"- No mapping found for CC {cc_number}")

    def _update_active_voices(self):
        """Update all active voices with current synth engine settings"""
        if not self.active_voices:
            if Constants.DEBUG:
                print("No active voices to update")
            return
        
        if Constants.DEBUG:    
            print(f"Updating {len(self.active_voices)} active voices with new parameters")

        new_envelope = self.synth_engine.create_envelope()
        for voice in self.active_voices.values():
            voice.synth_note.envelope = new_envelope
            if self.synth_engine.filter:
                voice.synth_note.filter = self.synth_engine.filter(self.synth)

    def update(self):
        """Main update loop for synth engine"""
        # Check for note timeouts
        current_time = supervisor.ticks_ms()
        for (channel, note), voice in list(self.active_voices.items()):
            if current_time - voice.timestamp >= Constants.NOTE_TIMEOUT_MS:
                if Constants.DEBUG:
                    print(f"Note timeout: Channel {channel}, Note {note}")
                self._handle_note_off(channel, note)
        
        # Update synthesis engine
        self.synth_engine.update()
        
        # Update all active voices
        for (channel, note), voice in list(self.active_voices.items()):
            # Re-apply current modulations
            if voice.pressure > 0:
                self._handle_pressure(channel, int(voice.pressure * 127))
            if voice.pitch_bend != 0:
                self._handle_pitch_bend(channel, int((voice.pitch_bend * 8192) + 8192))

    def stop(self):
        """Clean shutdown"""
        print("\nStopping synthesizer")
        if self.active_voices:
            notes = [voice.synth_note for voice in self.active_voices.values()]
            self.synth.release(notes)
            self.active_voices.clear()
        self.audio_output_manager.stop()

    def _fractional_midi_to_hz(self, midi_note):
        """Convert MIDI note number to frequency in Hz"""
        return 440 * (2 ** ((midi_note - 69) / 12))
