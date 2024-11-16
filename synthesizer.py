import board
import synthio
import audiobusio
import math
import array
import audiomixer
import supervisor  # Added for ticks_ms()

class FixedPoint:
    SCALE = 1 << 16  # 16-bit fractional part
    MAX_VALUE = (1 << 31) - 1
    MIN_VALUE = -(1 << 31)
    
    @staticmethod
    def from_float(value):
        """Convert float to fixed-point integer with safe bounds"""
        try:
            # Clamp value to prevent overflow
            value = max(min(value, 32767.0), -32768.0)
            return int(value * FixedPoint.SCALE)
        except (TypeError, OverflowError):
            return 0
        
    @staticmethod
    def to_float(fixed):
        """Convert fixed-point integer to float with safe handling"""
        try:
            if isinstance(fixed, (int, float)):
                return float(fixed) / float(FixedPoint.SCALE)
            return 0.0
        except (TypeError, OverflowError):
            return 0.0
        
    @staticmethod
    def multiply(a, b):
        """Multiply two fixed-point numbers"""
        if not isinstance(a, int):
            a = FixedPoint.from_float(float(a))
        if not isinstance(b, int):
            b = FixedPoint.from_float(float(b))
        return (a * b) >> 16

class Constants:
    DEBUG = False
    NOTE_TRACKER = False  # Added for note lifecycle tracking
    # Audio Pins (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2
    I2S_DATA = board.GP0

    # Synthesizer Constants
    AUDIO_BUFFER_SIZE = 8192 #4096
    SAMPLE_RATE = 44100
    
    # Note Management Constants
    MAX_ACTIVE_NOTES = 8  # Maximum simultaneous voices
    NOTE_TIMEOUT_MS = 2000  # 5 seconds in milliseconds before force note-off
    
    # MPE Significance Constants
    BASE_THRESHOLD = FixedPoint.from_float(0.05)  # Base threshold for significant changes (5%)
    MAX_THRESHOLD = FixedPoint.from_float(0.20)   # Maximum threshold cap (20%)
    THRESHOLD_SCALE = FixedPoint.from_float(1.5)  # Exponential scaling factor for threshold

