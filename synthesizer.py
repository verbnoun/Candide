"""
synthesizer.py - Route Processing and Voice Management
"""

import sys
import time
import synthio
from constants import SYNTH_DEBUG, SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from timing import timing_stats, TimingContext
from modules import RouteManager

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
    def __init__(self, address, engine):
        self.address = address
        self.engine = engine
        self.note = None
        self.stored_values = {}
        self.state = "initializing"
        self.creation_time = time.monotonic()
        self.last_update = self.creation_time
        
        # Parse note number from address (format: Vnote.channel)
        try:
            if not address.startswith('V'):
                self.state = "error"
                _log(f"[ERROR] Invalid voice ID format: {address}")
                return
                
            note_channel = address[1:].split('.')
            if len(note_channel) != 2:
                self.state = "error"
                _log(f"[ERROR] Invalid voice ID format: {address}")
                return
                
            self.note_number = int(note_channel[0])
            if not 0 <= self.note_number <= 127:
                self.state = "error"
                _log(f"[ERROR] Invalid MIDI note number {self.note_number} for {address}")
                return
                
        except (ValueError, IndexError):
            self.state = "error"
            _log(f"[ERROR] Could not parse note number from address: {address}")
            return
        
        # Initialize with any existing global values
        for route_path, value in engine.global_values.items():
            self.stored_values[route_path] = value
        
        _log(f"Created voice container for {address} with note {self.note_number}")

    def receive_value(self, route_path, value):
        """Store value and check if we have minimum set for any action"""
        if self.state in ["error", "released"]:
            return
            
        self.stored_values[route_path] = value
        self.last_update = time.monotonic()
        
        if self.state == "initializing":
            self.check_sets()
        
    def check_sets(self):
        """Check if we have complete minimum set for press"""
        required_paths = {
            "note/press",
            "oscillator/frequency", 
            "oscillator/waveform"
        }
        
        # Only proceed if we have all required values and note isn't already pressed
        if all(path in self.stored_values for path in required_paths) and self.note is None:
            self.apply_press()

    def apply_press(self):
        """Create and press note when we have minimum required values"""
        try:
            if self.state != "initializing":
                return

            # Validate frequency value
            freq_value = self.stored_values["oscillator/frequency"]
            try:
                freq = synthio.midi_to_hz(int(freq_value))
                if not 20 <= freq <= 20000:  # Basic frequency range check
                    raise ValueError(f"Frequency {freq} Hz out of range")
            except (ValueError, TypeError) as e:
                self.state = "error"
                _log(f"[ERROR] Invalid frequency value {freq_value}: {str(e)}")
                return

            waveform = self.stored_values["oscillator/waveform"]
            
            # Get filter if available
            filter_params = self.get_active_filter()
            filter_obj = None
            if filter_params:
                filter_type, frequency, resonance = filter_params
                filter_obj = self.engine.route_manager.filter.create_filter(
                    filter_type, frequency, resonance
                )
            
            # Get envelope if all parameters are available
            envelope_params = self.get_envelope_params()
            envelope_obj = None
            if envelope_params:
                envelope_obj = self.engine.route_manager.amplifier.create_envelope(
                    envelope_params
                )
            
            # Calculate amplitude based on number of active notes
            active_notes_count = len([v for v in self.engine.active_voices.values() if v.state == "active"])
            # If this is a new note being pressed, include it in the count
            if self.state == "initializing":
                active_notes_count += 1
            # Calculate amplitude scaling factor (1/sqrt(n) gives good perceptual balance)
            amplitude = 1.0 / (active_notes_count ** 0.5) if active_notes_count > 0 else 1.0
            
            # Create new note instance
            self.note = synthio.Note(
                frequency=freq,
                waveform=waveform,
                filter=filter_obj,
                envelope=envelope_obj,
                amplitude=amplitude
            )
            
            # Press the note and update state atomically
            try:
                self.engine.synth.press(self.note)
                self.state = "active"
                self.last_update = time.monotonic()
                _log(f"Pressed note for {self.address} with freq: {freq} and amplitude: {amplitude}")
                
                # Update amplitudes of other active notes
                self.engine.update_note_amplitudes()
            except Exception as e:
                self.note = None
                self.state = "error"
                _log(f"[ERROR] Failed to press note: {str(e)}")
            
        except Exception as e:
            self.note = None
            self.state = "error"
            _log(f"[ERROR] Failed to apply press set: {str(e)}")

    def release(self):
        """Release note if it exists"""
        if self.state == "released":
            return False
            
        success = False
        if self.note and self.state == "active":
            try:
                self.engine.synth.release(self.note)
                success = True
                _log(f"Released note for {self.address}")
            except Exception as e:
                _log(f"[ERROR] Failed to release note for {self.address}: {str(e)}")
            finally:
                self.note = None
                
        # Always update state even if release failed
        self.state = "released"
        self.last_update = time.monotonic()
        
        # Update amplitudes of remaining notes after release
        if success:
            self.engine.update_note_amplitudes()
            
        return success

    def get_active_filter(self):
        """Check if we have a complete filter set and return it"""
        if self.state in ["error", "released"]:
            return None
            
        filter_types = ['low_pass', 'high_pass', 'band_pass', 'notch']
        
        for filter_type in filter_types:
            freq_path = f"filter/{filter_type}/frequency"
            res_path = f"filter/{filter_type}/resonance"
            
            if freq_path in self.stored_values and res_path in self.stored_values:
                return (filter_type,
                       self.stored_values[freq_path],
                       self.stored_values[res_path])
        
        return None

    def get_envelope_params(self):
        """Collect all available envelope parameters"""
        if self.state in ["error", "released"]:
            return None
            
        envelope_params = {}
        param_names = [
            'attack_time',
            'decay_time', 
            'release_time',
            'attack_level',
            'sustain_level'
        ]
        
        for param in param_names:
            route_path = f"amplifier/envelope/{param}"
            if route_path in self.stored_values:
                envelope_params[param] = self.stored_values[route_path]
                
        return envelope_params if len(envelope_params) == len(param_names) else None

