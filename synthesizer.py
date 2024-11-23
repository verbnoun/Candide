"""
Synthesis Module

Handles parameter manipulation and waveform generation for synthio notes.
Provides calculations needed by voice modules to control synthesis.
"""
import sys
import array
import math
import time
import synthio
from constants import SYNTH_DEBUG

def _log(message, module="SYNTH"):
    """Enhanced logging for synthesis operations"""
    if not SYNTH_DEBUG:
        return
        
    GREEN = "\033[32m"  # Green for synthesis operations
    RED = "\033[31m"    # Red for errors
    RESET = "\033[0m"
    
    color = RED if "[ERROR]" in str(message) else GREEN
    print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class Timer:
    """Modular timer for synthesis timing needs"""
    def __init__(self, name, initial_time=None):
        self.name = name
        self.time_value = initial_time
        self.start_time = None
        self.active = False
        self.end_callbacks = []  # Callbacks to run when timer ends
        _log(f"Timer created: {name}")
        
    def start(self):
        """Start or restart timer"""
        if self.time_value is None:
            _log(f"[ERROR] Timer {self.name} has no duration set")
            return False
            
        self.start_time = time.monotonic()
        self.active = True
        _log(f"Timer {self.name} started: duration={self.time_value}")
        return True
        
    def update_time(self, new_time):
        """Update timer duration
        
        If timer is running, adjusts the start time to maintain relative progress
        """
        if not self.active:
            self.time_value = new_time
            _log(f"Timer {self.name} duration updated: {new_time}")
            return
            
        # Calculate progress through current duration
        elapsed = time.monotonic() - self.start_time
        if elapsed < self.time_value:
            # Still running, adjust start time to maintain relative progress
            progress = elapsed / self.time_value
            self.time_value = new_time
            self.start_time = time.monotonic() - (progress * new_time)
        else:
            # Original duration elapsed, start fresh
            self.time_value = new_time
            self.start()
        _log(f"Timer {self.name} duration updated: {new_time}")
        
    def check(self):
        """Check if timer has elapsed
        
        Returns:
            bool: True if timer is active and has elapsed, False otherwise
        """
        if not self.active:
            return False
            
        if time.monotonic() - self.start_time >= self.time_value:
            self.active = False
            # Run end callbacks
            for callback in self.end_callbacks:
                callback(self.name)
            _log(f"Timer {self.name} elapsed")
            return True
            
        return False
        
    def stop(self):
        """Stop timer"""
        self.active = False
        self.start_time = None
        _log(f"Timer {self.name} stopped")
        
    def is_active(self):
        """Check if timer is currently running"""
        return self.active
        
    def add_end_callback(self, callback):
        """Add callback to run when timer ends
        
        Args:
            callback: Function to call with timer name when timer ends
        """
        self.end_callbacks.append(callback)

class TimerManager:
    """Manages collection of timers for synthesis"""
    def __init__(self):
        self.timers = {}
        _log("Timer manager initialized")
        
    def create_timer(self, name, initial_time=None):
        """Create a new timer
        
        Args:
            name: Unique identifier for timer
            initial_time: Optional initial duration
            
        Returns:
            Timer: The created timer
        """
        timer = Timer(name, initial_time)
        self.timers[name] = timer
        return timer
        
    def get_timer(self, name):
        """Get existing timer or create new one"""
        return self.timers.get(name)
        
    def update_timer(self, name, time_value):
        """Update timer duration, creating if needed"""
        timer = self.timers.get(name)
        if timer:
            timer.update_time(time_value)
        else:
            timer = self.create_timer(name, time_value)
        return timer
        
    def check_timers(self):
        """Check all timers and return elapsed ones
        
        Returns:
            list: Names of timers that have elapsed
        """
        elapsed = []
        for name, timer in self.timers.items():
            if timer.check():
                elapsed.append(name)
        return elapsed
        
    def stop_timer(self, name):
        """Stop a specific timer"""
        timer = self.timers.get(name)
        if timer:
            timer.stop()
            
    def cleanup(self):
        """Stop all timers"""
        for timer in self.timers.values():
            timer.stop()
        self.timers.clear()

