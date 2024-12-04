"""
synthesizer.py - Route Processing and Voice Management

- we need to clear all routes on instrument switch
- note off needs to skip the buffer and maybe the line too in router.py
- volume knob
- multi note amplitude reduction calculation
- MPE continuous swamps the synth, must be thinned even if used
- what is an appropriate frequency to send MPE continuous, i think might need to update bart to lower output, we might just be doing as much as possible
- lag on envelope minimum and all paths
- overall efficiency improvements 

"""

import sys
import time
import synthio
from constants import SYNTH_DEBUG, SAMPLE_RATE, AUDIO_CHANNEL_COUNT
from timing import timing_stats, TimingContext

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
            self.note_number = int(address.split('.')[0][1:])  # Extract number after 'V'
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
            
            # Create new note instance
            self.note = synthio.Note(
                frequency=freq,
                waveform=waveform,
                filter=filter_obj,
                envelope=envelope_obj
            )
            
            # Press the note and update state atomically
            try:
                with TimingContext(timing_stats, "synth_process"):
                    self.engine.synth.press(self.note)
                    self.state = "active"
                    self.last_update = time.monotonic()
                    _log(f"Pressed note for {self.address} with freq: {freq}")
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
                with TimingContext(timing_stats, "synth_process"):
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
            
    def handle_route(self, route):
        """Pass route handling to RouteManager"""
        try:
            with TimingContext(timing_stats, "synth_process"):
                self.route_manager.handle_route(route)
        finally:
            # Always attempt cleanup after route processing
            self.cleanup_voices()

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
            
            # Clear all stored values
            self.global_values.clear()
            
            # Reset voice manager state
            self.active_voices.clear()
            
            _log("Routes cleared successfully")
        except Exception as e:
            _log(f"[ERROR] Failed to clear routes: {str(e)}")

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
    """Handles note on/off and related controls"""
    def __init__(self, engine):
        self.engine = engine
        
    def _validate_voice_id(self, voice_id):
        """Validate voice ID format and note number"""
        try:
            if not voice_id.startswith('V'):
                return False
            note_num = int(voice_id.split('.')[0][1:])  # Get number after 'V'
            return 0 <= note_num <= 127
        except (ValueError, IndexError):
            return False
            
    def process_route(self, parts, scope, value):
        """Process note routes with priority for release"""
        try:
            # Validate voice ID for all note operations
            if value and not self._validate_voice_id(value):
                _log(f"[ERROR] Invalid voice ID format or note number: {value}")
                return
                
            # Handle release routes first
            if parts[0] == "release":
                voice = self.engine.active_voices.get(value)
                if voice:
                    if voice.release():
                        _log(f"Successfully released voice {value}")
                    else:
                        _log(f"[ERROR] Failed to release voice {value}")
                return
                    
            # Handle press routes
            if parts[0] == "press":
                # Handle existing voice cases
                existing_voice = self.engine.active_voices.get(value)
                if existing_voice:
                    if existing_voice.state == "active":
                        _log(f"Voice {value} already active, ignoring press")
                        return
                    if existing_voice.state == "released":
                        _log(f"Removing released voice {value} before new press")
                        del self.engine.active_voices[value]
                    
                # Create new voice and store press route
                voice = Voice(value, self.engine)
                if voice.state != "error":
                    self.engine.active_voices[value] = voice
                    self.engine.store_value(value, "note/press", True)
                else:
                    _log(f"[ERROR] Not adding voice {value} due to initialization error")
                
            else:
                _log(f"[ERROR] Unknown note route type: {parts[0]}")
                    
        except Exception as e:
            _log(f"[ERROR] Note processing failed: {str(e)}")

