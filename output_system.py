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
from constants import Constants
from fixed_point_math import FixedPoint

class AudioOutputManager:
    """Central manager for audio output"""
    def __init__(self):
        self.mixer = None
        self.audio = None
        self.volume = FixedPoint.from_float(1.0)
        self.attached_synth = None
        self._setup_audio()

    def _setup_audio(self):
        """Initialize audio hardware and mixer"""
        try:
            # Set up I2S output
            self.audio = audiobusio.I2SOut(
                bit_clock=Constants.I2S_BIT_CLOCK,
                word_select=Constants.I2S_WORD_SELECT,
                data=Constants.I2S_DATA
            )

            # Initialize mixer with stereo output
            self.mixer = audiomixer.Mixer(
                sample_rate=Constants.SAMPLE_RATE,
                buffer_size=Constants.AUDIO_BUFFER_SIZE,
                channel_count=2  # Stereo output
            )

            # Start audio
            self.audio.play(self.mixer)

            if Constants.OUTPUT_AUDIO_DEBUG:
                print("[AUDIO] Initialized: rate={0}Hz, buffer={1}".format(
                    Constants.SAMPLE_RATE, Constants.AUDIO_BUFFER_SIZE))

        except Exception as e:
            print("[ERROR] Audio setup failed: {0}".format(str(e)))
            raise

    def attach_synthesizer(self, synth):
        """Connect synthesizer to audio output"""
        try:
            if self.mixer and synth:
                # Store reference to attached synth
                self.attached_synth = synth

                # Connect to first mixer channel
                self.mixer.voice[0].play(synth)

                # Apply current volume
                self.set_volume(FixedPoint.to_float(self.volume))

                if Constants.OUTPUT_AUDIO_DEBUG:
                    print("[AUDIO] Synthesizer attached to mixer")

        except Exception as e:
            print("[ERROR] Failed to attach synthesizer: {0}".format(str(e)))

    def set_volume(self, normalized_volume):
        """Set volume from normalized hardware input"""
        try:
            # Convert to fixed point and constrain
            new_volume = FixedPoint.from_float(max(0.0, min(1.0, normalized_volume)))

            if self.mixer:
                # Apply to mixer
                self.mixer.voice[0].level = FixedPoint.to_float(new_volume)

                # Log significant changes
                if Constants.OUTPUT_AUDIO_DEBUG:
                    current_vol = FixedPoint.to_float(new_volume)
                    print("[AUDIO] Volume set to {0:.2f}".format(current_vol))

            self.volume = new_volume

        except Exception as e:
            print("[ERROR] Volume update failed: {0}".format(str(e)))

    def get_buffer_fullness(self):
        """Get current buffer status"""
        try:
            if self.mixer and hasattr(self.mixer.voice[0], 'buffer_fullness'):
                print(f"[AUDIO] Buffer fullness: {self.mixer.voice[0].buffer_fullness:.2f}")
                return self.mixer.voice[0].buffer_fullness
        except Exception as e:
            print(f"[AUDIO] Error getting buffer fullness: {str(e)}")
        return 0

    def update(self):
        """Placeholder update method to maintain compatibility"""
        # No-op method to prevent errors in existing code
        pass

    def cleanup(self):
        """Clean shutdown of audio system"""
        if Constants.OUTPUT_AUDIO_DEBUG:
            print("[AUDIO] Starting cleanup...")

        if self.mixer:
            try:
                if Constants.OUTPUT_AUDIO_DEBUG:
                    print("[AUDIO] Shutting down mixer...")
                self.mixer.voice[0].level = 0
                time.sleep(0.01)  # Allow final samples
            except Exception as e:
                print("[ERROR] Mixer cleanup failed: {0}".format(str(e)))

        if self.audio:
            try:
                if Constants.OUTPUT_AUDIO_DEBUG:
                    print("[AUDIO] Shutting down I2S...")
                self.audio.stop()
                self.audio.deinit()
            except Exception as e:
                print("[ERROR] I2S cleanup failed: {0}".format(str(e)))

        if Constants.OUTPUT_AUDIO_DEBUG:
            print("[AUDIO] Cleanup complete")
