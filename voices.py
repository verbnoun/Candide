"""Voice pool management module."""

import array
import math
import time
from logging import log, TAG_VOICES

class AmplitudeScaler:
    """Handles exponential amplitude scaling for polyphony protection.
    
    For n notes with individual amplitudes a₁, a₂, ..., aₙ, where each aᵢ is in [0,1],
    scales amplitude using the formula:
    S(a₁,...,aₙ) = aᵢ * e^(-k * ∑aⱼ)
    
    Where:
    - aᵢ is the individual note's amplitude
    - k is a compression factor (0.3)
    - ∑aⱼ is the sum of all current amplitudes
    
    This scaling:
    - Preserves relative amplitudes between notes
    - Prevents clipping/overload as n increases
    - Smoothly decreases with more notes
    - Never reaches 0
    """
    def __init__(self):
        self.k = 0.3  # Compression factor
        self.e_neg_k = math.exp(-self.k)  # Pre-calculate for efficiency
        self.sum_amplitudes = 0.0  # Running sum of amplitudes
        self.active_count = 0  # Number of active notes
        
        log(TAG_VOICES, "Amplitude scaler initialized:")
        log(TAG_VOICES, f"  Compression factor (k): {self.k}")
        log(TAG_VOICES, f"  Pre-calculated e^(-k): {self.e_neg_k:.4f}")
        
    def add_amplitude(self, amplitude):
        """Add a new amplitude to the sum."""
        self.sum_amplitudes += amplitude
        self.active_count += 1
        
        log(TAG_VOICES, "Amplitude scaling state after add:")
        log(TAG_VOICES, f"  Added raw amplitude: {amplitude:.4f}")
        log(TAG_VOICES, f"  Total amplitude: {self.sum_amplitudes:.4f}")
        log(TAG_VOICES, f"  Active notes: {self.active_count}")
        
        # Calculate scale using total amplitude
        scale = math.pow(self.e_neg_k, self.sum_amplitudes)
        scaled = amplitude * scale
        log(TAG_VOICES, f"  Scale factor: {scale:.4f}")
        log(TAG_VOICES, f"  Final amplitude: {scaled:.4f}")
            
    def remove_amplitude(self, amplitude):
        """Remove an amplitude from the sum."""
        self.sum_amplitudes -= amplitude
        self.active_count -= 1
        if self.active_count < 0:  # Safety check
            self.active_count = 0
            self.sum_amplitudes = 0.0
            
        log(TAG_VOICES, "Amplitude scaling state after remove:")
        log(TAG_VOICES, f"  Removed raw amplitude: {amplitude:.4f}")
        log(TAG_VOICES, f"  Total amplitude: {self.sum_amplitudes:.4f}")
        log(TAG_VOICES, f"  Active notes: {self.active_count}")
        if self.active_count > 0:
            # Calculate scale using total amplitude
            scale = math.pow(self.e_neg_k, self.sum_amplitudes)
            log(TAG_VOICES, f"  Scale factor: {scale:.4f}")
            log(TAG_VOICES, f"  Example scaled amplitudes:")
            for amp in [0.5, 1.0]:  # Show scaling for different amplitudes
                scaled = amp * scale
                log(TAG_VOICES, f"    {amp:.1f} -> {scaled:.4f}")
            
    def clear(self):
        """Reset amplitude tracking."""
        log(TAG_VOICES, "Cleared amplitude scaler:")
        log(TAG_VOICES, f"  Previous total: {self.sum_amplitudes:.4f}")
        log(TAG_VOICES, f"  Previous count: {self.active_count}")
        
        self.sum_amplitudes = 0.0
        self.active_count = 0
        
    def scale_amplitude(self, amplitude):
        """Scale an individual amplitude based on current state.
        
        Args:
            amplitude: The amplitude to scale
            
        Returns:
            Scaled amplitude value
        """
        if self.active_count == 0:
            log(TAG_VOICES, f"No active notes - using raw amplitude: {amplitude:.4f}")
            return amplitude
            
        # Calculate scale using total amplitude
        scale = math.pow(self.e_neg_k, self.sum_amplitudes)
        
        # Scale the individual amplitude
        final_amp = amplitude * scale
        
        log(TAG_VOICES, f"Scaling amplitude {amplitude:.4f}:")
        log(TAG_VOICES, f"  Active notes: {self.active_count}")
        log(TAG_VOICES, f"  Total amplitude: {self.sum_amplitudes:.4f}")
        log(TAG_VOICES, f"  Scale factor: {scale:.4f}")
        log(TAG_VOICES, f"  Final amplitude: {final_amp:.4f}")
        
        return final_amp

