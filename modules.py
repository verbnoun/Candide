"""Low-level synthesis module."""

import array
import synthio
import math
import sys
import time
from constants import (
    LOG_MODU, LOG_LIGHT_BLUE, LOG_RED, LOG_RESET, MODULES_LOG,
    STATIC_WAVEFORM_SAMPLES, MORPHED_WAVEFORM_SAMPLES
)

def _log(message, is_error=False):
    """Enhanced logging with error support."""
    if not MODULES_LOG:
        return
    color = LOG_RED if is_error else LOG_LIGHT_BLUE
    if is_error:
        print("{}{} [ERROR] {}{}".format(color, LOG_MODU, message, LOG_RESET), file=sys.stderr)
    else:
        print("{}{} {}{}".format(color, LOG_MODU, message, LOG_RESET), file=sys.stderr)

# Cache for pre-computed waveforms
_waveform_cache = {}
_morphed_waveform_cache = {}  # Cache for morphed waveforms

def get_cached_waveform(waveform_type):
    """Get or create a waveform from cache."""
    if waveform_type not in _waveform_cache:
        _waveform_cache[waveform_type] = create_waveform(waveform_type)
        _log(f"Created and cached {waveform_type} waveform")
    return _waveform_cache[waveform_type]

def create_waveform(waveform_type):
    """Create a waveform buffer based on type."""
    samples = STATIC_WAVEFORM_SAMPLES
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

class WaveformMorph:
    """Handles pre-calculated morphed waveforms for MIDI control."""
    def __init__(self, name, waveform_sequence=None):
        self.name = name
        self.waveform_sequence = waveform_sequence or ['sine', 'triangle', 'square', 'saw']
        self.lookup_table = []  # Will be 128 morphed waveforms
        self._build_lookup()
        _log(f"Created waveform morph: {name} sequence: {'-'.join(self.waveform_sequence)}")
        
    def _build_lookup(self):
        """Build lookup table of 128 morphed waveforms for MIDI control."""
        cache_key = '-'.join(self.waveform_sequence)
        if cache_key in _morphed_waveform_cache:
            self.lookup_table = _morphed_waveform_cache[cache_key]
            _log(f"Using cached morph table for {cache_key}")
            return
            
        # Get sample length from first waveform
        first_wave = get_cached_waveform(self.waveform_sequence[0])
        samples = MORPHED_WAVEFORM_SAMPLES
        
        # Pre-calculate all possible morphed waveforms
        num_transitions = len(self.waveform_sequence) - 1
        
        # Log sample values for debugging
        _log(f"Building morph table for {self.name}:")
        _log(f"  0: {self.waveform_sequence[0]}")
        _log(f" 64: Between {self.waveform_sequence[len(self.waveform_sequence)//2-1]} and {self.waveform_sequence[len(self.waveform_sequence)//2]}")
        _log(f"127: {self.waveform_sequence[-1]}")
        
        # Create array to hold all morphed waveforms
        self.lookup_table = []
        
        for midi_value in range(128):
            # Convert MIDI value to morph position
            morph_position = midi_value / 127.0
            
            # Scale position to total number of transitions
            scaled_pos = morph_position * num_transitions
            transition_index = int(scaled_pos)
            
            # Clamp to valid range
            if transition_index >= num_transitions:
                self.lookup_table.append(get_cached_waveform(self.waveform_sequence[-1]))
                continue
                
            # Get the two waveforms to blend
            waveform1 = get_cached_waveform(self.waveform_sequence[transition_index])
            waveform2 = get_cached_waveform(self.waveform_sequence[transition_index + 1])
            
            # Calculate blend amount within this transition
            t = scaled_pos - transition_index
            
            # Create morphed buffer
            morphed = array.array('h')
            for i in range(samples):
                # Scale indices for potentially different sample counts
                idx1 = (i * len(waveform1)) // samples
                idx2 = (i * len(waveform2)) // samples
                value = int(waveform1[idx1] * (1-t) + waveform2[idx2] * t)
                morphed.append(value)
                
            self.lookup_table.append(morphed)
            
        # Cache the computed morph table
        _morphed_waveform_cache[cache_key] = self.lookup_table
        _log(f"Cached morph table for {cache_key}")
    
    def get_waveform(self, midi_value):
        """Get pre-calculated morphed waveform for MIDI value."""
        if not 0 <= midi_value <= 127:
            _log(f"Invalid MIDI value {midi_value} for {self.name}", is_error=True)
            raise ValueError(f"MIDI value must be between 0 and 127, got {midi_value}")
        return self.lookup_table[midi_value]

