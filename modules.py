"""Low-level synthesis module.

This module provides the core sound generation and resource management functionality:
- Waveform generation and management
- Note pool and resource management
- Direct hardware interaction
- Core sound generation capabilities

This split separates the concerns of "how to make sound" (this file)
from "what sound to make" (synthesizer.py).
"""

import array
import synthio
import math
import sys
from constants import LOG_SYNTH, LOG_LIGHT_GREEN, LOG_RED, LOG_RESET

def _log(message, is_error=False, is_debug=False):
    """Enhanced logging with error and debug support."""
    color = LOG_RED if is_error else LOG_LIGHT_GREEN
    if is_error:
        print("{}{}".format(color, LOG_SYNTH) + (" [ERROR] " if is_error else " ") + message + LOG_RESET, file=sys.stderr)
    else:
        print("{}{}".format(color, LOG_SYNTH) + " " + message + LOG_RESET, file=sys.stderr)

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

class NotePool:
    """Manages a fixed pool of pre-allocated notes with MPE support and robust FIFO note stealing."""
    def __init__(self, size=5):
        """Initialize note pool with specified size."""
        self.size = size
        self.notes = [None] * size  # Array of synthio.Note objects
        self.note_nums = [None] * size  # Array of MIDI note numbers
        self.channels = [None] * size  # Array of MIDI channels
        self.timestamps = [0] * size  # Array of timestamps
        self.next_timestamp = 0  # Monotonic counter for age tracking
        
        # Ready note for immediate replacement
        self.ready_note = None
        self.ready_note_freq = None
        
        # Compatibility properties
        self.channel_notes = {}  # channel -> (note_num, index) mapping
        
        _log("Note pool initialized with size " + str(size))

    def _prepare_ready_note(self, freq):
        """Prepare a ready note at a specific frequency."""
        try:
            self.ready_note = synthio.Note(frequency=freq)
            self.ready_note_freq = freq
            _log("Prepared ready note at frequency " + str(freq))
        except Exception as e:
            _log("Error preparing ready note: " + str(e), is_error=True)

    def _get_slot_index(self):
        """Find first empty slot or oldest used slot."""
        oldest_index = 0
        oldest_timestamp = self.next_timestamp
        
        # First try to find an empty slot
        for i in range(self.size):
            if self.notes[i] is None:
                return i
            if self.timestamps[i] < oldest_timestamp:
                oldest_index = i
                oldest_timestamp = self.timestamps[i]
        
        # If no empty slot, use the oldest one
        return oldest_index

    def _release_slot(self, index, synth):
        """Release a note slot."""
        if self.notes[index] is not None:
            if synth:
                _log("Releasing note " + str(self.note_nums[index]) + " from channel " + str(self.channels[index]))
                synth.release(self.notes[index])
            
            # Remove from channel mapping
            if self.channels[index] in self.channel_notes:
                del self.channel_notes[self.channels[index]]
            
            # Clear slot
            self.notes[index] = None
            self.note_nums[index] = None
            self.channels[index] = None

    def get_note(self, note_num, channel, synth=None):
        """Get a note slot, stealing if necessary."""
        try:
            freq = synthio.midi_to_hz(note_num)
            
            # First release any existing note on this channel
            if channel in self.channel_notes:
                old_note_num, old_index = self.channel_notes[channel]
                self._release_slot(old_index, synth)
            
            # Get an empty or oldest slot
            index = self._get_slot_index()
            
            # If slot was in use, we'll need note stealing
            if self.notes[index] is not None:
                _log("Stealing slot " + str(index) + " from note " + str(self.note_nums[index]) + " for new note " + str(note_num))
                
                # If we have a ready note at the correct frequency, use it
                if self.ready_note and self.ready_note_freq == freq:
                    note = self.ready_note
                    self.ready_note = None
                    self.ready_note_freq = None
                else:
                    # Create new note since ready note wasn't suitable
                    note = synthio.Note(frequency=freq)
                
                # Release the old note
                self._release_slot(index, synth)
                
                # Prepare a new ready note for next time
                self._prepare_ready_note(freq)
            else:
                # No stealing needed, just create a new note
                note = synthio.Note(frequency=freq)
            
            # Update slot
            self.notes[index] = note
            self.note_nums[index] = note_num
            self.channels[index] = channel
            self.timestamps[index] = self.next_timestamp
            self.next_timestamp += 1
            
            # Update channel mapping
            self.channel_notes[channel] = (note_num, index)
            
            _log("Allocated note " + str(note_num) + " to channel " + str(channel) + " at index " + str(index))
            return index, note
            
        except Exception as e:
            _log("Error allocating note: " + str(e), is_error=True)
            return None

    def release_note(self, note_num, synth=None):
        """Release a specific note."""
        try:
            for i in range(self.size):
                if self.note_nums[i] == note_num:
                    note = self.notes[i]
                    self._release_slot(i, synth)
                    return i, note
            return None, None
                    
        except Exception as e:
            _log("Error releasing note: " + str(e), is_error=True)
            return None, None

    def release_channel(self, channel, synth=None):
        """Release all notes on a channel."""
        try:
            if channel in self.channel_notes:
                note_num, index = self.channel_notes[channel]
                self._release_slot(index, synth)
                    
        except Exception as e:
            _log("Error releasing channel: " + str(e), is_error=True)

    def release_all(self, synth=None):
        """Release all notes."""
        try:
            released = []
            for i in range(self.size):
                if self.notes[i] is not None:
                    note = self.notes[i]
                    released.append(note)
                    self._release_slot(i, synth)
            
            # Also release ready note if it exists
            if self.ready_note:
                released.append(self.ready_note)
                self.ready_note = None
                self.ready_note_freq = None
            
            self.next_timestamp = 0
            self.channel_notes.clear()
            return released
            
        except Exception as e:
            _log("Error in release_all: " + str(e), is_error=True)
            return []
