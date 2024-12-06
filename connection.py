"""Connection management system handling base station communication and handshake protocol."""

import time
import sys
from constants import (
    HEARTBEAT_INTERVAL,
    HEARTBEAT_DEBUG,
    ConnectionState,
    DETECT_PIN
)

def _log(message, state=None):
    RED = "\033[31m"
    WHITE = "\033[37m"
    GREEN = "\033[32m"
    RESET = "\033[0m"
    
    if state:
        color = GREEN
        message = f"[STATE] {state}: {message}"
    else:
        color = RED if "[ERROR]" in message else WHITE
        message = f"[CONNCT] {message}"
    
    print(f"{color}{message}{RESET}", file=sys.stderr)

# Timing constants
CONFIG_RETRY_INTERVAL = 1.0  # Send config every 1s until we get pot data
POT_WAIT_TIMEOUT = 5.0  # Wait up to 5s for pot data response
DETECTION_RETRY_INTERVAL = 2.0  # Wait between detection attempts

class ConnectionManager:
    def __init__(self, text_uart, midi_interface, hardware_manager, instrument_manager):
        if text_uart is None or midi_interface is None or hardware_manager is None or instrument_manager is None:
            raise ValueError("Required arguments cannot be None")
        
        _log("Setting uart, midi_interface")
        self.uart = text_uart
        self.midi = midi_interface
        self.hardware = hardware_manager
        self.instrument_manager = instrument_manager
        
        _log("Initializing state variables ...")
        self.state = ConnectionState.STANDALONE
        self.last_heartbeat_time = 0
        self.last_detection_time = 0
        self.synth_ready = False
        self.waiting_for_synth = False
        
        _log("Candide connection manager initialized")

    def on_synth_ready(self):
        """Called when synthesizer is ready for MIDI messages."""
        _log("Synthesizer signaled ready state")
        self.synth_ready = True
        self.waiting_for_synth = False
        self.send_config()

    def update_state(self):
        is_detected = self.hardware.is_base_station_detected()  # Checks GP22
        current_time = time.monotonic()
        
        # Handle disconnection in any state
        if not is_detected and self.state != ConnectionState.STANDALONE:
            self._handle_disconnection()
            return
            
        # Handle connection and config sending
        if self.state == ConnectionState.STANDALONE:
            if is_detected:
                # Rate limit detection attempts
                if current_time - self.last_detection_time >= DETECTION_RETRY_INTERVAL:
                    self._handle_initial_detection()
                    self.last_detection_time = current_time
                
        elif self.state == ConnectionState.CONNECTED:
            # Only send heartbeat if GP22 is still high
            if is_detected:
                if current_time - self.last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    self._send_heartbeat()
                    self.last_heartbeat_time = current_time
            else:
                self._handle_disconnection()

    def send_config(self):
        """Send CC configuration to Bartleby."""
        if not self.synth_ready:
            if not self.waiting_for_synth:
                _log("Waiting for synthesizer to be ready before sending config")
                self.waiting_for_synth = True
            return False

        try:
            # Get CC configurations from instrument manager
            cc_configs = self.instrument_manager.get_current_cc_configs()
            
            # Send config string - either with CC mappings or blank
            if cc_configs:
                # Build config string: cc|pot=cc|pot=cc|...
                config_parts = []
                for pot_num, (cc_num, param_name) in enumerate(cc_configs):
                    config_parts.append(f"{pot_num}={cc_num}")
                
                config_string = "cc|" + "|".join(config_parts)
                _log(f"Sending config string: {config_string}")
            else:
                # Send blank CC config when no mappings exist
                config_string = "cc|"
                _log("No CC configurations found - sending blank config")
            
            # Send config
            self.uart.write(config_string)
            _log("Config sent successfully")
            
            self._transition_to_connected()
            return True
                
        except Exception as e:
            _log(f"[ERROR] Failed to send config: {str(e)}")
        return False

    def _transition_to_connected(self):
        """Helper to transition to connected state and start heartbeat."""
        _log("Starting heartbeat", "STANDALONE -> CONNECTED")
        self.state = ConnectionState.CONNECTED
        self._send_heartbeat()
        self.last_heartbeat_time = time.monotonic()

    def _handle_initial_detection(self):
        _log("Base station detected (GP22 HIGH) - initializing connection", "STANDALONE -> DETECTED")
        # Reset synth ready state on new detection
        self.synth_ready = False
        self.waiting_for_synth = False
        # Request current instrument config
        if self.instrument_manager:
            current = self.instrument_manager.current_instrument
            self.instrument_manager.set_instrument(current)
        
    def _handle_disconnection(self):
        _log("Base station disconnected (GP22 LOW)")
        self.state = ConnectionState.STANDALONE
        self.last_heartbeat_time = 0
        self.synth_ready = False
        self.waiting_for_synth = False
            
    def _send_heartbeat(self):
        try:
            # Only send heartbeat if still detected
            if self.hardware.is_base_station_detected():
                self.uart.write("♡")
                if HEARTBEAT_DEBUG:
                    _log("♡", "CONNECTED")
        except Exception as e:
            _log(f"[ERROR] Failed to send heartbeat: {str(e)}")

    def is_connected(self):
        return self.state == ConnectionState.CONNECTED

    def cleanup(self):
        """Clean up resources when shutting down."""
        _log("Cleaning up connection manager resources")
        try:
            self.state = ConnectionState.STANDALONE
            self.uart = None
            self.midi = None
            self.hardware = None
            self.instrument_manager = None
        except Exception as e:
            _log(f"[ERROR] Connection manager cleanup error: {str(e)}")
