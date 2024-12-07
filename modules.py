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
        print(f"{color}{LOG_SYNTH} [ERROR] {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{LOG_SYNTH} {message}{LOG_RESET}", file=sys.stderr)

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
        raise ValueError(f"Invalid waveform type: {waveform_type}. Must be one of: sine, square, saw, triangle")
    
    return buffer

class NotePool:
    """Manages a fixed pool of pre-allocated notes with MPE support and robust FIFO note stealing."""
    def __init__(self, size=5):
        """Initialize note pool with specified size."""
        self.size = size
        self.available_indices = list(range(size))  # Available note indices
        self.active_notes = {}      # note_number -> (index, note) mapping
        self.note_order = []        # FIFO order tracking (oldest first)
        self.channel_notes = {}     # channel -> (note_number, index) for MPE
        self.note_timestamps = {}   # note_number -> timestamp for age tracking
        self._timestamp = 0         # Monotonic counter for note age
        _log(f"Note pool initialized with size {size}")

    def _get_timestamp(self):
        """Get next timestamp for note age tracking."""
        self._timestamp += 1
        return self._timestamp

    def _cleanup_note(self, note_number):
        """Clean up all references to a note."""
        if note_number in self.active_notes:
            index, note = self.active_notes[note_number]
            
            # Remove from all tracking structures
            del self.active_notes[note_number]
            if note_number in self.note_order:
                self.note_order.remove(note_number)
            if note_number in self.note_timestamps:
                del self.note_timestamps[note_number]
            
            # Remove from channel tracking
            channels_to_remove = []
            for channel, (n, _) in self.channel_notes.items():
                if n == note_number:
                    channels_to_remove.append(channel)
            for channel in channels_to_remove:
                del self.channel_notes[channel]
            
            # Return index to available pool
            if index not in self.available_indices:
                self.available_indices.append(index)
            
            return index, note
        return None, None

    def get_note(self, note_number, channel):
        """Get next available note, implementing FIFO note stealing if needed."""
        try:
            # First handle any existing note on this channel (MPE)
            if channel in self.channel_notes:
                old_note_num, _ = self.channel_notes[channel]
                self.release_note(old_note_num)
                _log(f"Released existing note {old_note_num} on channel {channel}")
            
            # If this note is already pressed somewhere else, release it
            if note_number in self.active_notes:
                self.release_note(note_number)
                _log(f"Released duplicate note {note_number}")
            
            # Get an available index or steal the oldest note
            if self.available_indices:
                index = self.available_indices.pop(0)
                _log(f"Using available index {index} for note {note_number}")
            else:
                # No indices available - steal the oldest note
                if self.note_order:
                    oldest_note = self.note_order[0]
                    _log(f"Stealing oldest note {oldest_note} for new note {note_number}")
                    index, _ = self._cleanup_note(oldest_note)
                else:
                    _log("Error: Note pool in invalid state - no notes to steal", is_error=True)
                    return None
            
            # Create new note
            freq = synthio.midi_to_hz(note_number)
            note = synthio.Note(frequency=freq)
            
            # Update all tracking structures
            self.active_notes[note_number] = (index, note)
            self.note_order.append(note_number)
            self.channel_notes[channel] = (note_number, index)
            self.note_timestamps[note_number] = self._get_timestamp()
            
            _log(f"Note {note_number} allocated to index {index} on channel {channel}")
            return index, note
            
        except Exception as e:
            _log(f"Error allocating note: {str(e)}", is_error=True)
            return None

    def release_note(self, note_number):
        """Release a note and clean up all its references."""
        try:
            if note_number in self.active_notes:
                _log(f"Releasing note {note_number}")
                index, note = self._cleanup_note(note_number)
                return index, note
            return None, None
            
        except Exception as e:
            _log(f"Error releasing note: {str(e)}", is_error=True)
            return None, None

    def release_all(self):
        """Release all active notes."""
        try:
            released_notes = []
            for note_number in list(self.active_notes.keys()):
                _, note = self.release_note(note_number)
                if note is not None:
                    released_notes.append(note)
            
            # Reset all tracking structures
            self.available_indices = list(range(self.size))
            self.active_notes.clear()
            self.note_order.clear()
            self.channel_notes.clear()
            self.note_timestamps.clear()
            self._timestamp = 0
            
            _log(f"Released all notes ({len(released_notes)} total)")
            return released_notes
            
        except Exception as e:
            _log(f"Error in release_all: {str(e)}", is_error=True)
            return []
