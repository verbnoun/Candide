"""
Audio Output and Processing Module

Provides comprehensive audio pipeline management for the synthesizer.

Key Responsibilities:
- Manage complete audio processing chain
- Handle audio routing and mixing
- Provide advanced audio system controls
- Support modular audio processing stages

Primary Classes:
- AudioPipeline: Comprehensive audio processing and routing system
- AudioOutputManager: Centralized audio output management
"""

import audiobusio
import audiomixer
import time
import sys
import synthio
from constants import *
from fixed_point_math import FixedPoint

class BootBeep:
    """Simple boot beep that can run independently"""
    def __init__(self, bit_clock, word_select, data):
        _log("Initializing BootBeep")
        self.bit_clock = bit_clock
        self.word_select = word_select
        self.data = data
        self.audio_out = None
        
    def play(self):
        """Play a boot beep"""
        try:
            # Setup I2S
            _log("BootBeep: Setting up I2S output...")
            self.audio_out = audiobusio.I2SOut(
                bit_clock=self.bit_clock,
                word_select=self.word_select,
                data=self.data
            )
            _log("BootBeep: I2S initialized successfully")
            
            # Create synth
            _log("BootBeep: Creating synthesizer...")
            synth = synthio.Synthesizer(sample_rate=SAMPLE_RATE)
            self.audio_out.play(synth)
            _log("BootBeep: Synthesizer playing")
            
            # Play gentle beep
            _log("BootBeep: Playing boot sound...")
            synth.press(64)  # A5 note
            time.sleep(0.10)  # Duration
            
            _log("BootBeep: Note released...")
            synth.release(81)
            time.sleep(0.05)  # Let release finish
            
            _log("BootBeep: Audio playback completed")
            
            # Cleanup
            _log("BootBeep: Starting cleanup...")
            synth.deinit()
            _log("BootBeep: Synthesizer deinitialized")
            self.audio_out.deinit()
            _log("BootBeep: I2S deinitialized")
            self.audio_out = None
            _log("BootBeep: Cleanup complete")
            
        except Exception as e:
            _log(f"[ERROR] BootBeep failed: {str(e)}")
            if self.audio_out:
                _log("BootBeep: Emergency cleanup of I2S...")
                try:
                    self.audio_out.deinit()
                    _log("BootBeep: Emergency cleanup successful")
                except:
                    _log("[ERROR] BootBeep: Emergency cleanup failed")
                self.audio_out = None
            raise e

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
    Conditional logging function that respects OUTPUT_DEBUG flag.
    Args:
        message (str/dict): Message to log
    """
    RED = "\033[31m"  # For errors
    GREEN = "\033[32m"  # For rejected messages
    LIGHT_GREEN = "\033[92m"  # For standard messages
    RESET = "\033[0m" 
    
    if OUTPUT_DEBUG:
        if "[ERROR]" in str(message):
            color = RED
        elif "[REJECTED]" in str(message) or "rejected" in str(message).lower():
            color = GREEN
        else:
            color = LIGHT_GREEN

        # If message is a dictionary, format with custom indentation
        if isinstance(message, dict):
            formatted_message = _format_log_message(message)
            print(f"{color}{formatted_message}{RESET}", file=sys.stderr)
        else:
            print(f"{color}[AUDIO] {message}{RESET}", file=sys.stderr)

class AudioStage:
    """Base class for audio processing stages"""
    def __init__(self, name):
        self.name = name
        self.next_stage = None

    def process(self, audio_data):
        """Process audio data"""
        raise NotImplementedError("Subclasses must implement process method")

    def connect(self, next_stage):
        """Connect to next processing stage"""
        self.next_stage = next_stage
        return next_stage

class AudioPipeline:
    """Comprehensive audio processing and routing system"""
    def __init__(self, sample_rate=SAMPLE_RATE, channels=2):
        _log("Initializing AudioPipeline")
        
        # Play boot beep before anything else
        boot_beep = BootBeep(I2S_BIT_CLOCK, I2S_WORD_SELECT, I2S_DATA)
        try:
            boot_beep.play()
        except Exception as e:
            _log(f"[ERROR] Boot beep failed: {str(e)}")
        
        self.sample_rate = sample_rate
        self.channels = channels
        
        # Audio processing stages
        self.stages = []
        
        # Audio output components
        self.mixer = None
        self.audio_out = None
        
        self._setup_audio()

    def _setup_audio(self):
        """Initialize audio hardware and mixer"""
        try:
            _log("Setting up I2S output...")
            self.audio_out = audiobusio.I2SOut(
                bit_clock=I2S_BIT_CLOCK,
                word_select=I2S_WORD_SELECT,
                data=I2S_DATA
            )
            _log("I2S output initialized successfully")

            _log("Initializing audio mixer...")
            self.mixer = audiomixer.Mixer(
                sample_rate=self.sample_rate,
                buffer_size=AUDIO_BUFFER_SIZE,
                channel_count=self.channels
            )
            _log("Audio mixer initialized successfully")

            # Start audio
            _log("Starting audio playback...")
            self.audio_out.play(self.mixer)
            _log("Audio playback started")

        except Exception as e:
            _log(f"[ERROR] Audio setup failed: {str(e)}")
            raise

    def add_stage(self, stage):
        """Add a processing stage to the pipeline"""
        if self.stages:
            self.stages[-1].connect(stage)
        self.stages.append(stage)
        return stage

    def attach_synthesizer(self, synth):
        """Attach synthesizer to mixer"""
        try:
            if not self.mixer:
                _log("[ERROR] Cannot attach synthesizer - mixer not initialized")
                return False

            _log("Connecting synthesizer to mixer channel 0")
            self.mixer.voice[0].play(synth)
            
            _log({
                "event": "Synthesizer Attached",
                "mixer_channel": 0,
                "synth_type": type(synth).__name__
            })
            return True

        except Exception as e:
            _log(f"[ERROR] Failed to attach synthesizer: {str(e)}")
            return False

    def set_volume(self, normalized_volume):
        """Set volume for the primary mixer channel"""
        try:
            # Constrain volume between 0 and 1
            volume = max(0.0, min(1.0, normalized_volume))
            
            if self.mixer:
                current_vol = self.mixer.voice[0].level
                self.mixer.voice[0].level = volume

                if OUTPUT_DEBUG and abs(current_vol - volume) >= 0.1:
                    _log(f"Volume changed from {current_vol:.2f} to {volume:.2f}")

        except Exception as e:
            _log(f"[ERROR] Volume update failed: {str(e)}")

    def get_buffer_status(self):
        """Get detailed buffer status"""
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
            _log(f"[ERROR] Error getting buffer status: {str(e)}")
        return 0

    def cleanup(self):
        """Comprehensive cleanup of audio system"""
        _log("Starting audio system cleanup")

        try:
            # Stop and deinitialize mixer
            if self.mixer:
                _log("Shutting down mixer")
                self.mixer.voice[0].level = 0
                time.sleep(0.01)  # Allow final samples

            # Stop and deinitialize I2S
            if self.audio_out:
                _log("Shutting down I2S")
                self.audio_out.stop()
                self.audio_out.deinit()

            _log({
                "event": "Cleanup Status",
                "mixer_cleaned": self.mixer is not None,
                "audio_cleaned": self.audio_out is not None
            })

        except Exception as e:
            _log(f"[ERROR] Audio system cleanup failed: {str(e)}")

# Maintain backward compatibility
AudioOutputManager = AudioPipeline
