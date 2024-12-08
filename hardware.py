"""Hardware interface management system for Candide synthesizer providing direct control of physical components."""

import board
import analogio
import rotaryio
import digitalio
import time
import synthio
import sys
import audiobusio
import audiomixer
from constants import *
from logging import log, TAG_HARD

class AudioSystem:
    def __init__(self):
        log(TAG_HARD, "Initializing AudioSystem")
        self.audio_out = None
        self.mixer = None
        self.current_volume = 0.5
        self._setup_audio()

    def _setup_audio(self):
        try:
            audiobusio.I2SOut(I2S_BIT_CLOCK, I2S_WORD_SELECT, I2S_DATA).deinit()

            self.audio_out = audiobusio.I2SOut(
                bit_clock=I2S_BIT_CLOCK,
                word_select=I2S_WORD_SELECT,
                data=I2S_DATA
            )

            self.mixer = audiomixer.Mixer(
                sample_rate=SAMPLE_RATE,
                buffer_size=AUDIO_BUFFER_SIZE,
                channel_count=AUDIO_CHANNEL_COUNT
            )

            self.audio_out.play(self.mixer)
            
            self.set_volume(self.current_volume)
            
            log(TAG_HARD, "Audio system initialized successfully")

        except Exception as e:
            log(TAG_HARD, f"Audio setup failed: {str(e)}", is_error=True)
            self.cleanup()
            raise

    def set_volume(self, normalized_volume):
        try:
            volume = max(0.0, min(1.0, normalized_volume))
            
            if volume > 0:
                log_volume = (2 ** (volume * 2) - 1) / 3
            else:
                log_volume = 0.0
                
            if self.mixer:
                for i in range(len(self.mixer.voice)):
                    self.mixer.voice[i].level = log_volume
                
            self.current_volume = volume
            
        except Exception as e:
            log(TAG_HARD, f"Volume update failed: {str(e)}", is_error=True)

    def cleanup(self):
        log(TAG_HARD, "Starting audio system cleanup")
        try:
            if self.mixer:
                for voice in self.mixer.voice:
                    voice.level = 0
                time.sleep(0.01)
            if self.audio_out:
                self.audio_out.stop()
                self.audio_out.deinit()
        except Exception as e:
            log(TAG_HARD, f"Audio cleanup failed: {str(e)}", is_error=True)

class BootBeep:
    def play(self):
        audio_out = None
        try:
            audiobusio.I2SOut(I2S_BIT_CLOCK, I2S_WORD_SELECT, I2S_DATA).deinit()
            audio_out = audiobusio.I2SOut(I2S_BIT_CLOCK, I2S_WORD_SELECT, I2S_DATA)
            
            log(TAG_HARD, f"BootBeep: Parameters: SAMPLE_RATE={SAMPLE_RATE}, AUDIO_CHANNEL_COUNT={AUDIO_CHANNEL_COUNT}")
            synth = synthio.Synthesizer(sample_rate=SAMPLE_RATE, channel_count=AUDIO_CHANNEL_COUNT)
            
            audio_out.play(synth)
            log(TAG_HARD, "Testing basic hardware audio output...")
            synth.press(64)
            time.sleep(0.05)
            
            synth.release(64)
            time.sleep(0.05)
            log(TAG_HARD, "BootBeep: BEEP!")
            synth.deinit()
            audio_out.deinit()
            
        except Exception as e:
            log(TAG_HARD, f"BootBeep error: {str(e)}", is_error=True)
            if audio_out:
                audio_out.deinit()

class HardwareComponent:
    def __init__(self):
        self.is_active = False
        
    def cleanup(self):
        pass

class VolumeManager(HardwareComponent):
    def __init__(self, pin):
        super().__init__()
        self.pot = analogio.AnalogIn(pin)
        self.last_value = self.pot.value
        self.last_normalized = self.normalize_value(self.last_value)
        log(TAG_HARD, f"Volume pot initialized. Initial raw value: {self.last_value}, normalized: {self.last_normalized:.2f}")
    
    def normalize_value(self, value):
        clamped_value = max(min(value, ADC_MAX), ADC_MIN)
        normalized = (clamped_value - ADC_MIN) / (ADC_MAX - ADC_MIN)
        
        if normalized < POT_LOWER_TRIM:
            normalized = 0
        elif normalized > (1 - POT_UPPER_TRIM):
            normalized = 1
        else:
            normalized = (normalized - POT_LOWER_TRIM) / (1 - POT_LOWER_TRIM - POT_UPPER_TRIM)
        
        return round(normalized, 5)

    def read(self):
        try:
            raw_value = self.pot.value
            change = abs(raw_value - self.last_value)
            
            if change > POT_THRESHOLD:
                normalized_new = self.normalize_value(raw_value)
                
                if normalized_new != self.last_normalized:
                    self.last_value = raw_value
                    self.last_normalized = normalized_new
                    self.is_active = True
                    return normalized_new
                    
            return None
            
        except Exception as e:
            log(TAG_HARD, f"Volume read failed: {str(e)}", is_error=True)
            return None
        
    def cleanup(self):
        if self.pot:
            self.pot.deinit()

