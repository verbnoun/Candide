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


class Voice:
    """Voice management including route collection and note lifecycle"""
    def __init__(self, address, synth):
        self.address = address
        self.synth = synth
        self.note = None
        
        # Route collections for different operations
        self.route_sets = {
            "press": {
                "required": {"note/press", "oscillator/frequency", "oscillator/waveform"},
                "routes": {}
            }
            # Future sets would be defined here following same pattern
        }
        _log(f"Created voice container for {address}")

    def receive_route(self, route_type, param, value):
        """Store route and check if we have a complete set"""
        route_path = f"{route_type}/{param}"
        
        # Store route in all relevant sets
        for set_name, set_data in self.route_sets.items():
            if route_path in set_data["required"]:
                set_data["routes"][route_path] = value
                self.try_apply_set(set_name)

    def try_apply_set(self, set_name):
        """Check if we have a complete set and apply it"""
        set_data = self.route_sets[set_name]
        received_routes = set(set_data["routes"].keys())
        
        if received_routes >= set_data["required"]:
            if set_name == "press":
                self.apply_press()
            # Future sets would be handled here
            set_data["routes"].clear()

    def apply_press(self):
        """Create and press note with collected routes"""
        try:
            routes = self.route_sets["press"]["routes"]
            freq = synthio.midi_to_hz(int(routes["oscillator/frequency"]))
            waveform = routes["oscillator/waveform"]
            
            self.note = synthio.Note(frequency=freq, waveform=waveform)
            self.synth.press(self.note)
            _log(f"Pressed note for {self.address}")
        except Exception as e:
            _log(f"[ERROR] Failed to apply press set: {str(e)}")
            
    def release(self):
        """Release note if it exists"""
        if self.note:
            try:
                self.synth.release(self.note)
                _log(f"Released note for {self.address}")
            except Exception as e:
                _log(f"[ERROR] Failed to release note for {self.address}: {str(e)}")
        self.note = None

class SynthEngine:
    def __init__(self):
        _log("Initializing SynthEngine")
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        self.active_voices = {}  # key: voice_id (e.g. "V74.1"), value: Voice object
        self.route_manager = RouteManager(self)

    def handle_route(self, route):
        """Pass route handling to RouteManager"""
        self.route_manager.handle_route(route)

    def get_synth(self):
        """Return synthesizer instance for audio system"""
        return self.synth

    def route_to_voice(self, voice_id, route_path, value):
        """Route a value to a specific voice if it exists"""
        if voice_id in self.active_voices:
            route_type, param = route_path.split('/', 1)
            self.active_voices[voice_id].receive_route(route_type, param, value)
        else:
            _log(f"[ERROR] Route to non-existent voice: {voice_id}")

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

    def release_all_notes(self):
        """Release all currently active notes"""
        _log("Releasing all notes")
        for voice in self.active_voices.values():
            voice.release()
        self.active_voices.clear()

    def cleanup_voices(self):
        """Clean up any finished voices - called in main update loop"""
        try:
            # Get list of voices to remove to avoid modifying dict during iteration
            to_remove = []
            
            for voice_id, voice in self.active_voices.items():
                # Add any voice cleanup conditions here
                if voice.note is None:
                    to_remove.append(voice_id)
                    _log(f"Marking voice for cleanup: {voice_id}")
                
            # Remove marked voices
            for voice_id in to_remove:
                del self.active_voices[voice_id]
                _log(f"Cleaned up voice: {voice_id}")
                
        except Exception as e:
            _log(f"[ERROR] Voice cleanup failed: {str(e)}")

    def cleanup(self):
        """Clean up resources on shutdown"""
        _log("Cleaning up synth engine")
        self.release_all_notes()
        if self.synth:
            try:
                self.synth.deinit()
                _log("Synthesizer deinitialized")
            except Exception as e:
                _log(f"[ERROR] Failed to deinit synthesizer: {str(e)}")


class NoteProcessor:
    def __init__(self, engine):
        self.engine = engine
        
    def process_route(self, parts, scope, value):
        try:
            if parts[0] == "press":
                voice = Voice(value, self.engine.synth)
                self.engine.active_voices[value] = voice
                self.engine.route_to_voice(value, "note/press", value)
                
            elif parts[0] == "release":
                if value in self.engine.active_voices:
                    self.engine.active_voices[value].release()
                    del self.engine.active_voices[value]
                else:
                    _log(f"[ERROR] Attempted release of non-existent voice: {value}")
            else:
                _log(f"[ERROR] No module for note/{parts[0]}")
                    
        except Exception as e:
            _log(f"[ERROR] Note processing failed: {str(e)}")


class OscillatorProcessor:
    def __init__(self, engine):
        self.engine = engine
        self.global_waveform = None
        
        # Waveform generators
        self.waveforms = {
            "sine": self.generate_sine,
            "triangle": self.generate_triangle,
            "saw": self.generate_saw
        }

    def process_route(self, parts, scope, value):
        try:
            if parts[0] == "waveform":
                waveform = self.create_waveform(value)
                if scope == "global":
                    self.global_waveform = waveform
                    _log(f"Set global waveform to {value}")
                else:
                    self.engine.route_to_voice(scope, "oscillator/waveform", waveform)
            elif parts[0] == "frequency":
                self.engine.route_to_voice(scope, "oscillator/frequency", value)
            else:
                _log(f"[ERROR] No module for oscillator/{parts[0]}")
        except Exception as e:
            _log(f"[ERROR] Oscillator processing failed: {str(e)}")

    def create_waveform(self, type_name):
        if type_name in self.waveforms:
            return self.waveforms[type_name]()
        _log(f"[ERROR] Unknown waveform type: {type_name}")
        return self.generate_sine()  # Safe fallback

    def generate_sine(self):
        # Generate sine wave sample buffer
        # Implementation needed
        pass

    def generate_triangle(self):
        # Generate triangle wave sample buffer
        # Implementation needed
        pass

    def generate_saw(self):
        # Generate saw wave sample buffer
        # Implementation needed
        pass


class FilterProcessor:
    def __init__(self, engine):
        self.engine = engine

    def process_route(self, parts, scope, value):
        _log(f"[ERROR] No module for filter/{parts[0]}")


class AmplifierProcessor:
    def __init__(self, engine):
        self.engine = engine

    def process_route(self, parts, scope, value):
        _log(f"[ERROR] No module for amplifier/{parts[0]}")


class LfoProcessor:
    def __init__(self, engine):
        self.engine = engine

    def process_route(self, parts, scope, value):
        _log(f"[ERROR] No module for lfo/{parts[0]}")


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

            processed = False
            if parts[0] == "oscillator":
                self.oscillator.process_route(parts[1:], scope, value)
                processed = True
            elif parts[0] == "filter":
                self.filter.process_route(parts[1:], scope, value)
                processed = True
            elif parts[0] == "amplifier":
                self.amplifier.process_route(parts[1:], scope, value)
                processed = True
            elif parts[0] == "lfo":
                self.lfo.process_route(parts[1:], scope, value)
                processed = True
            elif parts[0] == "note":
                self.note.process_route(parts[1:], scope, value)
                processed = True
                
            if not processed:
                _log(f"[ERROR] No processor for route type: {parts[0]}")

        except Exception as e:
            _log(f"[ERROR] Route processing failed: {str(e)}")