class Voice:
    def __init__(self, note=None, channel=None, velocity=1.0):
        self.note = note
        self.channel = channel
        self.velocity = FixedPoint.from_float(velocity)
        self.pressure = FixedPoint.from_float(0.0)
        self.pitch_bend = FixedPoint.from_float(0.0)
        self.synth_note = None  # Will hold the synthio.Note instance
        self.timestamp = supervisor.ticks_ms()  # Added timestamp field
        self.release_tracking = False  # Flag to track release state
        self.active = False  # Flag to track if voice is active in fixed array
        if Constants.NOTE_TRACKER and note is not None:
            print(f"[NOTE_TRACKER] Voice Created:")
            print(f"  Channel: {channel}")
            print(f"  Note: {note}")
            print(f"  Velocity: {FixedPoint.to_float(self.velocity):.3f}")
            print(f"  Time: {self.timestamp}ms")

    def is_significant_change(self, current_value, new_value, active_voice_count):
        """Determine if a parameter change is significant enough to process"""
        # Calculate dynamic threshold based on active voices
        threshold = min(
            FixedPoint.multiply(Constants.BASE_THRESHOLD, 
                              FixedPoint.from_float(Constants.THRESHOLD_SCALE ** (active_voice_count - 1))),
            Constants.MAX_THRESHOLD
        )
        
        # Calculate relative change
        if current_value == 0:
            return abs(new_value) > threshold
        
        relative_change = abs(FixedPoint.multiply(
            FixedPoint.from_float((new_value - current_value)), 
            FixedPoint.from_float(1.0 / current_value)
        ))
        return relative_change > threshold

    def log_release_progression(self, synth):
        """Track and log note release progression"""
        if not Constants.NOTE_TRACKER or not self.synth_note:
            return

        # Get note info from synthesizer
        note_state = synth.note_info(self.synth_note)
        
        if note_state[0] is not None:
            if not self.release_tracking:
                print(f"[NOTE_TRACKER] Release Started:")
                print(f"  Channel: {self.channel}")
                print(f"  Note: {self.note}")
                self.release_tracking = True

            # Print detailed release information
            print(f"[NOTE_TRACKER] Release Progression:")
            print(f"  State: {note_state[0]}")
            print(f"  Envelope Value: {FixedPoint.to_float(note_state[1]):.4f}")
        elif self.release_tracking:
            print(f"[NOTE_TRACKER] Release Completed:")
            print(f"  Channel: {self.channel}")
            print(f"  Note: {self.note}")
            self.release_tracking = False

    def refresh_timestamp(self):
        """Update the timestamp to current time"""
        old_timestamp = self.timestamp
        self.timestamp = supervisor.ticks_ms()
        if Constants.NOTE_TRACKER:
            print(f"[NOTE_TRACKER] Voice Activity:")
            print(f"  Channel: {self.channel}")
            print(f"  Note: {self.note}")
            print(f"  Pressure: {FixedPoint.to_float(self.pressure):.3f}")
            print(f"  Pitch Bend: {FixedPoint.to_float(self.pitch_bend):.3f}")
            print(f"  Time: {self.timestamp}ms")

    def log_envelope_update(self, envelope):
        """Log envelope parameter changes"""
        if Constants.NOTE_TRACKER:
            print(f"[NOTE_TRACKER] Envelope Update:")
            print(f"  Channel: {self.channel}")
            print(f"  Note: {self.note}")
            print(f"  Attack: {FixedPoint.to_float(envelope.attack_time):.3f}s")
            print(f"  Decay: {FixedPoint.to_float(envelope.decay_time):.3f}s")
            print(f"  Sustain: {FixedPoint.to_float(envelope.sustain_level):.3f}")
            print(f"  Release: {FixedPoint.to_float(envelope.release_time):.3f}s")

    def log_release(self):
        """Log note release"""
        if Constants.NOTE_TRACKER:
            print(f"[NOTE_TRACKER] Voice Released:")
            print(f"  Channel: {self.channel}")
            print(f"  Note: {self.note}")
            print(f"  Final Pressure: {FixedPoint.to_float(self.pressure):.3f}")
            print(f"  Final Pitch Bend: {FixedPoint.to_float(self.pitch_bend):.3f}")
            print(f"  Total Duration: {supervisor.ticks_ms() - self.timestamp}ms")

