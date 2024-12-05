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

def _log(message):
    if not HARDWARE_DEBUG:
        return
        
    RED = "\033[31m"
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        formatted_message = _format_log_message(message)
        print(f"{RESET}{formatted_message}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message):
            color = RED
        else:
            color = RESET
        print(f"{color}[HARD  ] {message}{RESET}", file=sys.stderr)

class AudioSystem:
    def __init__(self):
        _log("Initializing AudioSystem")
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
            
            _log("Audio system initialized successfully")

        except Exception as e:
            _log(f"[ERROR] Audio setup failed: {str(e)}")
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
            _log(f"Volume set to {volume:.3f} (log_volume: {log_volume:.3f})")
            
        except Exception as e:
            _log(f"[ERROR] Volume update failed: {str(e)}")

    def cleanup(self):
        _log("Starting audio system cleanup")
        try:
            if self.mixer:
                for voice in self.mixer.voice:
                    voice.level = 0
                time.sleep(0.01)
            if self.audio_out:
                self.audio_out.stop()
                self.audio_out.deinit()
        except Exception as e:
            _log(f"[ERROR] Audio cleanup failed: {str(e)}")

class BootBeep:
    def play(self):
        if not HARDWARE_DEBUG:
            return

        audio_out = None
        try:
            audiobusio.I2SOut(I2S_BIT_CLOCK, I2S_WORD_SELECT, I2S_DATA).deinit()
            audio_out = audiobusio.I2SOut(I2S_BIT_CLOCK, I2S_WORD_SELECT, I2S_DATA)
            
            _log(f"BootBeep: Parameters: SAMPLE_RATE={SAMPLE_RATE}, AUDIO_CHANNEL_COUNT={AUDIO_CHANNEL_COUNT}")
            synth = synthio.Synthesizer(sample_rate=SAMPLE_RATE, channel_count=AUDIO_CHANNEL_COUNT)
            
            audio_out.play(synth)
            _log("Testing basic hardware audio output...")
            synth.press(64)
            time.sleep(0.05)
            
            synth.release(64)
            time.sleep(0.05)
            _log("BootBeep: BEEP!")
            synth.deinit()
            audio_out.deinit()
            
        except Exception as e:
            print(f"[BOOTBEEP] error: {str(e)}")
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
        _log(f"Volume pot initialized. Initial raw value: {self.last_value}, normalized: {self.last_normalized:.3f}")
    
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
                    _log(f"Volume change detected - Raw: {raw_value} (Δ{change}), Normalized: {normalized_new:.3f}")
                    self.last_value = raw_value
                    self.last_normalized = normalized_new
                    self.is_active = True
                    return normalized_new
                    
            return None
            
        except Exception as e:
            _log(f"[ERROR] Volume read failed: {str(e)}")
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

            if HARDWARE_DEBUG:
                print(f"Encoder movement: pos={current_raw_position}, last={self.last_position}, dir={direction}")
            
            events.append(('instrument_change', direction))
            self.last_position = current_raw_position
        
        return events

import time
import digitalio
import board

def _log(message):
    """Simple logging function."""
    print(message)

class DetectPinManager:
    def __init__(self, pin, log_interval=5):
        """
        Initialize the DetectPinManager.
        
        :param pin: The GPIO pin to monitor.
        :param log_interval: Time interval (in seconds) for periodic logging.
        """
        _log("Initializing detection pin...")
        
        # Set up the pin
        self.detect_pin = digitalio.DigitalInOut(pin)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN  # Use internal pull-down resistor
        
        # Initialize state tracking
        self.last_state = self.detect_pin.value
        self.last_log_time = time.monotonic()
        self.log_interval = log_interval  # Log periodically
        
        # Initial log for verification
        _log(f"Detection pin initialized (initial state: {'HIGH' if self.last_state else 'LOW'})")

    def is_detected(self):
        """
        Check the pin state (HIGH or LOW) and log changes.
        
        :return: True if HIGH (connected), False if LOW (disconnected).
        """
        current_state = self.detect_pin.value
        
        # Log state changes
        if current_state != self.last_state:
            _log(f"State changed: {'HIGH' if current_state else 'LOW'}")
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
            _log("Detection pin deinitialized.")


class HardwareManager:
    def __init__(self):
        _log("Starting HardwareManager initialization...")
        
        _log("Running BootBeep test...")
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
            _log("Initializing volume manager...")
            self.volume = VolumeManager(VOLUME_POT)
            
            _log("Initializing encoder manager...")
            self.encoder = EncoderManager(INSTRUMENT_ENC_CLK, INSTRUMENT_ENC_DT)
            
            _log("Initializing detect pin manager...")
            self.detect = DetectPinManager(DETECT_PIN)
            
            _log("Hardware components initialized successfully")
        except Exception as e:
            print(f"[ERROR] Hardware initialization failed: {str(e)}")
            self.cleanup()
            raise

    def get_initial_volume(self):
        if self.volume:
            initial_volume = self.volume.normalize_value(self.volume.pot.value)
            _log(f"Getting initial volume: {initial_volume:.3f}")
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
                _log(f"Volume update - Previous: {self.last_volume:.3f}, New: {new_volume:.3f}")
                audio_system.set_volume(new_volume)
                self.last_volume = new_volume
            self.last_volume_scan = current_time

    def check_encoder(self, connection_manager, router_manager):
        current_time = time.monotonic()
        if current_time - self.last_encoder_scan >= ENCODER_SCAN_INTERVAL:
            events = self.read_encoder()
            valid_states = [ConnectionState.STANDALONE, ConnectionState.CONNECTED]
            current_state = connection_manager.state
            
            if current_state in valid_states and events:
                for event_type, direction in events:
                    if event_type == 'instrument_change':
                        instruments = router_manager.get_available_instruments()
                        current_idx = instruments.index(router_manager.current_instrument)
                        new_idx = (current_idx + direction) % len(instruments)
                        new_instrument = instruments[new_idx]
                        
                        if router_manager.set_instrument(new_instrument):
                            if current_state == ConnectionState.CONNECTED:
                                connection_manager.send_config()
                            
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
