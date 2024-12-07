"""Low-level synthesis module.

This module provides the core sound generation and resource management functionality:
- Waveform generation and management 
- Voice pool and resource management
- Direct hardware interaction
- Core sound generation capabilities

This split separates the concerns of "how to make sound" (this file)
from "how to make sound" (modules.py).
"""

import array
import synthio
import math
import sys
import time
from constants import LOG_MODU, LOG_LIGHT_BLUE, LOG_RED, LOG_RESET, MODULES_LOG

def _log(message, is_error=False):
    """Enhanced logging with error support."""
    if not MODULES_LOG:
        return
        
    color = LOG_RED if is_error else LOG_LIGHT_BLUE
    if is_error:
        print(f"{color}{LOG_MODU} {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{LOG_MODU} {message}{LOG_RESET}", file=sys.stderr)

def create_waveform(waveform_type):
    """Create a waveform buffer based on type."""
    samples = 100  # Number of samples in waveform
    buffer = array.array('h')  # signed short array for samples
    
    if waveform_type == 'sine':
        # Sine wave: sin(2π * t)
        for i in range(samples):
            value = int(32767 * math.sin(2 * math.pi * i / samples))
            buffer.append(value)
            
    elif waveform_type == 'square':
        # Square wave: 50% duty cycle
        half_samples = samples // 2
        buffer.extend([32767] * half_samples)  # First half high
        buffer.extend([-32767] * (samples - half_samples))  # Second half low
            
    elif waveform_type == 'saw':
        # Sawtooth wave: linear ramp from -32767 to 32767
        for i in range(samples):
            value = int(32767 * (2 * i / samples - 1))
            buffer.append(value)
            
    elif waveform_type == 'triangle':
        # Triangle wave: linear ramp up then down
        quarter_samples = samples // 4
        for i in range(samples):
            # Normalize position in wave from 0 to 4 (representing quarters)
            pos = (4 * i) / samples
            if pos < 1:  # First quarter: ramp up from 0 to 1
                value = pos
            elif pos < 3:  # Middle half: ramp down from 1 to -1
                value = 1 - (pos - 1)
            else:  # Last quarter: ramp up from -1 to 0
                value = -1 + (pos - 3)
            buffer.append(int(32767 * value))
    
    else:
        raise ValueError("Invalid waveform type: " + waveform_type + ". Must be one of: sine, square, saw, triangle")
    
    return buffer

class Voice:
    """A voice that can contain one active synthio note and multiple releasing notes."""
    def __init__(self):
        """Initialize an empty voice."""
        self.channel = None  # MPE channel assigned to this voice
        self.note_number = None  # Current MIDI note number
        self.active_note = None  # Currently active synthio note
        self.timestamp = 0  # For FIFO voice allocation
        
    def _log_state(self):
        """Log current voice state."""
        if self.active_note:
            _log(f"Voice state: Active note {self.note_number}.{self.channel}")
        else:
            _log("Voice state: No active note")
        
    def press_note(self, note_number, channel, synth, **note_params):
        """Press a new note in this voice."""
        # Log voice stealing if applicable
        if self.active_note:
            _log(f"Stealing voice from {self.note_number}.{self.channel} for {note_number}.{channel}")
            synth.release(self.active_note)
            _log(f"Released note {self.note_number} during voice steal")
            
        # Create and press new note
        self.active_note = synthio.Note(**note_params)
        synth.press(self.active_note)
        
        # Update voice addressing
        self.note_number = note_number
        self.channel = channel
        
        self._log_state()
        
    def release_note(self, synth):
        """Release the currently active note."""
        if self.active_note:
            _log(f"Releasing note {self.note_number}.{self.channel}")
            synth.release(self.active_note)
            self.active_note = None
            self.note_number = None
            self.channel = None
            self._log_state()
            
    def update_active_note(self, **params):
        """Update parameters of the active note."""
        if self.active_note:
            for param, value in params.items():
                if hasattr(self.active_note, param):
                    setattr(self.active_note, param, value)
            _log(f"Updated note {self.note_number}.{self.channel} parameters: {params}")
            
    def is_active(self):
        """Check if this voice has an active note."""
        return self.active_note is not None

class VoicePool:
    """Manages a fixed pool of voices with MPE support."""
    def __init__(self, size=5):
        """Initialize voice pool with specified size."""
        self.size = size
        self.voices = [Voice() for _ in range(size)]
        self.next_timestamp = 0
        self.channel_map = {}  # Maps channel -> voice for active notes only
        _log(f"Voice pool initialized with {size} voices")
        
    def _get_voice(self):
        """Get an unused voice or steal the oldest one using FIFO."""
        # First try to find an unused voice
        for voice in self.voices:
            if not voice.is_active():
                return voice
                
        # If no unused voices, steal the oldest one (FIFO)
        oldest_voice = self.voices[0]
        oldest_timestamp = self.next_timestamp
        
        for voice in self.voices:
            if voice.timestamp < oldest_timestamp:
                oldest_voice = voice
                oldest_timestamp = voice.timestamp
                
        _log(f"Stealing oldest voice (age: {self.next_timestamp - oldest_timestamp})")
        return oldest_voice
        
    def press_note(self, note_number, channel, synth, **note_params):
        """Press a note using an available voice."""
        # First release any existing note on this channel
        self.release_channel(channel, synth)
        
        # Get a voice
        voice = self._get_voice()
        
        # If stealing a voice, remove its channel mapping
        if voice.channel in self.channel_map:
            del self.channel_map[voice.channel]
        
        # Press the note
        voice.press_note(note_number, channel, synth, **note_params)
        
        # Update timestamp and channel map
        voice.timestamp = self.next_timestamp
        self.next_timestamp += 1
        self.channel_map[channel] = voice
        
        return voice
        
    def release_note(self, note_number, synth):
        """Release a specific note."""
        for voice in self.voices:
            if voice.note_number == note_number:
                voice.release_note(synth)
                if voice.channel in self.channel_map:
                    del self.channel_map[voice.channel]
                return voice
        return None
        
    def release_channel(self, channel, synth):
        """Release all notes on a channel."""
        if channel in self.channel_map:
            voice = self.channel_map[channel]
            voice.release_note(synth)
            del self.channel_map[channel]
                
    def release_all(self, synth):
        """Release all active notes."""
        for voice in self.voices:
            voice.release_note(synth)
        self.next_timestamp = 0
        self.channel_map.clear()
        
    def get_voice_by_channel(self, channel):
        """Get the voice assigned to a channel."""
        return self.channel_map.get(channel)
        
    def check_health(self, synth):
        """Verify the health of the voice pool."""
        try:
            _log("Performing voice pool health check")
            
            # Count active voices and log their states
            active_voices = 0
            for voice in self.voices:
                if voice.is_active():
                    active_voices += 1
                    _log(f"Voice active: {voice.note_number}.{voice.channel}")
            
            # Log pool status
            _log(f"Pool status: {active_voices}/{self.size} voices active")
            _log(f"Channel map: {len(self.channel_map)} channels mapped")
            
        except Exception as e:
            _log(f"Error in health check: {str(e)}", is_error=True)