class SynthEngine:
    def __init__(self):
        self.envelope_settings = {}
        self.instrument = None
        self.detune = FixedPoint.from_float(0)
        self.filter = None
        self.waveforms = {}
        self.filter_config = {
            'type': 'low_pass', 
            'cutoff': FixedPoint.from_float(1000), 
            'resonance': FixedPoint.from_float(0.5)
        }
        self.current_waveform = 'sine'
        self.pitch_bend_enabled = True
        self.pitch_bend_range = FixedPoint.from_float(48)
        self.pitch_bend_curve = FixedPoint.from_float(2)
        self.pressure_enabled = True
        self.pressure_sensitivity = FixedPoint.from_float(0.5)
        self.pressure_targets = []
        self.current_pressure = FixedPoint.from_float(0.0)

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
                self.pitch_bend_range = FixedPoint.from_float(config['pitch_bend'].get('range', 48))
                self.pitch_bend_curve = FixedPoint.from_float(config['pitch_bend'].get('curve', 2))
            if 'pressure' in config:
                pressure_config = config['pressure']
                self.pressure_enabled = pressure_config.get('enabled', True)
                self.pressure_sensitivity = FixedPoint.from_float(pressure_config.get('sensitivity', 0.5))
                self.pressure_targets = pressure_config.get('targets', [])

    def apply_pressure(self, pressure_value):
        if not self.pressure_enabled:
            return
            
        # Safely clamp pressure value
        pressure_value = max(0.0, min(1.0, pressure_value))
        
        self.current_pressure = FixedPoint.multiply(pressure_value, self.pressure_sensitivity)
        
        for target in self.pressure_targets:
            param = target['param']
            min_val = FixedPoint.from_float(target.get('min', 0.0))
            max_val = FixedPoint.from_float(target.get('max', 1.0))
            curve = target.get('curve', 'linear')
            
            if curve == 'exponential':
                pressure_squared = FixedPoint.multiply(self.current_pressure, self.current_pressure)
                range_val = max_val - min_val
                scaled_value = min_val + FixedPoint.multiply(range_val, pressure_squared)
            else:  # linear
                range_val = max_val - min_val
                scaled_value = min_val + FixedPoint.multiply(range_val, self.current_pressure)
            
            if param.startswith('envelope.'):
                param_name = param.split('.')[1]
                self.set_envelope_param(param_name, FixedPoint.to_float(scaled_value))
            elif param.startswith('filter.'):
                param_name = param.split('.')[1]
                if param_name == 'cutoff':
                    self.set_filter_cutoff(FixedPoint.to_float(scaled_value))
                elif param_name == 'resonance':
                    self.set_filter_resonance(FixedPoint.to_float(scaled_value))

    def configure_oscillator(self, osc_config):
        if 'detune' in osc_config:
            self.set_detune(osc_config['detune'])
        if 'waveform' in osc_config:
            self.set_waveform(osc_config['waveform'])

    def set_filter(self, filter_config):
        self.filter_config.update({
            'type': filter_config['type'],
            'cutoff': FixedPoint.from_float(filter_config['cutoff']),
            'resonance': FixedPoint.from_float(filter_config['resonance'])
        })
        self._update_filter()

    def set_filter_resonance(self, resonance):
        self.filter_config['resonance'] = FixedPoint.from_float(resonance)
        self._update_filter()

    def set_filter_cutoff(self, cutoff):
        safe_cutoff = max(20, min(20000, float(cutoff)))
        self.filter_config['cutoff'] = FixedPoint.from_float(safe_cutoff)
        self._update_filter()

    def _update_filter(self):
        if self.filter_config['type'] == 'low_pass':
            self.filter = lambda synth: synth.low_pass_filter(
                FixedPoint.to_float(self.filter_config['cutoff']), 
                FixedPoint.to_float(self.filter_config['resonance'])
            )
        elif self.filter_config['type'] == 'high_pass':
            self.filter = lambda synth: synth.high_pass_filter(
                FixedPoint.to_float(self.filter_config['cutoff']),
                FixedPoint.to_float(self.filter_config['resonance'])
            )
        elif self.filter_config['type'] == 'band_pass':
            self.filter = lambda synth: synth.band_pass_filter(
                FixedPoint.to_float(self.filter_config['cutoff']),
                FixedPoint.to_float(self.filter_config['resonance'])
            )
        else:
            self.filter = None

    def set_detune(self, detune):
        self.detune = FixedPoint.from_float(detune)

    def set_envelope(self, env_config):
        self.envelope_settings.update({
            k: FixedPoint.from_float(v) for k, v in env_config.items()
        })

    def set_envelope_param(self, param, value):
        if param in self.envelope_settings:
            self.envelope_settings[param] = FixedPoint.from_float(value)
    
    def create_envelope(self):
        return synthio.Envelope(
            attack_time=FixedPoint.to_float(self.envelope_settings.get('attack', FixedPoint.from_float(0.01))),
            decay_time=FixedPoint.to_float(self.envelope_settings.get('decay', FixedPoint.from_float(0.1))),
            release_time=FixedPoint.to_float(self.envelope_settings.get('release', FixedPoint.from_float(0.1))),
            attack_level=1.0,
            sustain_level=FixedPoint.to_float(self.envelope_settings.get('sustain', FixedPoint.from_float(0.8)))
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
            [int(FixedPoint.to_float(FixedPoint.multiply(
                FixedPoint.from_float(math.sin(math.pi * 2 * i / sample_size)),
                FixedPoint.from_float(32767)
            ))) for i in range(sample_size)])

    def generate_saw_wave(self, sample_size=256):
        return array.array("h", 
            [int(FixedPoint.to_float(FixedPoint.multiply(
                FixedPoint.from_float(i / sample_size * 2 - 1),
                FixedPoint.from_float(32767)
            ))) for i in range(sample_size)])

    def generate_square_wave(self, sample_size=256, duty_cycle=0.5):
        duty = FixedPoint.from_float(duty_cycle)
        return array.array("h", 
            [32767 if FixedPoint.from_float(i / sample_size) < duty else -32767 
             for i in range(sample_size)])

    def generate_triangle_wave(self, sample_size=256):
        return array.array("h", 
            [int(FixedPoint.to_float(FixedPoint.multiply(
                FixedPoint.from_float(
                    (2 * i / sample_size - 1) if i < sample_size / 2 
                    else (2 - 2 * i / sample_size) - 1
                ),
                FixedPoint.from_float(32767)
            ))) for i in range(sample_size)])

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
        self.volume = FixedPoint.from_float(1.0)
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
        self.set_volume(FixedPoint.to_float(self.volume))

    def set_volume(self, volume):
        self.volume = FixedPoint.from_float(max(0.0, min(1.0, volume)))
        self.mixer.voice[0].level = FixedPoint.to_float(self.volume)

    def get_volume(self):
        return FixedPoint.to_float(self.volume)

    def get_synth(self):
        return self.synth

    def stop(self):
        self.audio.stop()

