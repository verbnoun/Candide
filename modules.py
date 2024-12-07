"""Low-level synthesis module."""

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
        print("{}{} [ERROR] {}{}".format(color, LOG_MODU, message, LOG_RESET), file=sys.stderr)
    else:
        print("{}{} {}{}".format(color, LOG_MODU, message, LOG_RESET), file=sys.stderr)

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
        raise ValueError("Invalid waveform type: " + waveform_type)
    
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
            return "{}.{}".format(self.note_number, self.channel)
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
            action = " " + action
            
        state = []
        if active_count > 0:
            state.append("{} active".format(active_count))
        if releasing_count > 0:
            state.append("{} releasing".format(releasing_count))
            
        _log("Voice {}{}: has {}".format(
            addr,
            action,
            ", ".join(state) if state else "no notes"
        ))

    def _create_filter(self, synth, filter_type, frequency, resonance):
        """Create a filter based on type with current parameters."""
        if filter_type == 'low_pass':
            return synth.low_pass_filter(frequency, resonance)
        elif filter_type == 'high_pass':
            return synth.high_pass_filter(frequency, resonance)
        elif filter_type == 'band_pass':
            return synth.band_pass_filter(frequency, resonance)
        elif filter_type == 'notch':
            return synth.notch_filter(frequency, resonance)
        return None
        
    def press_note(self, note_number, channel, synth, **note_params):
        """Target this voice with a note-on."""
        if self.active_note:
            synth.release(self.active_note)
            
        # Set new address
        self.note_number = note_number
        self.channel = channel
        
        # Create filter if parameters provided
        if 'filter_type' in note_params and 'filter_frequency' in note_params and 'filter_resonance' in note_params:
            filter = self._create_filter(
                synth,
                note_params.pop('filter_type'),
                note_params.pop('filter_frequency'),
                note_params.pop('filter_resonance')
            )
            if filter:
                note_params['filter'] = filter
        
        # Create new active note
        self.active_note = synthio.Note(**note_params)
        synth.press(self.active_note)
        self._log_state(synth, "pressed")
        
    def release_note(self, synth, forced=False):
        """Target this voice with a note-off."""
        if self.active_note:
            addr = self.get_address()
            synth.release(self.active_note)
            action = "forced release" if forced else "released"
            self._log_state(synth, action)
            self.active_note = None
            self.note_number = None
            self.channel = None
            
    def steal_voice(self, synth):
        """Release voice during stealing."""
        if self.active_note:
            addr = self.get_address()
            synth.release(self.active_note)
            self._log_state(synth, "forced release")
            self.active_note = None
            self.note_number = None
            self.channel = None
            
    def update_active_note(self, synth, **params):
        """Update parameters of active note."""
        if self.active_note:
            # Handle filter updates
            if ('filter_type' in params and 'filter_frequency' in params and 
                'filter_resonance' in params):
                filter = self._create_filter(
                    synth,
                    params.pop('filter_type'),
                    params.pop('filter_frequency'),
                    params.pop('filter_resonance')
                )
                if filter:
                    params['filter'] = filter
            
            # Update note parameters
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
        
        # Toddler mode tracking
        self.last_steal_time = 0
        self.rapid_steal_count = 0
        self.toddler_mode = False
        self.toddler_start_time = 0  # When toddler mode started
        self.toddler_timeout = 0  # When toddler mode ends
        self.last_cleanup_time = 0  # Last time we cleaned up voices during timeout
        
        _log("Voice pool initialized with {} voices".format(size))
        
    def _check_toddler_trigger(self, synth, current_time, is_stealing=False):
        """Check if we should trigger toddler mode."""
        # If already in toddler mode, handle countdown and cleanup
        if self.toddler_mode:
            # Check if we need to do periodic cleanup
            if current_time - self.last_cleanup_time >= 1.0:  # Every second
                seconds_left = int(self.toddler_timeout - current_time)
                _log("Stop that! Timeout: {} seconds remaining...".format(seconds_left))
                self.release_all(synth)
                self.last_cleanup_time = current_time
                
            # Check if timeout is complete
            if current_time >= self.toddler_timeout:
                _log("Toddler timeout complete - behaving now")
                self.toddler_mode = False
                self.rapid_steal_count = 0
                self.release_all(synth)  # One final cleanup
            return self.toddler_mode
            
        # Only check for rapid steals when we're actually stealing
        if is_stealing:
            if current_time - self.last_steal_time < 0.1:  # 100ms between steals
                self.rapid_steal_count += 1
                if self.rapid_steal_count >= 3:  # 3 rapid steals triggers
                    _log("Stop that! Starting 3 second timeout...")
                    self.toddler_mode = True
                    self.toddler_start_time = current_time
                    self.toddler_timeout = current_time + 3.0  # 3 second timeout
                    self.last_cleanup_time = current_time
                    self.release_all(synth)  # Initial cleanup
                    return True
            else:
                self.rapid_steal_count = 1
                
            self.last_steal_time = current_time
            
        return False
        
    def _log_all_voices(self, synth, trigger=""):
        """Log the state of all voices."""
        _log("Voice pool state {}:".format(trigger))
        for i, voice in enumerate(self.voices):
            if voice.active_note:
                state, _ = synth.note_info(voice.active_note)
                addr = voice.get_address()
                _log("  Voice {}: {} {}".format(i, addr, state))
            else:
                _log("  Voice {}: inactive".format(i))
        
        # Log channel map
        channels = []
        for ch, v in self.channel_map.items():
            addr = v.get_address() if v else "None"
            channels.append("{} -> {}".format(ch, addr))
        _log("  Channels: {}".format(", ".join(channels) if channels else "none"))
        
    def _get_voice(self, synth):
        """Get unused voice or steal oldest one."""
        # Try to find unused voice
        for voice in self.voices:
            if not voice.is_active():
                return voice
                
        # If no unused voices, check for toddler mode before stealing
        current_time = time.monotonic()
        if self._check_toddler_trigger(synth, current_time, is_stealing=True):
            return None  # Don't allow new notes during toddler mode
                
        # If no unused voices and not in toddler mode, steal oldest one
        oldest_voice = self.voices[0]
        oldest_timestamp = self.next_timestamp
        
        for voice in self.voices:
            if voice.timestamp < oldest_timestamp:
                oldest_voice = voice
                oldest_timestamp = voice.timestamp
                
        if oldest_voice.get_address():
            _log("Stealing voice {}".format(oldest_voice.get_address()))
            oldest_voice.steal_voice(synth)
            
        return oldest_voice
        
    def press_note(self, note_number, channel, synth, **note_params):
        """Target a voice with note-on."""
        current_time = time.monotonic()
        
        # Check toddler mode status
        if self._check_toddler_trigger(synth, current_time):
            return None  # Don't allow new notes during toddler mode
            
        self._log_all_voices(synth, "before note-on")
        
        # Release any existing voice on this channel
        self.release_channel(channel, synth)
        
        # Get a voice
        voice = self._get_voice(synth)
        if voice is None:  # Could be None if we just entered toddler mode
            return None
            
        # Press note in voice
        voice.press_note(note_number, channel, synth, **note_params)
        
        # Update timestamp and channel map
        voice.timestamp = self.next_timestamp
        self.next_timestamp += 1
        self.channel_map[channel] = voice
        
        self._log_all_voices(synth, "after note-on")
        return voice
        
    def release_note(self, note_number, synth):
        """Target a voice with note-off."""
        self._log_all_voices(synth, "before note-off")
        
        for voice in self.voices:
            if voice.note_number == note_number:
                voice.release_note(synth, forced=False)
                if voice.channel in self.channel_map:
                    del self.channel_map[voice.channel]
                    
                self._log_all_voices(synth, "after note-off")
                return voice
                
        return None
        
    def release_channel(self, channel, synth):
        """Release voice on channel if any."""
        if channel in self.channel_map:
            voice = self.channel_map[channel]
            voice.release_note(synth, forced=True)
            del self.channel_map[channel]
                
    def release_all(self, synth):
        """Release all voices."""
        self._log_all_voices(synth, "before release-all")
        
        for voice in self.voices:
            if voice.is_active():
                voice.release_note(synth, forced=True)
                
        self.next_timestamp = 0
        self.channel_map.clear()
        
        self._log_all_voices(synth, "after release-all")
        
    def get_voice_by_channel(self, channel):
        """Get voice targeted to channel."""
        return self.channel_map.get(channel)
        
    def check_health(self, synth):
        """Check voice pool health."""
        _log("Performing voice pool health check")
        self._log_all_voices(synth)
