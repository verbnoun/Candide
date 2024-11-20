"""
Audio Output Module

Provides audio output routing for the synthesizer.

Key Responsibilities:
- Manage audio hardware initialization
- Control audio output and volume
- Provide basic audio system management

Primary Classes:
- AudioOutputManager: Centralized audio output management
  * Initializes audio hardware (I2S)
  * Manages audio mixer
  * Controls volume
  * Attaches synthesizer to audio output
"""

import audiobusio
import audiomixer
import time
import sys
from constants import *
from fixed_point_math import FixedPoint

def _format_log_message(message):
    """
    Format a dictionary or primitive message for console logging.
    
    Args:
        message (dict/str/primitive): Message to format
        
    Returns:
        str: Formatted message string
    """
    def format_value(value, indent_level=0):
        """Recursively format values with proper indentation."""
        base_indent = ' ' * 0
        extra_indent = ' ' * 2
        indent = base_indent + ' ' * (4 * indent_level)
        
        if isinstance(value, dict):
            if not value:  # Handle empty dict
                return '{}'
            lines = ['{']
            for k, v in value.items():
                formatted_v = format_value(v, indent_level + 1)
                lines.append(f"{indent + extra_indent}'{k}': {formatted_v},")
            lines.append(f"{indent}}}")
            return '\n'.join(lines)
        
        elif isinstance(value, list):
            if not value:  # Handle empty list
                return '[]'
            lines = ['[']
            for item in value:
                formatted_item = format_value(item, indent_level + 1)
                lines.append(f"{indent + extra_indent}{formatted_item},")
            lines.append(f"{indent}]")
            return '\n'.join(lines)
        
        elif isinstance(value, str):
            return f"'{value}'"
        else:
            return str(value)
            
    return format_value(message)

