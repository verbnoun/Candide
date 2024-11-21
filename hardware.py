"""
Hardware Interface Management Module

This module provides essential hardware interaction capabilities 
for the Candide Synthesizer, enabling direct interface with 
physical input components.

Key Responsibilities:
- Manage analog input from potentiometers
- Handle rotary encoder interactions
- Provide normalized hardware input processing
- Support hardware-level configuration and constants
- Enable precise input reading and filtering

Primary Classes:
- HardwareComponent: Base class for hardware components
- VolumeManager: Manages volume potentiometer
- EncoderManager: Manages instrument selection encoder
- HardwareManager: Coordinates hardware components
"""

import board
import analogio
import rotaryio
from constants import *

class HardwareComponent:
    """Base class for hardware components"""
    def __init__(self):
        self.is_active = False
        
    def cleanup(self):
        """Clean shutdown of hardware component"""
        pass

class VolumeManager(HardwareComponent):
    """Manages volume potentiometer functionality"""
    def __init__(self, pin):
        super().__init__()
        self.pot = analogio.AnalogIn(pin)
        self.last_value = 0
    
    def normalize_value(self, value):
        """Convert ADC value to normalized range (0.0-1.0)"""
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
        """Read and process potentiometer value"""
        raw_value = self.pot.value
        change = abs(raw_value - self.last_value)

        if self.is_active:
            if change != 0:
                normalized_new = self.normalize_value(raw_value)
                self.last_value = raw_value
                return normalized_new
            elif change < POT_THRESHOLD:
                self.is_active = False
        elif change > POT_THRESHOLD:
            self.is_active = True
            normalized_new = self.normalize_value(raw_value)
            self.last_value = raw_value
            return normalized_new
            
        return None
        
    def cleanup(self):
        """Clean shutdown of potentiometer"""
        if self.pot:
            self.pot.deinit()

class EncoderManager(HardwareComponent):
    """Manages instrument selection encoder functionality"""
    def __init__(self, clk_pin, dt_pin):
        super().__init__()
        self.encoder = rotaryio.IncrementalEncoder(clk_pin, dt_pin, divisor=2)
        self.last_position = 0
        self.current_position = 0
        self.reset_position()

    def reset_position(self):
        """Reset encoder to initial state"""
        self.encoder.position = 0
        self.last_position = 0
        self.current_position = 0

    def read(self):
        """Read encoder and return events if position changed"""
        events = []
        current_raw_position = self.encoder.position
        
        if current_raw_position != self.last_position:
            direction = 1 if current_raw_position > self.last_position else -1

            if HARDWARE_DEBUG:
                print(f"Encoder movement: pos={current_raw_position}, last={self.last_position}, dir={direction}")
            
            events.append(('instrument_change', direction))
            self.last_position = current_raw_position
        
        return events

class HardwareManager:
    """Coordinates hardware component interactions"""
    def __init__(self):
        self.volume = None
        self.encoder = None
        self._initialize_components()

    def _initialize_components(self):
        """Initialize all hardware components"""
        try:
            self.volume = VolumeManager(VOLUME_POT)
            self.encoder = EncoderManager(INSTRUMENT_ENC_CLK, INSTRUMENT_ENC_DT)
        except Exception as e:
            print(f"[ERROR] Hardware initialization failed: {str(e)}")
            self.cleanup()
            raise

    def get_initial_volume(self):
        """Get initial normalized volume setting"""
        if self.volume:
            return self.volume.normalize_value(self.volume.pot.value)
        return 0.0

    def read_encoder(self):
        """Read encoder state"""
        if self.encoder:
            return self.encoder.read()
        return []

    def read_volume(self):
        """Read volume potentiometer state"""
        if self.volume:
            return self.volume.read()
        return None
        
    def cleanup(self):
        """Clean shutdown of all hardware components"""
        if self.encoder:
            self.encoder.cleanup()
            self.encoder = None
            
        if self.volume:
            self.volume.cleanup()
            self.volume = None
