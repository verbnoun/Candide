import board
import synthio
import audiobusio
import math
import array
import audiomixer

class Constants:
    # Audio Pins (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2
    I2S_DATA = board.GP0

    # Synthesizer Constants
    AUDIO_BUFFER_SIZE = 4096
    SAMPLE_RATE = 44100
    
    # MPE Constants
    MPE_MASTER_CHANNEL = 0  # MIDI channel 1 (zero-based)
    MPE_ZONE_START = 1      # MIDI channel 2 (zero-based)
    MPE_ZONE_END = 11      # MIDI channel 12 (zero-based)
    MPE_MAX_VOICES = 12    # Maximum number of MPE voices
    
    # MIDI CC Numbers
    CC_CHANNEL_PRESSURE = 74
    CC_LEFT_PRESSURE = 78
    CC_RIGHT_PRESSURE = 79

class SynthVoiceManager:
    def __init__(self):
        self.active_notes = {}  # Maps key_id to Note objects
        self.note_channels = {}  # Maps key_id to MPE channel
        self.available_channels = list(range(
            Constants.MPE_ZONE_START,
            Constants.MPE_ZONE_END + 1
        ))

    def allocate_channel(self, key_id):
        """Allocate an MPE channel for a new note"""
        if key_id in self.note_channels:
            return self.note_channels[key_id]
            
        if self.available_channels:
            channel = self.available_channels.pop(0)
            self.note_channels[key_id] = channel
            return channel
            
        # If no channels available, steal oldest one
        if self.note_channels:
            oldest_key = min(self.note_channels.keys())
            channel = self.note_channels[oldest_key]
            del self.note_channels[oldest_key]
            self.note_channels[key_id] = channel
            return channel
            
        return Constants.MPE_ZONE_START  # Fallback

    def allocate_voice(self, key_id, frequency, velocity, envelope, waveform):
        """Allocate or update a voice for the given key"""
        if key_id in self.active_notes:
            note = self.active_notes[key_id]
            note.frequency = frequency
            note.amplitude = velocity / 127.0
            note.envelope = envelope
            note.waveform = waveform
        else:
            channel = self.allocate_channel(key_id)
            note = synthio.Note(
                frequency=frequency,
                envelope=envelope,
                amplitude=velocity / 127.0,
                waveform=waveform,
                bend=0.0,  # Initialize with no pitch bend
                panning=0.0  # Initialize centered
            )
            self.active_notes[key_id] = note
            
        return note

    def change_note_waveform(self, key_id, new_waveform):
        if key_id in self.active_notes:
            self.active_notes[key_id].waveform = new_waveform

    def release_voice(self, key_id):
        """Release a voice and its channel"""
        if key_id in self.active_notes:
            note = self.active_notes.pop(key_id)
            if key_id in self.note_channels:
                channel = self.note_channels[key_id]
                if channel not in self.available_channels:
                    self.available_channels.append(channel)
                del self.note_channels[key_id]
            return note
        return None

    def get_note_by_key_id(self, key_id):
        return self.active_notes.get(key_id)

    def get_channel_by_key_id(self, key_id):
        return self.note_channels.get(key_id)

    def update_all_envelopes(self, new_envelope):
        for note in self.active_notes.values():
            note.envelope = new_envelope

    def release_all_voices(self):
        self.active_notes.clear()
        self.note_channels.clear()
        self.available_channels = list(range(
            Constants.MPE_ZONE_START,
            Constants.MPE_ZONE_END + 1
        ))

    def get_active_note_count(self):
        return len(self.active_notes)
    
    def get_active_notes(self):
        return list(self.active_notes.values())