class Synthesizer:
    def __init__(self, audio_output_manager):
        self.synth_engine = SynthEngine()
        self.audio_output_manager = audio_output_manager
        self.synth = self.audio_output_manager.get_synth()
        self.max_amplitude = FixedPoint.from_float(0.9)
        self.instrument = None
        self.current_midi_values = {}
        self.active_voices = [Voice() for _ in range(Constants.MAX_ACTIVE_NOTES)]  # Fixed-size array of Voice objects

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
        
        # Normalize velocity
        norm_velocity = FixedPoint.from_float(velocity / 127.0)
        
        # Find an inactive voice
        for voice in self.active_voices:
            if not voice.active:
                voice.note = note
                voice.channel = channel
                voice.velocity = norm_velocity
                voice.active = True
                break
        
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
            
        voice.synth_note = synth_note
        voice.log_envelope_update(envelope)  # Log initial envelope values
        self.synth.press([synth_note])

    def _handle_note_off(self, channel, note):
        """Handle MPE note-off event"""
        if Constants.DEBUG:
            print(f"\nMPE Note Off - Channel: {channel}, Note: {note}")
            
        for voice in self.active_voices:
            if voice.active and voice.channel == channel and voice.note == note:
                voice.log_release()  # Log final state before release
                self.synth.release([voice.synth_note])
                voice.active = False
                break

    def _handle_pressure(self, channel, pressure_value):
        """Handle per-channel pressure"""
        if not self.synth_engine.pressure_enabled:
            return
            
        if Constants.DEBUG:
            print(f"\nMPE Pressure - Channel: {channel}, Value: {pressure_value}")
            
        for voice in self.active_voices:
            if voice.active and voice.channel == channel:
                norm_pressure = FixedPoint.from_float(pressure_value / 127.0)
                voice.pressure = norm_pressure
                voice.refresh_timestamp()  # This will log pressure changes
                
                # Apply pressure modulation from instrument config
                self.synth_engine.apply_pressure(FixedPoint.to_float(norm_pressure))
                
                # Update voice parameters
                new_envelope = self.synth_engine.create_envelope()
                voice.log_envelope_update(new_envelope)  # Log envelope changes
                voice.synth_note.envelope = new_envelope
                if self.synth_engine.filter:
                    voice.synth_note.filter = self.synth_engine.filter(self.synth)

    def _handle_pitch_bend(self, channel, bend_value):
        """Handle per-channel pitch bend with safe calculations"""
        if not self.synth_engine.pitch_bend_enabled:
            return
            
        if Constants.DEBUG:
            print(f"\nMPE Pitch Bend - Channel: {channel}, Value: {bend_value}")
        
        # Safely normalize bend value
        bend_value = max(0, min(16383, bend_value))
        
        for voice in self.active_voices:
            if voice.active and voice.channel == channel:
                # Normalize to -1.0 to 1.0 range
                norm_bend = FixedPoint.from_float((bend_value - 8192) / 8192.0)
                # Scale by semitone range and convert to frequency ratio
                bend_range = FixedPoint.multiply(
                    self.synth_engine.pitch_bend_range,
                    FixedPoint.from_float(1.0 / 12.0)
                )
                voice.pitch_bend = norm_bend
                voice.synth_note.bend = FixedPoint.to_float(
                    FixedPoint.multiply(norm_bend, bend_range)
                )
                voice.refresh_timestamp()  # This will log pitch bend changes

    def _handle_cc(self, channel, cc_number, value):
        """Handle MIDI CC messages"""
        if Constants.DEBUG:
            print(f"\nMPE CC - Channel: {channel}, CC: {cc_number}, Value: {value}")
            
        # Normalize value
        norm_value = FixedPoint.from_float(value / 127.0)
        
        # Store for recall
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

                if param_name == 'Filter Cutoff':
                    if Constants.DEBUG:
                        print("  - Setting filter cutoff")
                    self.synth_engine.set_filter_cutoff(FixedPoint.to_float(scaled_value))
                elif param_name == 'Filter Resonance':
                    if Constants.DEBUG:
                        print("  - Setting filter resonance")
                    self.synth_engine.set_filter_resonance(FixedPoint.to_float(scaled_value))
                elif param_name == 'Detune Amount':
                    if Constants.DEBUG:
                        print("  - Setting detune")
                    self.synth_engine.set_detune(scaled_value)
                elif param_name == 'Attack Time':
                    if Constants.DEBUG:
                        print("  - Setting attack time")
                    self.synth_engine.set_envelope_param('attack', FixedPoint.to_float(scaled_value))
                elif param_name == 'Decay Time':
                    if Constants.DEBUG:
                        print("  - Setting decay time")
                    self.synth_engine.set_envelope_param('decay', FixedPoint.to_float(scaled_value))
                elif param_name == 'Sustain Level':
                    if Constants.DEBUG:
                        print("  - Setting sustain level")
                    self.synth_engine.set_envelope_param('sustain', FixedPoint.to_float(scaled_value))
                elif param_name == 'Release Time':
                    if Constants.DEBUG:
                        print("  - Setting release time")
                    self.synth_engine.set_envelope_param('release', FixedPoint.to_float(scaled_value))
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
        if not any(voice.active for voice in self.active_voices):
            if Constants.DEBUG:
                print("No active voices to update")
            return
        
        if Constants.DEBUG:    
            print(f"Updating active voices with new parameters")

        new_envelope = self.synth_engine.create_envelope()
        for voice in self.active_voices:
            if voice.active:
                voice.log_envelope_update(new_envelope)  # Log envelope changes
                voice.synth_note.envelope = new_envelope
                if self.synth_engine.filter:
                    voice.synth_note.filter = self.synth_engine.filter(self.synth)

    def update(self):
        """Main update loop for synth engine"""
        # Check for note timeouts
        current_time = supervisor.ticks_ms()
        for voice in self.active_voices:
            if voice.active and current_time - voice.timestamp >= Constants.NOTE_TIMEOUT_MS:
                if Constants.DEBUG:
                    print(f"Note timeout: Channel {voice.channel}, Note {voice.note}")
                if Constants.NOTE_TRACKER:
                    print(f"[NOTE_TRACKER] Note Timeout:")
                    print(f"  Channel: {voice.channel}")
                    print(f"  Note: {voice.note}")
                    print(f"  Duration: {Constants.NOTE_TIMEOUT_MS}ms")
                self._handle_note_off(voice.channel, voice.note)
        
        # Update synthesis engine
        self.synth_engine.update()
        
        # Track release progression for active voices
        for voice in self.active_voices:
            if voice.active:
                # Track release progression
                voice.log_release_progression(self.synth)
                
                # Re-apply current modulations
                if voice.pressure > 0:
                    self._handle_pressure(voice.channel, int(voice.pressure * 127))
                if voice.pitch_bend != 0:
                    self._handle_pitch_bend(voice.channel, int((voice.pitch_bend * 8192) + 8192))

    def stop(self):
        """Clean shutdown"""
        print("\nStopping synthesizer")
        if Constants.NOTE_TRACKER:
            print("[NOTE_TRACKER] Synthesizer stopping")
            print(f"  Active voices being released: {sum(voice.active for voice in self.active_voices)}")
        if any(voice.active for voice in self.active_voices):
            notes = [voice.synth_note for voice in self.active_voices if voice.active]
            self.synth.release(notes)
            for voice in self.active_voices:
                voice.active = False
        self.audio_output_manager.stop()

    def _fractional_midi_to_hz(self, midi_note):
        """Convert MIDI note number to frequency in Hz"""
        return 440 * (2 ** ((midi_note - 69) / 12))