class EncoderManager(HardwareComponent):
    def __init__(self, clk_pin, dt_pin):
        super().__init__()
        self.encoder = rotaryio.IncrementalEncoder(clk_pin, dt_pin, divisor=2)
        self.last_position = 0
        self.current_position = 0
        self.reset_position()

    def reset_position(self):
        self.encoder.position = 0
        self.last_position = 0
        self.current_position = 0

    def read(self):
        events = []
        current_raw_position = self.encoder.position
        
        if current_raw_position != self.last_position:
            direction = 1 if current_raw_position > self.last_position else -1
            log(TAG_HARD, f"Encoder movement: pos={current_raw_position}, last={self.last_position}, dir={direction}")
            events.append(('instrument_change', direction))
            self.last_position = current_raw_position
        
        return events

class DetectPinManager:
    def __init__(self, pin, log_interval=5):
        """
        Initialize the DetectPinManager.
        
        :param pin: The GPIO pin to monitor.
        :param log_interval: Time interval (in seconds) for periodic logging.
        """
        log(TAG_HARD, "Initializing detection pin...")
        
        # Set up the pin
        self.detect_pin = digitalio.DigitalInOut(pin)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN  # Use internal pull-down resistor
        
        # Initialize state tracking
        self.last_state = self.detect_pin.value
        self.last_log_time = time.monotonic()
        self.log_interval = log_interval  # Log periodically
        
        # Initial log for verification
        log(TAG_HARD, f"Detection pin initialized (initial state: {'HIGH' if self.last_state else 'LOW'})")

    def is_detected(self):
        """
        Check the pin state (HIGH or LOW) and log changes.
        
        :return: True if HIGH (connected), False if LOW (disconnected).
        """
        current_state = self.detect_pin.value
        
        # Log state changes
        if current_state != self.last_state:
            log(TAG_HARD, f"State changed: {'HIGH' if current_state else 'LOW'}")
            self.last_state = current_state
        
        # Periodic logging for monitoring
        current_time = time.monotonic()
        if current_time - self.last_log_time >= self.log_interval:
            self.last_log_time = current_time
        
        return current_state

    def cleanup(self):
        """
        Deinitialize the pin safely.
        """
        if self.detect_pin:
            self.detect_pin.deinit()
            log(TAG_HARD, "Detection pin deinitialized.")

class HardwareManager:
    def __init__(self):
        log(TAG_HARD, "Starting HardwareManager initialization...")
        
        log(TAG_HARD, "Running BootBeep test...")
        BootBeep().play()
        
        self.volume = None
        self.encoder = None
        self.detect = None
        self.last_encoder_scan = 0
        self.last_volume_scan = 0
        self.last_volume = None
        self._initialize_components()

    def _initialize_components(self):
        try:
            log(TAG_HARD, "Initializing volume manager...")
            self.volume = VolumeManager(VOLUME_POT)
            
            log(TAG_HARD, "Initializing encoder manager...")
            self.encoder = EncoderManager(INSTRUMENT_ENC_CLK, INSTRUMENT_ENC_DT)
            
            log(TAG_HARD, "Initializing detect pin manager...")
            self.detect = DetectPinManager(DETECT_PIN)
            
            log(TAG_HARD, "Hardware components initialized successfully")
        except Exception as e:
            log(TAG_HARD, f"Hardware initialization failed: {str(e)}", is_error=True)
            self.cleanup()
            raise

    def get_initial_volume(self):
        if self.volume:
            initial_volume = self.volume.normalize_value(self.volume.pot.value)
            log(TAG_HARD, f"Getting initial volume: {initial_volume:.2f}")
            return initial_volume
        return 0.0

    def read_encoder(self):
        if self.encoder:
            return self.encoder.read()
        return []

    def read_volume(self):
        if self.volume:
            return self.volume.read()
        return None

    def is_base_station_detected(self):
        if self.detect:
            return self.detect.is_detected()
        return False

    def check_volume(self, audio_system):
        current_time = time.monotonic()
        if current_time - self.last_volume_scan >= UPDATE_INTERVAL:
            new_volume = self.read_volume()
            if new_volume is not None and new_volume != self.last_volume:
                # Only log if volume changed by 0.05 or more
                if abs(new_volume - (self.last_volume or 0)) >= 0.05:
                    log(TAG_HARD, f"Volume update - Previous: {self.last_volume:.2f}, New: {new_volume:.2f}")
                audio_system.set_volume(new_volume)
                self.last_volume = new_volume
            self.last_volume_scan = current_time

    def check_encoder(self, instrument_manager):
        current_time = time.monotonic()
        if current_time - self.last_encoder_scan >= ENCODER_SCAN_INTERVAL:
            events = self.read_encoder()
            
            if events:
                for event_type, direction in events:
                    if event_type == 'instrument_change':
                        instruments = instrument_manager.get_available_instruments()
                        current_idx = instruments.index(instrument_manager.current_instrument)
                        new_idx = (current_idx + direction) % len(instruments)
                        new_instrument = instruments[new_idx]
                        instrument_manager.set_instrument(new_instrument)
            
            self.last_encoder_scan = current_time

    def cleanup(self):
        if self.encoder:
            self.encoder.cleanup()
            self.encoder = None
            
        if self.volume:
            self.volume.cleanup()
            self.volume = None
            
        if self.detect:
            self.detect.cleanup()
            self.detect = None
