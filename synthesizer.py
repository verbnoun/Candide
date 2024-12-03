"""
synthesizer.py - Route Processing and Voice Management
Each route is processed in a clear, linear fashion matching the route structure.
"""

import sys
import time
import synthio
from constants import SYNTH_DEBUG, SAMPLE_RATE, AUDIO_CHANNEL_COUNT


def _log(message, module="SYNTH"):
    if not SYNTH_DEBUG:
        return
    BLUE = "\033[94m"
    RED = "\033[31m"
    RESET = "\033[0m"
    prefix = RED if "[ERROR]" in str(message) else BLUE
    print(f"{prefix}[{module}] {message}{RESET}", file=sys.stderr)

class SynthEngine:
    def __init__(self):
        _log("Initializing SynthEngine")
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        self.active_voices = {}  # key: voice_id (e.g. "V74.1"), value: Note object
        self.route_manager = RouteManager(self)

    def handle_route(self, route):
        """Pass route handling to RouteManager"""
        self.route_manager.handle_route(route)

    def get_synth(self):
        """Return synthesizer instance for audio system"""
        return self.synth

    def test_audio_hardware(self):
        """Test audio output hardware with a simple beep"""
        _log("Testing audio hardware")
        try:
            self.synth.press(64)  # Middle C
            time.sleep(0.1)
            self.synth.release(64)
            time.sleep(0.05)
            _log("Audio test complete")
        except Exception as e:
            _log(f"[ERROR] Audio test failed: {str(e)}")

    def cleanup_voices(self):
        """Clean up any finished voices - called in main update loop"""
        pass

    def release_all_notes(self):
        """Release all currently active notes - used when switching instruments"""
        _log("Releasing all notes")
        self.active_voices.clear()
        try:
            self.synth.deinit()
            self.synth = synthio.Synthesizer(
                sample_rate=SAMPLE_RATE,
                channel_count=AUDIO_CHANNEL_COUNT
            )
        except Exception as e:
            _log(f"[ERROR] Failed to release all notes: {str(e)}")

    def cleanup(self):
        """Clean up voice manager resources on shutdown"""
        _log("Cleaning up voice manager")
        if self.synth:
            try:
                self.synth.deinit()
                _log("Synthesizer deinitialized")
            except Exception as e:
                _log(f"[ERROR] Failed to deinit synthesizer: {str(e)}")

class RouteManager:
    def __init__(self, engine):
        _log("Initializing RouteManager")
        self.engine = engine
        self.oscillator = OscillatorProcessor(engine)
        self.filter = FilterProcessor(engine)
        self.amplifier = AmplifierProcessor(engine)
        self.lfo = LfoProcessor(engine)
        self.note = NoteProcessor(engine)

    def handle_route(self, route):
        """Process incoming route string and dispatch to appropriate handler"""
        _log(f"Processing route: {route}")
        try:
            parts = route.strip().split('/')
            if len(parts) < 2:
                _log(f"[ERROR] Invalid route format: {route}")
                return

            scope = parts[-2]
            value = parts[-1] if len(parts) > 2 else None
            _log(f"Scope: {scope}, Value: {value}")

            if parts[0] == "oscillator":
                self.oscillator.process_route(parts[1:], scope, value)
            elif parts[0] == "filter":
                self.filter.process_route(parts[1:], scope, value)
            elif parts[0] == "amplifier":
                self.amplifier.process_route(parts[1:], scope, value)
            elif parts[0] == "lfo":
                self.lfo.process_route(parts[1:], scope, value)
            elif parts[0] == "note":
                self.note.process_route(parts[1:], scope, value)

        except Exception as e:
            _log(f"[ERROR] Route processing failed: {str(e)}")

class NoteProcessor:
    def __init__(self, engine):
        self.engine = engine
        
    def process_route(self, parts, scope, value):
        if parts[0] == "press":
            try:
                # Extract note number from voice ID (e.g. "V74.1" -> 74)
                note_num = int(value[1:].split('.')[0])
                freq = synthio.midi_to_hz(note_num)
                
                # Create basic note with just frequency
                note = synthio.Note(frequency=freq)
                self.engine.synth.press(note)
                self.engine.active_voices[value] = note
                _log(f"Note press: MIDI {note_num} -> {freq:.2f} Hz")
                
            except ValueError as e:
                _log(f"[ERROR] Invalid note format: {value}")
                
        elif parts[0] == "release":
            try:
                voice_id = value  # e.g. "V74.1"
                if voice_id in self.engine.active_voices:
                    note = self.engine.active_voices[voice_id]
                    self.engine.synth.release(note)
                    del self.engine.active_voices[voice_id]
                    _log(f"Note release: {voice_id}")
            except Exception as e:
                _log(f"[ERROR] Note release failed: {str(e)}")

class OscillatorProcessor:
    def process_route(self, parts, scope, value):
        if parts[0] == "ring":
            self.handle_ring(parts[1], scope, value)
        elif parts[0] == "waveform":
            _log(f"Setting main oscillator waveform to {value} for {scope}")
            
    def handle_ring(self, param, scope, value):
        if param == "frequency":
            _log(f"Setting ring oscillator frequency to {value} for {scope}")
        elif param == "bend":
            _log(f"Setting ring oscillator bend to {value} for {scope}")
        elif param == "waveform":
            _log(f"Setting ring oscillator waveform to {value} for {scope}")

class FilterProcessor:
    def process_route(self, parts, scope, value):
        if parts[0] == "band_pass":
            self.handle_bandpass(parts[1], scope, value)
            
    def handle_bandpass(self, param, scope, value):
        if param == "resonance":
            _log(f"Setting bandpass filter resonance to {value} for {scope}")
        elif param == "frequency":
            _log(f"Setting bandpass filter frequency to {value} for {scope}")

class AmplifierProcessor:
    def process_route(self, parts, scope, value):
        if parts[0] == "envelope":
            self.handle_envelope(parts[1], scope, value)
            
    def handle_envelope(self, param, scope, value):
        if param == "attack_time":
            _log(f"Setting envelope attack time to {value} for {scope}")
        elif param == "decay_time":
            _log(f"Setting envelope decay time to {value} for {scope}")
        elif param == "release_time":
            _log(f"Setting envelope release time to {value} for {scope}")
        elif param == "sustain_level":
            _log(f"Setting envelope sustain level to {value} for {scope}")
        elif param == "attack_level":
            _log(f"Setting envelope attack level to {value} for {scope}")

class LfoProcessor:
    def process_route(self, parts, scope, value):
        if parts[0] == "rate":
            _log(f"Setting LFO rate to {value} for {scope}")
        elif parts[0] == "scale":
            _log(f"Setting LFO scale to {value} for {scope}")
        elif parts[0] == "offset":
            _log(f"Setting LFO offset to {value} for {scope}")
        elif parts[0] == "phase_offset":
            _log(f"Setting LFO phase offset to {value} for {scope}")
        elif parts[0] == "once":
            _log(f"Setting LFO once to {value} for {scope}")
        elif parts[0] == "interpolate":
            _log(f"Setting LFO interpolate to {value} for {scope}")