def _log(message):
    """
    Conditional logging function that respects OUTPUT_AUDIO_DEBUG flag.
    Args:
        message (str/dict): Message to log
    """
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[37m"
    DARK_GRAY = "\033[90m"
    RESET = "\033[0m" 
    
    if OUTPUT_AUDIO_DEBUG:
        if "rejected" in str(message):
            color = DARK_GRAY
        elif "[ERROR]" in str(message):
            color = RED
        elif "[AUDIO]" in str(message):
            color = YELLOW
        else:
            color = YELLOW

        # If message is a dictionary, format with custom indentation
        if isinstance(message, dict):
            formatted_message = _format_log_message(message)
            print(f"{color}{formatted_message}{RESET}", file=sys.stderr)
        else:
            print(f"{color}[AUDIO] {message}{RESET}", file=sys.stderr)

class AudioOutputManager:
    """Central manager for audio output"""
    def __init__(self):
        self.mixer = None
        self.audio = None
        self.volume = FixedPoint.from_float(1.0)
        self.attached_synth = None
        
        _log("Initializing AudioOutputManager")
        self._setup_audio()

    def _setup_audio(self):
        """Initialize audio hardware and mixer"""
        try:
            _log("Setting up I2S output...")
            # Set up I2S output
            self.audio = audiobusio.I2SOut(
                bit_clock=I2S_BIT_CLOCK,
                word_select=I2S_WORD_SELECT,
                data=I2S_DATA
            )
            _log("I2S output initialized successfully")

            _log("Initializing audio mixer...")
            # Initialize mixer with stereo output
            self.mixer = audiomixer.Mixer(
                sample_rate=SAMPLE_RATE,
                buffer_size=AUDIO_BUFFER_SIZE,
                channel_count=2  # Stereo output
            )
            _log("Audio mixer initialized successfully")

            # Start audio
            _log("Starting audio playback...")
            self.audio.play(self.mixer)
            _log("Audio playback started")

            _log({
                "event": "Audio System Status",
                "i2s_initialized": self.audio is not None,
                "mixer_initialized": self.mixer is not None,
                "sample_rate": SAMPLE_RATE,
                "buffer_size": AUDIO_BUFFER_SIZE,
                "channels": 2,
                "volume": FixedPoint.to_float(self.volume)
            })

        except Exception as e:
            _log(f"[ERROR] Audio setup failed: {str(e)}")
            raise

    def attach_synthesizer(self, synth):
        """Connect synthesizer to audio output"""
        try:
            _log("Attempting to attach synthesizer...")
            
            if not self.mixer:
                _log("[ERROR] Cannot attach synthesizer - mixer not initialized")
                return
                
            if not synth:
                _log("[ERROR] Cannot attach synthesizer - synth object is None")
                return

            # Store reference to attached synth
            self.attached_synth = synth

            # Connect to first mixer channel
            _log("Connecting synthesizer to mixer channel 0")
            self.mixer.voice[0].play(synth)

            # Apply current volume
            current_vol = FixedPoint.to_float(self.volume)
            _log(f"Setting initial mixer volume to {current_vol:.2f}")
            self.set_volume(current_vol)

            _log({
                "event": "Synthesizer Status",
                "attached": True,
                "mixer_channel": 0,
                "volume": current_vol,
                "synth_type": type(synth).__name__
            })

        except Exception as e:
            _log(f"[ERROR] Failed to attach synthesizer: {str(e)}")
            _log({
                "event": "Synthesizer Attachment Error",
                "error": str(e),
                "mixer_state": "initialized" if self.mixer else "not initialized",
                "synth_state": "valid" if synth else "invalid"
            })

    def set_volume(self, normalized_volume):
        """Set volume from normalized hardware input"""
        try:
            # Convert to fixed point and constrain
            new_volume = FixedPoint.from_float(max(0.0, min(1.0, normalized_volume)))

            if self.mixer:
                # Check if volume change is significant (>0.1 or 10%)
                current_vol = FixedPoint.to_float(self.volume)
                new_vol = FixedPoint.to_float(new_volume)
                
                # Apply to mixer
                self.mixer.voice[0].level = new_vol

                # Log only if volume change is significant
                if OUTPUT_AUDIO_DEBUG and abs(current_vol - new_vol) >= 0.1:
                    _log(f"Volume changed from {current_vol:.2f} to {new_vol:.2f}")

            self.volume = new_volume

        except Exception as e:
            _log(f"[ERROR] Volume update failed: {str(e)}")

    def get_buffer_fullness(self):
        """Get current buffer status"""
        try:
            if self.mixer and hasattr(self.mixer.voice[0], 'buffer_fullness'):
                buffer_fullness = self.mixer.voice[0].buffer_fullness
                _log({
                    "event": "Buffer Status",
                    "buffer_fullness": buffer_fullness,
                    "mixer_active": True,
                    "voice_active": True
                })
                return buffer_fullness
        except Exception as e:
            _log(f"[ERROR] Error getting buffer fullness: {str(e)}")
            _log({
                "event": "Buffer Status Error",
                "error": str(e),
                "mixer_state": "initialized" if self.mixer else "not initialized"
            })
        return 0

    def update(self):
        """Placeholder update method to maintain compatibility"""
        # No-op method to prevent errors in existing code
        pass

    def cleanup(self):
        """Clean shutdown of audio system"""
        _log("Starting audio system cleanup")

        if self.mixer:
            try:
                _log("Shutting down mixer")
                self.mixer.voice[0].level = 0
                time.sleep(0.01)  # Allow final samples
            except Exception as e:
                _log(f"[ERROR] Mixer cleanup failed: {str(e)}")

        if self.audio:
            try:
                _log("Shutting down I2S")
                self.audio.stop()
                self.audio.deinit()
            except Exception as e:
                _log(f"[ERROR] I2S cleanup failed: {str(e)}")

        _log({
            "event": "Cleanup Status",
            "mixer_cleaned": self.mixer is not None,
            "audio_cleaned": self.audio is not None
        })