class VoicePool:
    """Manages voices that can be targeted by MIDI address."""
    def __init__(self, size=5):
        self.size = size
        self.voices = [Voice() for _ in range(size)]
        self.next_timestamp = 0
        self.channel_map = {}  # Maps channel -> voice for active voices
        self.base_amplitude = 1.0  # Base amplitude for notes
        self.amplitude_scaler = AmplitudeScaler()  # Handles amplitude scaling
        
        # Toddler mode tracking
        self.last_steal_time = 0
        self.rapid_steal_count = 0
        self.toddler_mode = False
        self.toddler_start_time = 0  # When toddler mode started
        self.toddler_timeout = 0  # When toddler mode ends
        self.last_cleanup_time = 0  # Last time we cleaned up voices during timeout
        
        log(TAG_VOICES, "Voice pool initialized with {} voices".format(size))

    def get_active_note_count(self):
        """Get count of currently active notes."""
        active_count = 0
        for voice in self.voices:
            if voice.is_active():
                active_count += 1
        return active_count

    def get_amplitude_for_count(self, amplitude):
        """Scale amplitude based on active voices."""
        return self.amplitude_scaler.scale_amplitude(amplitude)
        
    def for_each_active_voice(self, callback):
        """Execute callback for each active voice."""
        for voice in self.voices:
            if voice.is_active():
                callback(voice)
        
    def _check_toddler_trigger(self, current_time, is_stealing=False):
        """Check if we should trigger toddler mode."""
        # If already in toddler mode, handle countdown and cleanup
        if self.toddler_mode:
            # Check if we need to do periodic cleanup
            if current_time - self.last_cleanup_time >= 1.0:  # Every second
                seconds_left = int(self.toddler_timeout - current_time)
                log(TAG_VOICES, "Stop that! Timeout: {} seconds remaining...".format(seconds_left))
                self.last_cleanup_time = current_time
                return True  # Signal need for cleanup
                
            # Check if timeout is complete
            if current_time >= self.toddler_timeout:
                log(TAG_VOICES, "Toddler timeout complete - behaving now")
                self.toddler_mode = False
                self.rapid_steal_count = 0
                return True  # Signal final cleanup needed
            return False
            
        # Only check for rapid steals when we're actually stealing
        if is_stealing:
            if current_time - self.last_steal_time < 0.1:  # 100ms between steals
                self.rapid_steal_count += 1
                if self.rapid_steal_count >= 3:  # 3 rapid steals triggers
                    log(TAG_VOICES, "Stop that! Starting 3 second timeout...")
                    self.toddler_mode = True
                    self.toddler_start_time = current_time
                    self.toddler_timeout = current_time + 3.0  # 3 second timeout
                    self.last_cleanup_time = current_time
                    return True  # Signal initial cleanup needed
            else:
                self.rapid_steal_count = 1
                
            self.last_steal_time = current_time
            
        return False
        
    def _log_all_voices(self, trigger=""):
        """Log the state of all voices."""
        log(TAG_VOICES, "Voice pool state {}:".format(trigger))
        for i, voice in enumerate(self.voices):
            addr = voice.get_address()
            if addr:
                log(TAG_VOICES, "  Voice {}: {}".format(i, addr))
                if voice.active_note:
                    raw_amp = voice.active_note.amplitude
                    log(TAG_VOICES, f"    Raw amplitude: {raw_amp:.4f}")
                    scaled = self.amplitude_scaler.scale_amplitude(raw_amp)
                    log(TAG_VOICES, f"    Scaled amplitude: {scaled:.4f}")
            else:
                log(TAG_VOICES, "  Voice {}: inactive".format(i))
        
        # Log channel map
        channels = []
        for ch, v in self.channel_map.items():
            addr = v.get_address() if v else "None"
            channels.append("{} -> {}".format(ch, addr))
        log(TAG_VOICES, "  Channels: {}".format(", ".join(channels) if channels else "none"))
        
    def _get_voice(self):
        """Get unused voice or steal oldest one."""
        # Try to find unused voice
        for voice in self.voices:
            if not voice.is_active():
                return voice
                
        # If no unused voices, check for toddler mode before stealing
        current_time = time.monotonic()
        if self._check_toddler_trigger(current_time, is_stealing=True):
            return None  # Don't allow new notes during toddler mode
                
        # If no unused voices and not in toddler mode, steal oldest one
        oldest_voice = self.voices[0]
        oldest_timestamp = self.next_timestamp
        
        for voice in self.voices:
            if voice.timestamp < oldest_timestamp:
                oldest_voice = voice
                oldest_timestamp = voice.timestamp
                
        if oldest_voice.get_address():
            log(TAG_VOICES, "Stealing voice {}".format(oldest_voice.get_address()))
            
        # Remove stolen voice's amplitude from scaler
        if oldest_voice.active_note:
            self.amplitude_scaler.remove_amplitude(oldest_voice.active_note.amplitude)
            
        return oldest_voice
        
    def press_note(self, note_number, channel):
        """Target a voice with note-on."""
        current_time = time.monotonic()
        
        # Check toddler mode status
        if self._check_toddler_trigger(current_time):
            return None  # Don't allow new notes during toddler mode
            
        self._log_all_voices("before note-on")
        
        # Release any existing voice on this channel
        self.release_channel(channel)
        
        # Get a voice
        voice = self._get_voice()
        if voice is None:  # Could be None if we just entered toddler mode
            return None
            
        # Set up voice
        voice.note_number = note_number
        voice.channel = channel
        voice.timestamp = self.next_timestamp
        self.next_timestamp += 1
        self.channel_map[channel] = voice
        
        # Return voice - amplitude will be added after note is created
        self._log_all_voices("after note-on")
        return voice
        
    def add_note_amplitude(self, voice):
        """Add a note's amplitude to the scaler after it's created."""
        if voice and voice.active_note:
            self.amplitude_scaler.add_amplitude(voice.active_note.amplitude)
        
    def release_note(self, note_number):
        """Target a voice with note-off."""
        self._log_all_voices("before note-off")
        
        for voice in self.voices:
            if voice.note_number == note_number:
                if voice.channel in self.channel_map:
                    del self.channel_map[voice.channel]
                # Remove voice's amplitude from scaler before clearing
                if voice.active_note:
                    self.amplitude_scaler.remove_amplitude(voice.active_note.amplitude)
                voice.clear()
                self._log_all_voices("after note-off")
                return voice
                
        return None
        
    def release_channel(self, channel):
        """Release voice on channel if any."""
        if channel in self.channel_map:
            voice = self.channel_map[channel]
            # Remove voice's amplitude from scaler before clearing
            if voice.active_note:
                self.amplitude_scaler.remove_amplitude(voice.active_note.amplitude)
            voice.clear()
            del self.channel_map[channel]
                
    def release_all(self):
        """Release all voices."""
        self._log_all_voices("before release-all")
        
        for voice in self.voices:
            voice.clear()
                
        self.next_timestamp = 0
        self.channel_map.clear()
        self.amplitude_scaler.clear()  # Reset amplitude tracking
        
        self._log_all_voices("after release-all")
        
    def get_voice_by_channel(self, channel):
        """Get voice targeted to channel."""
        return self.channel_map.get(channel)
        
    def check_health(self):
        """Check voice pool health."""
        log(TAG_VOICES, "Performing voice pool health check")
        self._log_all_voices()

class Voice:
    """A voice that can be targeted by MIDI address."""
    def __init__(self):
        self.channel = None
        self.note_number = None
        self.active_note = None  # Set by synthesizer
        self.timestamp = 0
        
    def get_address(self):
        """Get voice's current address (note_number.channel)."""
        if self.note_number is not None and self.channel is not None:
            return "{}.{}".format(self.note_number, self.channel)
        return None
        
    def clear(self):
        """Clear voice state."""
        self.channel = None
        self.note_number = None
        self.active_note = None
            
    def is_active(self):
        """Check if voice is active."""
        return self.note_number is not None