def create_morphed_waveform(morph_position, waveform_sequence=None):
    """
    Create a morphed waveform based on position and sequence.
    
    Args:
        morph_position: Value 0-1 representing position in morph sequence
        waveform_sequence: List of waveform types to morph between.
                         Defaults to ['sine', 'triangle', 'square', 'saw']
    """
    if waveform_sequence is None:
        waveform_sequence = ['sine', 'triangle', 'square', 'saw']
    
    # Calculate which waveforms to blend between
    num_transitions = len(waveform_sequence) - 1
    if num_transitions == 0:
        return get_cached_waveform(waveform_sequence[0])
        
    # Scale position to total number of transitions
    scaled_pos = morph_position * num_transitions
    transition_index = int(scaled_pos)
    
    # Clamp to valid range
    if transition_index >= num_transitions:
        return get_cached_waveform(waveform_sequence[-1])
    
    # Get the two waveforms to blend
    waveform1 = get_cached_waveform(waveform_sequence[transition_index])
    waveform2 = get_cached_waveform(waveform_sequence[transition_index + 1])
    
    # Calculate blend amount within this transition
    t = scaled_pos - transition_index
    
    # Create morphed buffer
    samples = MORPHED_WAVEFORM_SAMPLES
    morphed = array.array('h')
    for i in range(samples):
        # Scale indices for potentially different sample counts
        idx1 = (i * len(waveform1)) // samples
        idx2 = (i * len(waveform2)) // samples
        value = int(waveform1[idx1] * (1-t) + waveform2[idx2] * t)
        morphed.append(value)
    
    _log(f"Created morphed waveform at position {morph_position} between {waveform_sequence[transition_index]} and {waveform_sequence[transition_index + 1]}")
    return morphed

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
        
        # Ensure amplitude is set
        if 'amplitude' not in note_params:
            note_params['amplitude'] = 1.0
            
        # Create new active note - will use synth's global envelope
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
            
            # Update note parameters including ring modulation
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
        self.base_amplitude = 1.0  # Base amplitude for notes
        
        # Pre-calculate amplitude scaling factors using 1/sqrt(n)
        # Create table for size+3 entries to handle potential voice stealing
        self.amplitude_scaling = array.array('f', [1.0])  # Start with 1.0 for 0 notes
        for i in range(1, size + 4):  # size+3 plus 1 since we start at 1
            self.amplitude_scaling.append(1.0 / math.sqrt(i))
        
        # Log the amplitude scaling table
        _log("Amplitude scaling table:")
        for i, amp in enumerate(self.amplitude_scaling):
            _log(f"  {i} notes: {amp:.4f}")
        
        # Toddler mode tracking
        self.last_steal_time = 0
        self.rapid_steal_count = 0
        self.toddler_mode = False
        self.toddler_start_time = 0  # When toddler mode started
        self.toddler_timeout = 0  # When toddler mode ends
        self.last_cleanup_time = 0  # Last time we cleaned up voices during timeout
        
        _log("Voice pool initialized with {} voices".format(size))

    def get_active_note_count(self, synth):
        """Get count of currently active notes (not including releasing notes)."""
        active_count = 0
        for voice in self.voices:
            if voice.active_note:
                state, _ = synth.note_info(voice.active_note)
                if state in (synthio.EnvelopeState.ATTACK, 
                           synthio.EnvelopeState.DECAY,
                           synthio.EnvelopeState.SUSTAIN):
                    active_count += 1
        return active_count

    def update_all_note_amplitudes(self, synth):
        """Update amplitudes of all active notes based on count."""
        active_count = self.get_active_note_count(synth)
        if active_count == 0:
            return

        # Get pre-calculated amplitude for this number of notes
        new_amplitude = self.amplitude_scaling[active_count]
        _log("Adjusting amplitudes: {} active notes, new amplitude: {:.4f}".format(
            active_count, new_amplitude))

        # Update all active notes
        for voice in self.voices:
            if voice.active_note:
                state, _ = synth.note_info(voice.active_note)
                if state in (synthio.EnvelopeState.ATTACK, 
                           synthio.EnvelopeState.DECAY,
                           synthio.EnvelopeState.SUSTAIN):
                    voice.update_active_note(synth, amplitude=new_amplitude)
        
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
            
        # Calculate initial amplitude based on current active notes + 1 (for this new note)
        active_count = self.get_active_note_count(synth) + 1
        note_params['amplitude'] = self.amplitude_scaling[active_count]
        
        # Press note in voice
        voice.press_note(note_number, channel, synth, **note_params)
        
        # Update timestamp and channel map
        voice.timestamp = self.next_timestamp
        self.next_timestamp += 1
        self.channel_map[channel] = voice
        
        # Update all note amplitudes after adding new note
        self.update_all_note_amplitudes(synth)
        
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
                    
                # Update all note amplitudes after releasing note
                self.update_all_note_amplitudes(synth)
                    
                self._log_all_voices(synth, "after note-off")
                return voice
                
        return None
        
    def release_channel(self, channel, synth):
        """Release voice on channel if any."""
        if channel in self.channel_map:
            voice = self.channel_map[channel]
            voice.release_note(synth, forced=True)
            del self.channel_map[channel]
            
            # Update all note amplitudes after releasing note
            self.update_all_note_amplitudes(synth)
                
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