class WaveformManager:
    """Creates and manages waveforms for synthesis"""
    def __init__(self):
        self.waveforms = {}
        _log("WaveformManager initialized")
        
    def create_triangle_wave(self, config):
        """Create triangle waveform from configuration"""
        try:
            size = int(config['size'])  # Ensure size is an integer
            amplitude = int(config['amplitude'])  # Ensure amplitude is an integer
            
            # Use double quotes for typecode in CircuitPython
            samples = array.array("h", [0] * size)
            half = size // 2
            
            # Generate triangle wave with explicit integer conversion
            for i in range(size):
                if i < half:
                    value = (i / half) * 2 - 1
                else:
                    value = 1 - ((i - half) / half) * 2
                # Ensure integer conversion for array values
                samples[i] = int(round(value * amplitude))
                    
            _log(f"Created triangle wave: size={size}, amplitude={amplitude}")
            return samples
            
        except Exception as e:
            _log(f"[ERROR] Failed to create waveform: {str(e)}")
            return None
            
    def get_waveform(self, wave_type, config=None):
        """Get or create waveform by type"""
        try:
            if not config:
                _log("[ERROR] No configuration provided for waveform")
                return None
                
            cache_key = f"{wave_type}_{config.get('size', 0)}"
            
            if cache_key in self.waveforms:
                _log(f"Retrieved cached waveform: {cache_key}")
                return self.waveforms[cache_key]
                
            if wave_type == 'triangle':
                waveform = self.create_triangle_wave(config)
                if waveform:
                    self.waveforms[cache_key] = waveform
                    _log(f"Created and cached triangle waveform: size={config['size']}")
                    return waveform
                    
            _log(f"[ERROR] Failed to get/create waveform: {wave_type}")
            return None
        except Exception as e:
            _log(f"[ERROR] Failed in get_waveform: {str(e)}")
            return None

