"""
modules.py - Synthesis Module Processors

Contains processor classes for handling different aspects of synthesis:
- Note processing
- Oscillator management
- Filter processing
- Amplifier/envelope control
- LFO functionality
"""
import sys
import array
import math
import synthio
from constants import SYNTH_DEBUG

def _log(message, module="SYNTH"):
    if not SYNTH_DEBUG:
        return
    BLUE = "\033[94m"
    RED = "\033[31m"
    RESET = "\033[0m"
    prefix = RED if "[ERROR]" in str(message) else BLUE
    print(f"{prefix}[{module}] {message}{RESET}", file=sys.stderr)

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
            # Handle release routes first
            if parts[0] == "release":
                voice = self.engine.active_voices.get(scope)
                if voice:
                    if voice.release():
                        _log(f"Successfully released voice {scope}")
                    else:
                        _log(f"[ERROR] Failed to release voice {scope}")
                return
                    
            # Handle press routes
            if parts[0] == "press":
                # Handle existing voice cases
                existing_voice = self.engine.active_voices.get(scope)
                if existing_voice:
                    if existing_voice.state == "active":
                        _log(f"Voice {scope} already active, ignoring press")
                        return
                    if existing_voice.state == "released":
                        _log(f"Removing released voice {scope} before new press")
                        del self.engine.active_voices[scope]
                    
                # Create new voice and store press route
                from synthesizer import Voice  # Import here to avoid circular import
                voice = Voice(scope, self.engine)
                if voice.state != "error":
                    self.engine.active_voices[scope] = voice
                    self.engine.store_value(scope, "note/press", True)
                else:
                    _log(f"[ERROR] Not adding voice {scope} due to initialization error")
                
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
        samples = array.array('h')
        for i in range(self.WAVE_LENGTH):
            # Scale sine wave to 16-bit signed range
            value = int(32767 * math.sin(2 * math.pi * i / self.WAVE_LENGTH))
            samples.append(value)
        return samples

    def _generate_square(self):
        """Generate square wave table"""
        samples = array.array('h')
        half_length = self.WAVE_LENGTH // 2
        samples.extend([32767] * half_length)  # First half full positive
        samples.extend([-32767] * (self.WAVE_LENGTH - half_length))  # Second half full negative
        return samples

    def _generate_triangle(self):
        """Generate triangle wave table"""
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

    def handle_route(self, route, timing_id=None):
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
