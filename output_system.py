import audiobusio
import audiomixer
import time
from synth_constants import Constants
from fixed_point_math import FixedPoint

class PerformanceMonitor:
    """Monitors complete system performance including audio output"""
    def __init__(self):
        self.last_check_time = time.monotonic()
        self.active_voices = 0
        self.load_factor = 0.0
        self.buffer_status = 1.0
        self._last_logged_voices = 0
        self._last_logged_load = 0.0
        self._last_logged_buffer = 1.0
        self.audio_errors = 0
        self.last_error_time = 0

    def update(self, audio_output):
        """Update all performance metrics"""
        current_time = time.monotonic()
        if (current_time - self.last_check_time) >= (Constants.MPE_LOAD_CHECK_INTERVAL / 1000.0):
            # Update load metrics
            self._calculate_load(audio_output)
            self.last_check_time = current_time

            if (Constants.DEBUG and
                (abs(self.active_voices - self._last_logged_voices) > 0 or
                 abs(self.load_factor - self._last_logged_load) > 0.05 or
                 abs(self.buffer_status - self._last_logged_buffer) > 0.05)):

                print("[PERF] Status: voices={}, load={:.2f}, buffer={:.2f}, errors={}".format(
                    self.active_voices,
                    self.load_factor,
                    self.buffer_status,
                    self.audio_errors
                ))

                self._last_logged_voices = self.active_voices
                self._last_logged_load = self.load_factor
                self._last_logged_buffer = self.buffer_status

    def _calculate_load(self, audio_output):
        """Calculate system load based on multiple factors"""
        voice_load = min(1.0, self.active_voices / Constants.MAX_VOICES)

        try:
            buffer_fullness = audio_output.get_buffer_fullness()
            self.buffer_status = min(1.0, buffer_fullness / Constants.AUDIO_BUFFER_SIZE)
        except Exception as e:
            print(f"[PERF] Error getting buffer status: {str(e)}")
            self.buffer_status = 0.5

        error_rate = self.audio_errors / max(1, (time.monotonic() - self.last_error_time))

        # Weight different factors
        weighted_load = (
            (0.5 * voice_load) +
            (0.3 * self.buffer_status) +
            (0.2 * error_rate)
        )
        self.load_factor = min(1.0, weighted_load)

    def register_error(self):
        """Track audio system errors"""
        self.audio_errors += 1
        self.last_error_time = time.monotonic()
        if Constants.DEBUG:
            print("[PERF] Audio error registered")

    def should_throttle(self):
        if Constants.DISABLE_THROTTLING:
            return False
        elif self.load_factor > 0.8:
            return True
        elif self.buffer_status < 0.2:
            return True
        elif self.audio_errors > 5:
            return True
        else:
            return False

    def bypass_throttling(self):
        """Bypass performance throttling for debugging"""
        self.load_factor = 0.0
        self.buffer_status = 1.0
        self.audio_errors = 0

    def reset_error_count(self):
        """Reset error tracking"""
        self.audio_errors = 0
        if Constants.DEBUG:
            print("[PERF] Error count reset")

class AudioOutputManager:
    """Central manager for all audio output"""
    def __init__(self):
        self.performance = PerformanceMonitor()
        self.mixer = None
        self.audio = None
        self.volume = FixedPoint.from_float(1.0)
        self._last_logged_volume = 1.0
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

            if Constants.DEBUG:
                print("[AUDIO] Initialized: rate={0}Hz, buffer={1}".format(
                    Constants.SAMPLE_RATE, Constants.AUDIO_BUFFER_SIZE))

        except Exception as e:
            print("[ERROR] Audio setup failed: {0}".format(str(e)))
            self.performance.register_error()
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

                if Constants.DEBUG:
                    print("[AUDIO] Synthesizer attached to mixer")

        except Exception as e:
            print("[ERROR] Failed to attach synthesizer: {0}".format(str(e)))
            self.performance.register_error()

    def set_volume(self, normalized_volume):
        """Set volume from normalized hardware input"""
        try:
            # Convert to fixed point and constrain
            new_volume = FixedPoint.from_float(max(0.0, min(1.0, normalized_volume)))

            if self.mixer:
                # Apply to mixer
                self.mixer.voice[0].level = FixedPoint.to_float(new_volume)

                # Log significant changes
                if Constants.DEBUG:
                    current_vol = FixedPoint.to_float(new_volume)
                    if abs(current_vol - self._last_logged_volume) >= 0.1:
                        print("[AUDIO] Volume set to {0:.2f}".format(current_vol))
                        self._last_logged_volume = current_vol

            self.volume = new_volume

        except Exception as e:
            print("[ERROR] Volume update failed: {0}".format(str(e)))
            self.performance.register_error()

    def get_buffer_fullness(self):
        """Get current buffer status"""
        try:
            if self.mixer and hasattr(self.mixer.voice[0], 'buffer_fullness'):
                print(f"[AUDIO] Buffer fullness: {self.mixer.voice[0].buffer_fullness:.2f}")
                return self.mixer.voice[0].buffer_fullness
        except Exception as e:
            print(f"[AUDIO] Error getting buffer fullness: {str(e)}")
            self.performance.register_error()
        return 0

    def update(self):
        """Regular update for monitoring"""
        self.performance.update(self)

    def cleanup(self):
        """Clean shutdown of audio system"""
        if Constants.DEBUG:
            print("[AUDIO] Starting cleanup...")

        if self.mixer:
            try:
                if Constants.DEBUG:
                    print("[AUDIO] Shutting down mixer...")
                self.mixer.voice[0].level = 0
                time.sleep(0.01)  # Allow final samples
            except Exception as e:
                print("[ERROR] Mixer cleanup failed: {0}".format(str(e)))

        if self.audio:
            try:
                if Constants.DEBUG:
                    print("[AUDIO] Shutting down I2S...")
                self.audio.stop()
                self.audio.deinit()
            except Exception as e:
                print("[ERROR] I2S cleanup failed: {0}".format(str(e)))

        if Constants.DEBUG:
            print("[AUDIO] Cleanup complete")