import audiobusio
import audiomixer
import time
from synth_constants import Constants
from fixed_point_math import FixedPoint

class PerformanceMonitor:
    """Monitors system load and audio performance"""
    def __init__(self):
        self.last_check_time = time.monotonic()
        self.active_voices = 0
        self.load_factor = 0.0
        self.buffer_status = 1.0
        self._last_logged_voices = 0
        self._last_logged_load = 0.0
        self._last_logged_buffer = 1.0
        
    def update(self, audio_output):
        """Update performance metrics"""
        current_time = time.monotonic()
        if (current_time - self.last_check_time) >= (Constants.MPE_LOAD_CHECK_INTERVAL / 1000.0):  # Convert ms to seconds
            # Calculate load metrics
            self.load_factor = self._calculate_load(audio_output)
            self.last_check_time = current_time
            
            # Only log if values have changed significantly
            if (Constants.DEBUG and 
                (abs(self.active_voices - self._last_logged_voices) > 0 or
                 abs(self.load_factor - self._last_logged_load) > 0.05 or
                 abs(self.buffer_status - self._last_logged_buffer) > 0.05)):
                
                print("[AUDIO] Performance: voices={0}, load={1:.2f}, buffer={2:.2f}".format(
                    self.active_voices, self.load_factor, self.buffer_status))
                    
                self._last_logged_voices = self.active_voices
                self._last_logged_load = self.load_factor
                self._last_logged_buffer = self.buffer_status
            
    def _calculate_load(self, audio_output):
        """Calculate current system load"""
        voice_load = min(1.0, self.active_voices / Constants.MAX_VOICES)
        
        try:
            buffer_fullness = audio_output.get_buffer_fullness()
            self.buffer_status = min(1.0, buffer_fullness / Constants.AUDIO_BUFFER_SIZE)
        except Exception:
            self.buffer_status = 0.5
            
        return (0.7 * voice_load) + (0.3 * self.buffer_status)
    
    def should_throttle(self):
        """Determine if we should throttle incoming messages"""
        return self.load_factor > 0.8
    
    def get_voice_allocation_status(self):
        """Get status of voice allocation"""
        return {
            'active_voices': self.active_voices,
            'load_factor': self.load_factor,
            'buffer_status': self.buffer_status
        }

class AudioOutputManager:
    """Manages audio output hardware and mixing"""
    def __init__(self):
        self.performance = PerformanceMonitor()
        self.mixer = None
        self.audio = None
        self.volume = FixedPoint.from_float(1.0)
        self._last_logged_volume = 1.0
        self._setup_audio()
        
    def _setup_audio(self):
        """Initialize audio hardware and mixer"""
        try:
            # Set up I2S output for PCM5102A DAC
            self.audio = audiobusio.I2SOut(
                bit_clock=Constants.I2S_BIT_CLOCK,
                word_select=Constants.I2S_WORD_SELECT,
                data=Constants.I2S_DATA
            )
            
            # Initialize mixer
            self.mixer = audiomixer.Mixer(
                sample_rate=Constants.SAMPLE_RATE,
                buffer_size=Constants.AUDIO_BUFFER_SIZE,
                channel_count=2
            )
            
            # Start audio
            self.audio.play(self.mixer)
            
            if Constants.DEBUG:
                print("[AUDIO] Initialized: rate={0}Hz, buffer={1}".format(
                    Constants.SAMPLE_RATE, Constants.AUDIO_BUFFER_SIZE))
            
        except Exception as e:
            print("Audio setup error: {0}".format(str(e)))
            raise
            
    def attach_synthesizer(self, synth):
        """Attach synthesizer to mixer"""
        if self.mixer and synth:
            self.mixer.voice[0].play(synth)
            self.set_volume(FixedPoint.to_float(self.volume))
            if Constants.DEBUG:
                print("[AUDIO] Synthesizer attached to mixer")
            
    def set_volume(self, volume):
        """Set master volume"""
        new_volume = FixedPoint.from_float(max(0.0, min(1.0, volume)))
        if self.mixer:
            self.mixer.voice[0].level = FixedPoint.to_float(new_volume)
            
            # Only log if volume has changed significantly
            if Constants.DEBUG and abs(FixedPoint.to_float(new_volume) - self._last_logged_volume) > 0.01:
                print("[AUDIO] Volume set to {0:.2f}".format(FixedPoint.to_float(new_volume)))
                self._last_logged_volume = FixedPoint.to_float(new_volume)
                
        self.volume = new_volume
            
    def get_buffer_fullness(self):
        """Get audio buffer status"""
        try:
            if hasattr(self.mixer.voice[0], 'buffer_fullness'):
                return self.mixer.voice[0].buffer_fullness
        except Exception:
            pass
        return 0
        
    def update(self):
        """Update performance monitoring"""
        self.performance.update(self)
        
    def cleanup(self):
        """Clean shutdown of audio system"""
        if self.mixer:
            try:
                if Constants.DEBUG:
                    print("[AUDIO] Shutting down mixer...")
                self.mixer.voice[0].level = 0
                time.sleep(0.01)  # Allow final samples to play
            except Exception:
                pass
                
        if self.audio:
            try:
                if Constants.DEBUG:
                    print("[AUDIO] Shutting down I2S...")
                self.audio.stop()
                self.audio.deinit()
            except Exception:
                pass
