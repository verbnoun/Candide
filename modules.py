"""Low-level synthesis module."""

import array
import synthio
import math
import sys
import time
from constants import LOG_MODU, LOG_LIGHT_BLUE, LOG_RED, LOG_RESET, MODULES_LOG

def _log(message, is_error=False):
    if not MODULES_LOG:
        return
    color = LOG_RED if is_error else LOG_LIGHT_BLUE
    if is_error:
        print(f"{color}{LOG_MODU} {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{LOG_MODU} {message}{LOG_RESET}", file=sys.stderr)

def create_waveform(waveform_type):
    """Create a waveform buffer based on type."""
    samples = 100
    buffer = array.array('h')
    
    if waveform_type == 'sine':
        for i in range(samples):
            value = int(32767 * math.sin(2 * math.pi * i / samples))
            buffer.append(value)
    elif waveform_type == 'square':
        half_samples = samples // 2
        buffer.extend([32767] * half_samples)
        buffer.extend([-32767] * (samples - half_samples))
    elif waveform_type == 'saw':
        for i in range(samples):
            value = int(32767 * (2 * i / samples - 1))
            buffer.append(value)
    elif waveform_type == 'triangle':
        quarter_samples = samples // 4
        for i in range(samples):
            pos = (4 * i) / samples
            if pos < 1:
                value = pos
            elif pos < 3:
                value = 1 - (pos - 1)
            else:
                value = -1 + (pos - 3)
            buffer.append(int(32767 * value))
    else:
        raise ValueError(f"Invalid waveform type: {waveform_type}")
    
    return buffer

class Voice:
    """A voice that can be targeted by MIDI address."""
    def __init__(self):
        self.channel = None
        self.note_number = None
        self.active_note = None
        self.timestamp = 0
        
    def get_address(self):
        """Get voice's current address (note_number.channel)."""
        if self.note_number is not None and self.channel is not None:
            return f"{self.note_number}.{self.channel}"
        return None
        
    def _log_state(self, synth, action=""):
        """Log voice state showing note counts by state."""
        addr = self.get_address()
        if not addr:
            _log("Voice has no address")
            return
            
        # Get note states from synth
        active_count = 1 if self.active_note else 0
        releasing_count = 0
        
        if self.active_note:
            state, _ = synth.note_info(self.active_note)
            if state == synthio.EnvelopeState.RELEASE:
                active_count = 0
                releasing_count = 1
            
        if action:
            action = f" {action}"
            
        state = []
        if active_count > 0:
            state.append(f"{active_count} active")
        if releasing_count > 0:
            state.append(f"{releasing_count} releasing")
            
        _log(f"Voice {addr}{action}: has {', '.join(state) if state else 'no'} notes")
        
    def press_note(self, note_number, channel, synth, **note_params):
        """Target this voice with a note-on."""
        if self.active_note:
            synth.release(self.active_note)
            
        # Set new address
        self.note_number = note_number
        self.channel = channel
        
        # Create new active note
        self.active_note = synthio.Note(**note_params)
        synth.press(self.active_note)
        self._log_state(synth, "pressed")
        
    def release_note(self, synth):
        """Target this voice with a note-off."""
        if self.active_note:
            addr = self.get_address()
            synth.release(self.active_note)
            self._log_state(synth, "manually released")
            self.active_note = None
            self.note_number = None
            self.channel = None
            
    def steal_voice(self, synth):
        """Release voice during stealing."""
        if self.active_note:
            addr = self.get_address()
            synth.release(self.active_note)
            self._log_state(synth, "stolen")
            self.active_note = None
            self.note_number = None
            self.channel = None
            
    def update_active_note(self, synth, **params):
        """Update parameters of active note."""
        if self.active_note:
            for param, value in params.items():
                if hasattr(self.active_note, param):
                    setattr(self.active_note, param, value)
            self._log_state(synth, "changed")
            
    def is_active(self):
        """Check if voice has active note."""
        return self.active_note is not None

class VoicePool:
    """Manages voices that can be targeted by MIDI address."""
    def __init__(self, size=5):
        self.size = size
        self.voices = [Voice() for _ in range(size)]
        self.next_timestamp = 0
        self.channel_map = {}  # Maps channel -> voice for active voices
        _log(f"Voice pool initialized with {size} voices")
        
    def _get_voice(self, synth):
        """Get unused voice or steal oldest one."""
        # Try to find unused voice
        for voice in self.voices:
            if not voice.is_active():
                return voice
                
        # If no unused voices, steal oldest one
        oldest_voice = self.voices[0]
        oldest_timestamp = self.next_timestamp
        
        for voice in self.voices:
            if voice.timestamp < oldest_timestamp:
                oldest_voice = voice
                oldest_timestamp = voice.timestamp
                
        if oldest_voice.get_address():
            _log(f"Stealing voice {oldest_voice.get_address()}")
            oldest_voice.steal_voice(synth)
            
        return oldest_voice
        
    def press_note(self, note_number, channel, synth, **note_params):
        """Target a voice with note-on."""
        # Release any existing voice on this channel
        self.release_channel(channel, synth)
        
        # Get a voice
        voice = self._get_voice(synth)
        
        # If stealing a voice, remove its channel mapping
        if voice.channel in self.channel_map:
            del self.channel_map[voice.channel]
        
        # Press note in voice
        voice.press_note(note_number, channel, synth, **note_params)
        
        # Update timestamp and channel map
        voice.timestamp = self.next_timestamp
        self.next_timestamp += 1
        self.channel_map[channel] = voice
        
        return voice
        
    def release_note(self, note_number, synth):
        """Target a voice with note-off."""
        for voice in self.voices:
            if voice.note_number == note_number:
                voice.release_note(synth)
                if voice.channel in self.channel_map:
                    del self.channel_map[voice.channel]
                return voice
        return None
        
    def release_channel(self, channel, synth):
        """Release voice on channel if any."""
        if channel in self.channel_map:
            voice = self.channel_map[channel]
            voice.release_note(synth)
            del self.channel_map[channel]
                
    def release_all(self, synth):
        """Release all voices."""
        for voice in self.voices:
            if voice.is_active():
                voice.release_note(synth)
        self.next_timestamp = 0
        self.channel_map.clear()
        
    def get_voice_by_channel(self, channel):
        """Get voice targeted to channel."""
        return self.channel_map.get(channel)
        
    def check_health(self, synth):
        """Check voice pool health."""
        _log("Performing voice pool health check")
        
        # Log state of each voice
        active_count = 0
        for voice in self.voices:
            if voice.is_active():
                active_count += 1
                voice._log_state(synth)
                
        _log(f"Pool status: {active_count}/{self.size} voices active")
        _log(f"Channel map: {len(self.channel_map)} channels mapped")
