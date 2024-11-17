import board
import analogio
import rotaryio

class Constants:
    # Debug Settings
    DEBUG = False
    
    # ADC Constants
    ADC_MAX = 65535
    ADC_MIN = 1
    
    # Pin Definitions
    INSTRUMENT_ENC_CLK = board.GP20
    INSTRUMENT_ENC_DT = board.GP21
    VOLUME_POT = board.GP26
    
    # Timing Intervals
    UPDATE_INTERVAL = 0.01
    ENCODER_SCAN_INTERVAL = 0.001
    
    # Potentiometer Constants
    POT_THRESHOLD = 800
    POT_LOWER_TRIM = 0.05
    POT_UPPER_TRIM = 0.0

class VolumePotHandler:
    def __init__(self, pin):
        self.pot = analogio.AnalogIn(pin)
        self.last_value = 0
        self.is_active = False
    
    def normalize_value(self, value):
        """Convert ADC value to normalized range (0.0-1.0)"""
        clamped_value = max(min(value, Constants.ADC_MAX), Constants.ADC_MIN)
        normalized = (clamped_value - Constants.ADC_MIN) / (Constants.ADC_MAX - Constants.ADC_MIN)
        
        if normalized < Constants.POT_LOWER_TRIM:
            normalized = 0
        elif normalized > (1 - Constants.POT_UPPER_TRIM):
            normalized = 1
        else:
            normalized = (normalized - Constants.POT_LOWER_TRIM) / (1 - Constants.POT_LOWER_TRIM - Constants.POT_UPPER_TRIM)
        
        return round(normalized, 5)

    def read_pot(self):
        """Read and process potentiometer value"""
        raw_value = self.pot.value
        change = abs(raw_value - self.last_value)

        if self.is_active:
            if change != 0:
                normalized_new = self.normalize_value(raw_value)
                self.last_value = raw_value
                return normalized_new
            elif change < Constants.POT_THRESHOLD:
                self.is_active = False
        elif change > Constants.POT_THRESHOLD:
            self.is_active = True
            normalized_new = self.normalize_value(raw_value)
            self.last_value = raw_value
            return normalized_new
            
        return None

class RotaryEncoderHandler:
    def __init__(self, clk_pin, dt_pin):
        # Initialize encoder using rotaryio
        self.encoder = rotaryio.IncrementalEncoder(clk_pin, dt_pin, divisor=2)
        
        # Track state
        self.last_position = 0
        self.current_position = 0
        
        # Reset initial state
        self.reset_position()

    def reset_position(self):
        """Reset encoder to initial state"""
        self.encoder.position = 0
        self.last_position = 0
        self.current_position = 0

    def read_encoder(self):
        """Read encoder and return events if position changed"""
        events = []
        
        # Read current position
        current_raw_position = self.encoder.position
        
        # Check if the encoder position has changed
        if current_raw_position != self.last_position:
            # Calculate direction (-1 for left, +1 for right)
            direction = 1 if current_raw_position > self.last_position else -1

            if Constants.DEBUG:
                print(f"Encoder movement: pos={current_raw_position}, last={self.last_position}, dir={direction}")
            
            # Add event with direction
            events.append(('instrument_change', direction))
            
            # Update last_position for next read
            self.last_position = current_raw_position
        
        return events

    def cleanup(self):
        """Clean shutdown of hardware"""
        # No specific cleanup needed for encoder
        pass
