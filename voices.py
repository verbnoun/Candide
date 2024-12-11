"""Voice pool management module."""

import array
import math
import time
from logging import log, TAG_VOICES

class VoicePool:
    """Manages voices that can be targeted by MIDI address."""
    def __init__(self, size=5):
        self.size = size
        self.voices = [Voice() for _ in range(size)]
        self.next_timestamp = 0
        self.channel_map = {}  # Maps channel -> voice for active voices
        self.base_amplitude = 1.0  # Base amplitude for notes
        
        # Pre-calculate amplitude scaling factors using 1/sqrt(n)
        # Create table for size+3 entries to handle potential voice stealing
        self.amplitude_scaling = array.array('f', [1.0])  # Start with 1.0 for 0 notes
        for i in range(1, size + 4):  # size+3 plus 1 since we start at 1
            self.amplitude_scaling.append(1.0 / math.sqrt(i))
        
        # Log the amplitude scaling table
        log(TAG_VOICES, "Amplitude scaling table:")
        for i, amp in enumerate(self.amplitude_scaling):
            log(TAG_VOICES, f"  {i} notes: {amp:.4f}")
        
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

    def get_amplitude_for_count(self, count):
        """Get amplitude scaling factor for given note count."""
        return self.amplitude_scaling[count]
        
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
        
        self._log_all_voices("after note-on")
        return voice
        
    def release_note(self, note_number):
        """Target a voice with note-off."""
        self._log_all_voices("before note-off")
        
        for voice in self.voices:
            if voice.note_number == note_number:
                if voice.channel in self.channel_map:
                    del self.channel_map[voice.channel]
                voice.clear()
                self._log_all_voices("after note-off")
                return voice
                
        return None
        
    def release_channel(self, channel):
        """Release voice on channel if any."""
        if channel in self.channel_map:
            voice = self.channel_map[channel]
            voice.clear()
            del self.channel_map[channel]
                
    def release_all(self):
        """Release all voices."""
        self._log_all_voices("before release-all")
        
        for voice in self.voices:
            voice.clear()
                
        self.next_timestamp = 0
        self.channel_map.clear()
        
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