class Synthesis:
    """Core synthesis parameter processing"""
    def __init__(self, synthio_synth=None):
        self.waveform_manager = WaveformManager()
        self.timer_manager = TimerManager()
        self.synthio_synth = synthio_synth
        _log("Synthesis engine initialized")
            
    def create_note(self, frequency, envelope_params=None):
        """Create a synthio note with the given frequency and envelope parameters
        
        Args:
            frequency: Base frequency in Hz
            envelope_params: Dictionary of envelope parameters
            
        Returns:
            synthio.Note: The created note
        """
        try:
            # Create envelope if parameters provided
            envelope = None
            if envelope_params:
                envelope = synthio.Envelope(
                    attack_time=max(0.001, float(envelope_params.get('attack_time', 0.001))),
                    attack_level=float(envelope_params.get('attack_level', 1.0)),
                    decay_time=max(0.001, float(envelope_params.get('decay_time', 0.001))),
                    sustain_level=float(envelope_params.get('sustain_level', 0.0)),
                    release_time=max(0.001, float(envelope_params.get('release_time', 0.001)))
                )
                _log(f"Created envelope with params: {envelope_params}")
            
            # Create note with envelope
            note = synthio.Note(
                frequency=float(frequency),
                envelope=envelope
            )
            _log(f"Created note with frequency {frequency}")
            return note
            
        except Exception as e:
            _log(f"[ERROR] Failed to create note: {str(e)}")
            return None

    def update_note(self, note, param_id, value):
        """Update synthio note parameter
        
        Args:
            note: synthio.Note instance
            param_id: Parameter identifier (frequency, amplitude, etc)
            value: New parameter value (pre-normalized by router)
            
        Returns:
            bool: True if parameter was updated successfully
        """
        if not note:
            _log("[ERROR] No note provided for update")
            return False
            
        try:
            _log(f"Updating note parameter: {param_id}={value}")
            
            # Handle basic parameters
            if param_id == 'frequency':
                note.frequency = float(value)
                _log(f"Set frequency: {value}")
                return True
                
            elif param_id == 'amplitude':
                note.amplitude = float(value)
                _log(f"Set amplitude: {value}")
                return True
                
            elif param_id == 'bend':
                note.bend = float(value)
                _log(f"Set bend: {value}")
                return True
                
            elif param_id == 'waveform':
                try:
                    # If value is already a waveform array, use it directly
                    if isinstance(value, array.array):
                        note.waveform = value
                        _log("Set waveform from array")
                        return True
                        
                    # Otherwise, expect a configuration dictionary
                    if not isinstance(value, dict):
                        _log("[ERROR] Expected waveform configuration dictionary")
                        return False
                        
                    wave_type = value.get('type')
                    if not wave_type:
                        _log("[ERROR] No waveform type specified")
                        return False
                        
                    # Create waveform using waveform_manager
                    waveform = self.waveform_manager.get_waveform(wave_type, value)
                    if waveform and isinstance(waveform, array.array):
                        note.waveform = waveform
                        _log(f"Set waveform: type={wave_type}")
                        return True
                        
                    _log("[ERROR] Invalid waveform generated")
                    return False
                except Exception as e:
                    _log(f"[ERROR] Failed to set waveform: {str(e)}")
                    return False
                    
            # Handle envelope parameters
            elif param_id.startswith('envelope_'):
                try:
                    # Get current envelope parameters
                    current_envelope = note.envelope
                    if not current_envelope:
                        _log("[ERROR] Note has no envelope")
                        return False
                        
                    # Get current parameter values
                    params = {
                        'attack_time': current_envelope.attack_time,
                        'attack_level': current_envelope.attack_level,
                        'decay_time': current_envelope.decay_time,
                        'sustain_level': current_envelope.sustain_level,
                        'release_time': current_envelope.release_time
                    }
                    
                    # Update specific parameter
                    param_name = param_id.split('envelope_')[1]
                    params[param_name] = max(0.001, float(value)) if 'time' in param_name else float(value)
                    
                    # Create new envelope with updated parameters
                    note.envelope = synthio.Envelope(**params)
                    _log(f"Updated envelope {param_name}: {value}")
                    return True
                    
                except Exception as e:
                    _log(f"[ERROR] Failed to update envelope: {str(e)}")
                    return False
                    
            # Handle filter parameters
            elif param_id.startswith('filter_'):
                if not self.synthio_synth:
                    _log("[ERROR] No synthesizer available for filter creation")
                    return False
                    
                current_filter = getattr(note, 'filter', None)
                current_freq = getattr(current_filter, 'frequency', 20000)
                current_q = getattr(current_filter, 'Q', 0.707)
                
                if param_id == 'filter_frequency':
                    note.filter = self.synthio_synth.low_pass_filter(
                        frequency=float(value),
                        Q=current_q
                    )
                    _log(f"Updated filter frequency: {value}")
                    return True
                    
                elif param_id == 'filter_resonance':
                    note.filter = self.synthio_synth.low_pass_filter(
                        frequency=current_freq,
                        Q=float(value)
                    )
                    _log(f"Updated filter resonance: {value}")
                    return True
                    
            # Handle timer updates
            elif param_id.startswith('timer_'):
                stage = param_id.split('timer_')[1]
                timer_name = f"{id(note)}_{param_id}"
                self.timer_manager.update_timer(timer_name, float(value))
                _log(f"Updated timer {timer_name}: {value}")
                return True
                    
            _log(f"[ERROR] Unhandled parameter: {param_id}")
            return False
            
        except Exception as e:
            _log(f"[ERROR] Failed to update {param_id}: {str(e)}")
            return False
            
    def check_timers(self):
        """Check all timers and return elapsed ones
        
        Returns:
            list: Names of timers that have elapsed
        """
        return self.timer_manager.check_timers()
        
    def cleanup_note(self, note):
        """Clean up timers for a note"""
        note_id = id(note)
        # Stop any timers associated with this note
        for timer_name in list(self.timer_manager.timers.keys()):
            if timer_name.startswith(f"{note_id}_"):
                self.timer_manager.stop_timer(timer_name)
