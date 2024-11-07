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

class SynthAudioOutputManager:
    def __init__(self):
        self.mixer = audiomixer.Mixer(
            sample_rate=Constants.SAMPLE_RATE,
            buffer_size=Constants.AUDIO_BUFFER_SIZE,
            channel_count=2
        )
        self.audio = audiobusio.I2SOut(
            bit_clock=Constants.I2S_BIT_CLOCK,
            word_select=Constants.I2S_WORD_SELECT,
            data=Constants.I2S_DATA
        )
        self.synth = synthio.Synthesizer(
            sample_rate=Constants.SAMPLE_RATE,
            channel_count=2
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
        self.synth_engine = SynthEngine()
        self.audio_output_manager = audio_output_manager
        self.synth = self.audio_output_manager.get_synth()
        self.max_amplitude = 0.9
        self.instrument = None
        self.current_midi_values = {}
        self.active_notes = {}  # {midi_note: note}

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
            midi_note, velocity, key_id = params
            self.play_note(midi_note, velocity)
        elif event_type == 'note_off':
            midi_note, velocity, key_id = params
            self.stop_note(midi_note)
        elif event_type == 'note_update':
            midi_note, velocity, key_id = params
            self.update_note(midi_note, velocity)
        elif event_type == 'pitch_bend':
            lsb, msb, key_id = params
            self.apply_pitch_bend(lsb, msb)
        elif event_type == 'control_change':
            cc_number, midi_value, normalized_value = params
            self.handle_control_change(cc_number, midi_value, normalized_value)
        elif event_type == 'pressure_update':
            key_id, left_pressure, right_pressure = params
            self.handle_pressure_update(left_pressure, right_pressure)

    def play_note(self, midi_note, velocity):
        frequency = self._fractional_midi_to_hz(midi_note)
        envelope = self.synth_engine.create_envelope()
        waveform = self.synth_engine.get_waveform(self.instrument.oscillator['waveform'])
        
        # First release any existing note for this midi_note
        if midi_note in self.active_notes:
            old_note = self.active_notes[midi_note]
            self.synth.release([old_note])
        
        note = synthio.Note(
            frequency=frequency,
            envelope=envelope,
            amplitude=velocity / 127.0,
            waveform=waveform,
            bend=0.0,
            panning=0.0
        )
        
        if self.synth_engine.filter:
            note.filter = self.synth_engine.filter(self.synth)
            
        self.active_notes[midi_note] = note
        self.synth.press([note])

    def stop_note(self, midi_note):
        if midi_note in self.active_notes:
            note = self.active_notes[midi_note]
            self.synth.release([note])
            del self.active_notes[midi_note]

    def update_note(self, midi_note, velocity):
        if midi_note in self.active_notes:
            note = self.active_notes[midi_note]
            note.frequency = self._fractional_midi_to_hz(midi_note)

    def apply_pitch_bend(self, lsb, msb):
        if not self.synth_engine.pitch_bend_enabled:
            return
            
        bend_value = (msb << 7) + lsb
        normalized_bend = (bend_value - 8192) / 8192.0
        bend_range = self.synth_engine.pitch_bend_range / 12.0
        
        # Apply pitch bend to all active notes
        for note in self.active_notes.values():
            note.bend = normalized_bend * bend_range

    def handle_pressure_update(self, left_pressure, right_pressure):
        if not self.synth_engine.pressure_enabled:
            return
            
        avg_pressure = (left_pressure + right_pressure) / 2.0
        self.synth_engine.apply_pressure(avg_pressure)
        
        # Update all active notes
        for note in self.active_notes.values():
            note.envelope = self.synth_engine.create_envelope()
            
            if left_pressure != right_pressure:
                pressure_diff = right_pressure - left_pressure
                note.panning = pressure_diff
            
            if self.synth_engine.filter:
                note.filter = self.synth_engine.filter(self.synth)

    def handle_control_change(self, cc_number, midi_value, normalized_value):
        self.current_midi_values[cc_number] = midi_value
        pots_config = self.instrument.pots
        for pot_index, pot_config in pots_config.items():
            if pot_config['cc'] == cc_number:
                param_name = pot_config['name']
                min_val = pot_config['min']
                max_val = pot_config['max']
                scaled_value = min_val + normalized_value * (max_val - min_val)
                
                print(f"P{pot_index}: {param_name}: {self.current_midi_values.get(cc_number, 0)/127.0:.2f} -> {normalized_value:.2f}")

                if param_name == 'Filter Cutoff':
                    self.synth_engine.set_filter_cutoff(scaled_value)
                elif param_name == 'Filter Resonance':
                    self.synth_engine.set_filter_resonance(scaled_value)
                elif param_name == 'Detune Amount':
                    self.synth_engine.set_detune(scaled_value)
                elif param_name == 'Attack Time':
                    self.synth_engine.set_envelope_param('attack', scaled_value)
                    self._update_active_notes()
                elif param_name == 'Decay Time':
                    self.synth_engine.set_envelope_param('decay', scaled_value)
                    self._update_active_notes()
                elif param_name == 'Sustain Level':
                    self.synth_engine.set_envelope_param('sustain', scaled_value)
                    self._update_active_notes()
                elif param_name == 'Release Time':
                    self.synth_engine.set_envelope_param('release', scaled_value)
                    self._update_active_notes()
                elif param_name == 'Bend Range':
                    self.synth_engine.pitch_bend_range = scaled_value
                elif param_name == 'Bend Curve':
                    self.synth_engine.pitch_bend_curve = scaled_value
                
                break

    def _update_active_notes(self):
        new_envelope = self.synth_engine.create_envelope()
        for note in self.active_notes.values():
            note.envelope = new_envelope
            if self.synth_engine.filter:
                note.filter = self.synth_engine.filter(self.synth)

    def update(self, midi_events):
        for event in midi_events:
            self.process_midi_event(event)

    def stop(self):
        if self.active_notes:
            self.synth.release(list(self.active_notes.values()))
            self.active_notes.clear()
        self.audio_output_manager.stop()

    def _fractional_midi_to_hz(self, midi_note):
        return 440 * (2 ** ((midi_note - 69) / 12))