class SynthEngine:
    """Central manager for synthesis system"""
    def __init__(self):
        _log("Initializing SynthEngine")
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        self.active_voices = {}
        self.global_values = {}
        self.route_manager = RouteManager(self)
        self.VOICE_TIMEOUT = 30.0  # Maximum lifetime for a voice in seconds

    def get_synth(self):
        """Return synthesizer instance for audio system"""
        return self.synth

    def store_value(self, scope, route_path, value):
        """Store route value either globally or to specific voice"""
        if scope == "global":
            self.global_values[route_path] = value
            # Update all active voices with new global
            for voice in self.active_voices.values():
                if voice.state not in ["released", "error"]:
                    voice.receive_value(route_path, value)
        else:
            # Pass to specific voice if it exists and valid
            voice = self.active_voices.get(scope)
            if voice and voice.state not in ["released", "error"]:
                voice.receive_value(route_path, value)
            
    def handle_route(self, route, timing_id=None):
        """Pass route handling to RouteManager"""
        try:
            with TimingContext(timing_stats, "synth", timing_id):
                # Split route into parts
                parts = route.strip().split('/')
                if len(parts) < 2:
                    _log(f"[ERROR] Invalid route format: {route}")
                    return

                # For note/press and note/release routes, the scope is the last part
                if parts[0] == "note" and parts[1] in ["press", "release"]:
                    scope = parts[-1]
                    value = None
                else:
                    # For other routes, extract scope and value normally
                    scope = parts[-2]
                    value = parts[-1] if len(parts) > 2 else None
                
                # Process route based on type
                processed = False
                if parts[0] == "note":
                    self.route_manager.note.process_route(parts[1:], scope, value)
                    processed = True
                elif parts[0] == "oscillator":
                    self.route_manager.oscillator.process_route(parts[1:], scope, value)
                    processed = True
                elif parts[0] == "filter":
                    self.route_manager.filter.process_route(parts[1:], scope, value)
                    processed = True
                elif parts[0] == "amplifier":
                    self.route_manager.amplifier.process_route(parts[1:], scope, value)
                    processed = True
                elif parts[0] == "lfo":
                    self.route_manager.lfo.process_route(parts[1:], scope, value)
                    processed = True
                
                if not processed:
                    _log(f"[ERROR] No processor for route type: {parts[0]}")
                
        except Exception as e:
            _log(f"[ERROR] Failed to handle route: {str(e)}")
        finally:
            # Always attempt cleanup after route processing
            self.cleanup_voices()

    def update_note_amplitudes(self):
        """Update amplitudes of all active notes based on total count"""
        try:
            active_notes = [v for v in self.active_voices.values() if v.state == "active" and v.note]
            active_count = len(active_notes)
            
            if active_count == 0:
                return
                
            # Calculate new amplitude (1/sqrt(n) gives good perceptual balance)
            new_amplitude = 1.0 / (active_count ** 0.5)
            
            # Update amplitude for all active notes
            for voice in active_notes:
                if voice.note:
                    voice.note.amplitude = new_amplitude
                    
            _log(f"Updated {active_count} notes to amplitude: {new_amplitude:.3f}")
            
        except Exception as e:
            _log(f"[ERROR] Failed to update note amplitudes: {str(e)}")

    def cleanup_voices(self):
        """Clean up finished or timed out voices"""
        current_time = time.monotonic()
        to_remove = []
        
        for voice_id, voice in self.active_voices.items():
            try:
                # Always remove error state voices
                if voice.state == "error":
                    to_remove.append((voice_id, "error state"))
                    continue
                    
                # Remove released voices
                if voice.state == "released":
                    to_remove.append((voice_id, "released"))
                    continue
                    
                # Handle stuck voices
                if current_time - voice.last_update > self.VOICE_TIMEOUT:
                    _log(f"Voice {voice_id} timed out, forcing release")
                    voice.release()
                    to_remove.append((voice_id, "timeout"))
                    continue
                    
                # Remove voices that lost their note reference
                if voice.state == "active" and voice.note is None:
                    _log(f"Voice {voice_id} lost note reference while active")
                    voice.state = "error"
                    to_remove.append((voice_id, "lost note"))
                    
            except Exception as e:
                _log(f"[ERROR] Failed to check voice {voice_id}: {str(e)}")
                to_remove.append((voice_id, "error during check"))
                
        # Remove marked voices
        for voice_id, reason in to_remove:
            try:
                del self.active_voices[voice_id]
                _log(f"Cleaned up voice {voice_id} ({reason})")
            except Exception as e:
                _log(f"[ERROR] Failed to remove voice {voice_id}: {str(e)}")

    def test_audio_hardware(self):
        """Test audio output hardware with a simple beep"""
        _log("Testing audio hardware")
        try:
            test_note = synthio.Note(frequency=440)  # A4 note
            self.synth.press(test_note)
            time.sleep(0.1)
            self.synth.release(test_note)
            time.sleep(0.05)
            _log("Audio test complete")
        except Exception as e:
            _log(f"[ERROR] Audio test failed: {str(e)}")

    def release_all_notes(self):
        """Release all currently active notes"""
        _log("Releasing all notes")
        failures = []
        for voice in list(self.active_voices.values()):
            try:
                if not voice.release():
                    failures.append(voice.address)
            except Exception as e:
                _log(f"[ERROR] Failed to release voice {voice.address}: {str(e)}")
                failures.append(voice.address)
                
        self.active_voices.clear()
        if failures:
            _log(f"[ERROR] Failed to cleanly release voices: {', '.join(failures)}")

    def clear_routes(self):
        """Clear all routes and reset state for instrument switch"""
        _log("Clearing all routes for instrument switch")
        try:
            # Release all notes first
            self.release_all_notes()
            _log("Released all notes")
            
            # Clear all stored values in engine
            self.global_values.clear()
            _log("Cleared global values")
            
            # Reset voice manager state
            self.active_voices.clear()
            _log("Cleared active voices")
            
            # Tell synthesizer to clear all routes in holding
            self.synth.release_all()
            _log("Released all synthio notes")
            
            # Clear stored values in each processor
            for voice in list(self.active_voices.values()):
                voice.stored_values.clear()
            _log("Cleared voice stored values")
            
            # Clear waveform cache
            if hasattr(self.route_manager.oscillator, '_waveforms'):
                self.route_manager.oscillator._waveforms.clear()
                _log("Cleared waveform cache")
            
            # Ensure any remaining voices are fully cleaned up
            self.cleanup_voices()
            _log("Final voice cleanup complete")
            
            _log("Routes and all stored values cleared successfully")
        except Exception as e:
            _log(f"[ERROR] Failed to clear routes: {str(e)}")
            # Even if we hit an error, try to ensure basic state is cleared
            try:
                self.global_values.clear()
                self.active_voices.clear()
                self.synth.release_all()
                _log("Emergency cleanup completed")
            except Exception as cleanup_error:
                _log(f"[ERROR] Emergency cleanup also failed: {str(cleanup_error)}")

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