class SynthEngine:
    def __init__(self):
        self.lfos = []
        self.modulation_matrix = {}
        self.effects = []
        self.envelope_settings = {}
        self.instrument = None
        self.detune = 0
        self.filter = None
        self.waveforms = {}
        self.filter_config = {'type': 'low_pass', 'cutoff': 1000, 'resonance': 0.5}
        self.current_waveform = 'sine'
        self.pitch_bend_enabled = True  # Default to enabled for MPE
        self.pitch_bend_range = 48  # Default MPE pitch bend range (4 octaves)
        self.pitch_bend_curve = 2
        self.pressure_enabled = True  # Enable pressure for MPE
        self.pressure_sensitivity = 0.5
        self.pressure_targets = []  # List of parameters affected by pressure
        self.current_pressure = 0.0  # Current pressure value

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

    def apply_pressure(self, pressure_value, key_id=None):
        """Apply pressure to all configured targets"""
        if not self.pressure_enabled:
            return
            
        # Scale pressure by sensitivity
        self.current_pressure = pressure_value * self.pressure_sensitivity
        
        # Apply pressure to each configured target
        for target in self.pressure_targets:
            param = target['param']
            min_val = target['min']
            max_val = target['max']
            curve = target.get('curve', 'linear')
            
            # Apply curve if specified
            if curve == 'exponential':
                scaled_value = min_val + (max_val - min_val) * (self.current_pressure ** 2)
            else:  # linear
                scaled_value = min_val + (max_val - min_val) * self.current_pressure
            
            # Update the parameter based on target type
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

    def create_lfo(self, rate, scale=1.0, offset=0.0, waveform=None):
        lfo = synthio.LFO(rate=rate, scale=scale, offset=offset, waveform=waveform)
        self.lfos.append(lfo)
        return lfo

    def update(self, synth):
        self.update_modulation()
        self.process_effects(synth)

    def update_modulation(self):
        for target, modulations in self.modulation_matrix.items():
            total_modulation = 0
            for source, amount in modulations:
                if isinstance(source, synthio.LFO):
                    total_modulation += source.value * amount
            if hasattr(target, 'value'):
                target.value += total_modulation

    def process_effects(self, synth):
        for effect in self.effects:
            effect.process(synth)