class OscillatorProcessor:
    """Handles oscillator controls and waveform generation"""
    def __init__(self, engine):
        self.engine = engine
        
        # Initialize waveform buffers only when first requested
        self._waveforms = {}
        self.WAVE_LENGTH = 256  # Good balance of quality and memory
        
    def process_route(self, parts, scope, value):
        """Process oscillator routes"""
        try:
            if parts[0] == "waveform":
                if value not in ["sine", "square", "triangle", "saw"]:
                    _log(f"[ERROR] Unknown waveform type: {value}")
                    return
                
                # Generate or retrieve waveform
                waveform = self._get_waveform(value)
                if waveform is None:
                    _log(f"[ERROR] Failed to generate waveform: {value}")
                    return
                    
                if scope == "global":
                    self.engine.store_value(scope, "oscillator/waveform", waveform)
                    _log(f"Set global waveform to {value}")
                else:
                    # Future support for per-key waveforms
                    _log(f"[ERROR] Per-key waveform selection not yet implemented for scope: {scope}")
                    
            elif parts[0] == "frequency":
                self.engine.store_value(scope, "oscillator/frequency", value)
                
            else:
                _log(f"[ERROR] No module for oscillator/{parts[0]}")
                
        except Exception as e:
            _log(f"[ERROR] Oscillator processing failed: {str(e)}")

    def _get_waveform(self, type_name):
        """Get or generate requested waveform"""
        if type_name in self._waveforms:
            return self._waveforms[type_name]
            
        try:
            if type_name == "sine":
                waveform = self._generate_sine()
            elif type_name == "square":
                waveform = self._generate_square()
            elif type_name == "triangle":
                waveform = self._generate_triangle()
            elif type_name == "saw":
                waveform = self._generate_saw()
            else:
                return None
                
            self._waveforms[type_name] = waveform
            return waveform
            
        except Exception as e:
            _log(f"[ERROR] Failed to generate {type_name} waveform: {str(e)}")
            return None

    def _generate_sine(self):
        """Generate sine wave table"""
        import array
        import math
        
        samples = array.array('h')
        for i in range(self.WAVE_LENGTH):
            # Scale sine wave to 16-bit signed range
            value = int(32767 * math.sin(2 * math.pi * i / self.WAVE_LENGTH))
            samples.append(value)
        return samples

    def _generate_square(self):
        """Generate square wave table"""
        import array
        
        samples = array.array('h')
        half_length = self.WAVE_LENGTH // 2
        samples.extend([32767] * half_length)  # First half full positive
        samples.extend([-32767] * (self.WAVE_LENGTH - half_length))  # Second half full negative
        return samples

    def _generate_triangle(self):
        """Generate triangle wave table"""
        import array
        
        samples = array.array('h')
        quarter = self.WAVE_LENGTH // 4
        
        # Generate triangle in 4 parts for symmetry
        for i in range(quarter):  # Rising 0 to peak
            value = int(32767 * (i / quarter))
            samples.append(value)
            
        for i in range(quarter):  # Falling peak to 0
            value = int(32767 * (1 - i / quarter))
            samples.append(value)
            
        for i in range(quarter):  # Falling 0 to -peak
            value = int(-32767 * (i / quarter))
            samples.append(value)
            
        for i in range(quarter):  # Rising -peak to 0
            value = int(-32767 * (1 - i / quarter))
            samples.append(value)
            
        return samples

    def _generate_saw(self):
        """Generate sawtooth wave table"""
        import array
        
        samples = array.array('h')
        for i in range(self.WAVE_LENGTH):
            # Linear ramp from -32767 to +32767
            value = int(-32767 + (65534 * i / (self.WAVE_LENGTH - 1)))
            samples.append(value)
        return samples

    def cleanup(self):
        """Clear waveform cache"""
        self._waveforms.clear()

class FilterProcessor:
    """Handles filter routes and filter creation"""
    def __init__(self, engine):
        self.engine = engine
        self._filter_types = {
            'low_pass': synthio.FilterMode.LOW_PASS,
            'high_pass': synthio.FilterMode.HIGH_PASS,
            'band_pass': synthio.FilterMode.BAND_PASS,
            'notch': synthio.FilterMode.NOTCH
        }
        
    def process_route(self, parts, scope, value):
        """Process filter routes and store filter parameters"""
        try:
            if len(parts) < 3:
                _log(f"[ERROR] Invalid filter route format: {parts}")
                return
                
            filter_type = parts[0]
            param_type = parts[1]
            
            if filter_type not in self._filter_types:
                _log(f"[ERROR] Unknown filter type: {filter_type}")
                return
                
            # Build route path that includes filter type
            route_path = f"filter/{filter_type}/{param_type}"
            
            # Store the value
            try:
                float_value = float(value)
                self.engine.store_value(scope, route_path, float_value)
            except ValueError:
                _log(f"[ERROR] Invalid filter value: {value}")
                return
                
            _log(f"Processed filter route: {route_path} = {float_value}")
            
        except Exception as e:
            _log(f"[ERROR] Filter processing failed: {str(e)}")

    def create_filter(self, filter_type, frequency, resonance):
        """Create a filter instance with the given parameters"""
        try:
            mode = self._filter_types.get(filter_type)
            if not mode:
                return None
                
            # Create filter using BlockBiquad for dynamic parameters
            return synthio.BlockBiquad(
                mode=mode,
                frequency=frequency,
                Q=resonance
            )
        except Exception as e:
            _log(f"[ERROR] Filter creation failed: {str(e)}")
            return None

class AmplifierProcessor:
    """Handles amplifier envelope routes and envelope creation"""
    def __init__(self, engine):
        self.engine = engine
        self.required_params = {
            'attack_time',
            'decay_time', 
            'release_time',
            'attack_level',
            'sustain_level'
        }
        
    def process_route(self, parts, scope, value):
        """Process amplifier envelope routes"""
        try:
            if len(parts) < 3 or parts[0] != "envelope":
                _log(f"[ERROR] Invalid amplifier route format: {parts}")
                return
                
            param_name = parts[1]
            if param_name not in self.required_params:
                _log(f"[ERROR] Unknown envelope parameter: {param_name}")
                return
                
            # Build route path 
            route_path = f"amplifier/envelope/{param_name}"
            
            # Store the value
            try:
                float_value = float(value)
                self.engine.store_value(scope, route_path, float_value)
                _log(f"Processed envelope parameter: {route_path} = {float_value}")
            except ValueError:
                _log(f"[ERROR] Invalid envelope value: {value}")
                
        except Exception as e:
            _log(f"[ERROR] Amplifier envelope processing failed: {str(e)}")

    def create_envelope(self, params):
        """Create an envelope instance with the given parameters"""
        try:
            # Verify we have all required parameters
            if not all(param in params for param in self.required_params):
                return None
                
            return synthio.Envelope(
                attack_time=params['attack_time'],
                decay_time=params['decay_time'],
                release_time=params['release_time'],
                attack_level=params['attack_level'],
                sustain_level=params['sustain_level']
            )
        except Exception as e:
            _log(f"[ERROR] Envelope creation failed: {str(e)}")
            return None

class LfoProcessor:
    def __init__(self, engine):
        self.engine = engine

    def process_route(self, parts, scope, value):
        _log(f"[ERROR] No module for lfo/{parts[0]}")

class RouteManager:
    """Routes incoming messages to appropriate processor"""
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