class SynthAudioOutputManager:
    def __init__(self):
        self.mixer = audiomixer.Mixer(
            sample_rate=Constants.SAMPLE_RATE,
            buffer_size=Constants.AUDIO_BUFFER_SIZE,
            channel_count=2  # Using stereo for MPE panning
        )
        self.audio = audiobusio.I2SOut(
            bit_clock=Constants.I2S_BIT_CLOCK,
            word_select=Constants.I2S_WORD_SELECT,
            data=Constants.I2S_DATA
        )
        self.synth = synthio.Synthesizer(
            sample_rate=Constants.SAMPLE_RATE,
            channel_count=2  # Using stereo for MPE panning
        )
        self.volume = 1.0
        self._setup_audio()

    def _setup_audio(self):
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
        self.voice_manager = SynthVoiceManager()
        self.synth_engine = SynthEngine()
        self.audio_output_manager = audio_output_manager
        self.synth = self.audio_output_manager.get_synth()
        self.max_amplitude = 0.9
        self.instrument = None
        self.current_midi_values = {}

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
            self.handle_control_change(cc_number, midi_value, midi_value / 127.0)

    def process_midi_event(self, event):
        event_type, *params = event
        if event_type == 'note_on':
            self.play_note(*params)
        elif event_type == 'note_off':
            self.stop_note(*params)
        elif event_type == 'note_update':
            self.update_note(*params)
        elif event_type == 'pitch_bend':
            self.apply_pitch_bend(*params)
        elif event_type == 'control_change':
            self.handle_control_change(*params)
        elif event_type == 'pressure_update':
            self.handle_pressure_update(*params)

    def play_note(self, midi_note, velocity, key_id):
        frequency = self._fractional_midi_to_hz(midi_note)
        envelope = self.synth_engine.create_envelope()
        waveform = self.synth_engine.get_waveform(self.instrument.oscillator['waveform'])
        
        note = self.voice_manager.allocate_voice(key_id, frequency, velocity, envelope, waveform)
        
        if note is not None:
            if self.synth_engine.filter:
                note.filter = self.synth_engine.filter(self.synth)
            self.synth.press(note)
            self._apply_amplitude_scaling()

    def stop_note(self, midi_note, velocity, key_id):
        note = self.voice_manager.release_voice(key_id)
        if note:
            self.synth.release(note)
            self._apply_amplitude_scaling()

    def update_note(self, midi_note, velocity, key_id):
        note = self.voice_manager.get_note_by_key_id(key_id)
        if note:
            frequency = self._fractional_midi_to_hz(midi_note)
            note.frequency = frequency
            self._apply_amplitude_scaling()

    def apply_pitch_bend(self, lsb, msb, key_id):
        if self.synth_engine.pitch_bend_enabled:
            note = self.voice_manager.get_note_by_key_id(key_id)
            if note:
                # Convert 14-bit MIDI pitch bend to semitones
                bend_value = (msb << 7) + lsb
                normalized_bend = (bend_value - 8192) / 8192.0
                bend_range = self.synth_engine.pitch_bend_range / 12.0  # Convert semitones to octaves
                note.bend = normalized_bend * bend_range

    def handle_pressure_update(self, key_id, left_pressure, right_pressure):
        if not self.synth_engine.pressure_enabled:
            return
            
        # Average the pressures
        avg_pressure = (left_pressure + right_pressure) / 2.0
        
        # Apply pressure to synth engine parameters
        self.synth_engine.apply_pressure(avg_pressure, key_id)
        
        note = self.voice_manager.get_note_by_key_id(key_id)
        if note:
            # Update the note's envelope to reflect any pressure-based changes
            note.envelope = self.synth_engine.create_envelope()
            
            # Calculate panning from pressure difference
            if left_pressure != right_pressure:
                pressure_diff = right_pressure - left_pressure
                note.panning = pressure_diff  # -1.0 to 1.0 for full left to right
            
            # Update filter based on pressure
            if self.synth_engine.filter:
                note.filter = self.synth_engine.filter(self.synth)
            
            self._apply_amplitude_scaling()

    def handle_control_change(self, cc_number, midi_value, normalized_value):
        self.current_midi_values[cc_number] = midi_value
        pots_config = self.instrument.pots
        for pot_index, pot_config in pots_config.items():
            if pot_config['cc'] == cc_number:
                param_name = pot_config['name']
                min_val = pot_config['min']
                max_val = pot_config['max']
                scaled_value = min_val + normalized_value * (max_val - min_val)
                
                # Print pot change information
                print(f"P{pot_index}: {param_name}: {self.current_midi_values.get(cc_number, 0)/127.0:.2f} -> {normalized_value:.2f}")

                if param_name == 'Filter Cutoff':
                    self.synth_engine.set_filter_cutoff(scaled_value)
                elif param_name == 'Filter Resonance':
                    self.synth_engine.set_filter_resonance(scaled_value)
                elif param_name == 'Detune Amount':
                    self.synth_engine.set_detune(scaled_value)
                elif param_name == 'Attack Time':
                    self.synth_engine.set_envelope_param('attack', scaled_value)
                    self._update_active_notes()  # Update all active notes with new envelope
                elif param_name == 'Decay Time':
                    self.synth_engine.set_envelope_param('decay', scaled_value)
                    self._update_active_notes()  # Update all active notes with new envelope
                elif param_name == 'Sustain Level':
                    self.synth_engine.set_envelope_param('sustain', scaled_value)
                    self._update_active_notes()  # Update all active notes with new envelope
                elif param_name == 'Release Time':
                    self.synth_engine.set_envelope_param('release', scaled_value)
                    self._update_active_notes()  # Update all active notes with new envelope
                elif param_name == 'Bend Range':
                    self.synth_engine.pitch_bend_range = scaled_value
                elif param_name == 'Bend Curve':
                    self.synth_engine.pitch_bend_curve = scaled_value
                
                break

    def _update_active_notes(self):
        # Create a new envelope with current settings
        new_envelope = self.synth_engine.create_envelope()
        # Update all active notes with the new envelope
        self.voice_manager.update_all_envelopes(new_envelope)
        # Update filters if needed
        active_notes = self.voice_manager.get_active_notes()
        for note in active_notes:
            if self.synth_engine.filter:
                note.filter = self.synth_engine.filter(self.synth)

    def _apply_amplitude_scaling(self):
        active_notes = self.voice_manager.get_active_notes()
        if not active_notes:
            return

        total_amplitude = sum(note.amplitude for note in active_notes)
        if total_amplitude > self.max_amplitude:
            scale_factor = self.max_amplitude / total_amplitude
            for note in active_notes:
                note.amplitude *= scale_factor

    def update(self, midi_events):
        for event in midi_events:
            self.process_midi_event(event)
        self.synth_engine.update(self.synth)

    def stop(self):
        self.voice_manager.release_all_voices()
        self.audio_output_manager.stop()

    def _fractional_midi_to_hz(self, midi_note):
        return 440 * (2 ** ((midi_note - 69) / 12))
