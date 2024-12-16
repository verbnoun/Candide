"""Connection management system handling base station communication and handshake protocol."""

import time
import sys
from constants import (
    HEARTBEAT_INTERVAL,
    ConnectionState,
    DETECT_PIN,
    DETECTION_RETRY_INTERVAL
)
from logging import log, TAG_CONNECT

class ConnectionManager:
    def __init__(self, text_uart, midi_interface, hardware_manager, instrument_manager):
        if text_uart is None or midi_interface is None or hardware_manager is None or instrument_manager is None:
            raise ValueError("Required arguments cannot be None")
        
        log(TAG_CONNECT, "Setting uart, midi_interface")
        self.uart = text_uart
        self.midi = midi_interface
        self.hardware = hardware_manager
        self.instrument_manager = instrument_manager
        
        log(TAG_CONNECT, "Initializing state variables ...")
        self.state = ConnectionState.STANDALONE
        self.last_heartbeat_time = 0
        self.last_detection_time = 0
        
        log(TAG_CONNECT, "Candide connection manager initialized")

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
            else:
                self._handle_disconnection()

    def _send_message(self, message):
        """Helper method to send messages and update heartbeat timer."""
        try:
            self.uart.write(message)
            self.last_heartbeat_time = time.monotonic()  # Any message counts as heartbeat
            return True
        except Exception as e:
            log(TAG_CONNECT, f"Failed to send message: {str(e)}", is_error=True)
            return False

    def send_config(self):
        """Send CC configuration to Bartleby."""
        try:
            # Get config string from instrument manager
            config_string = self.instrument_manager.get_current_cc_configs()
            
            if not config_string or config_string == "Candide|cc|":
                # Send blank CC config when no mappings exist
                config_string = "cc|"
                log(TAG_CONNECT, "No CC configurations found - sending blank config")
            else:
                log(TAG_CONNECT, f"Sending config string: {config_string}")
            
            # Send config
            if self._send_message(config_string):
                self._transition_to_connected()
                return True
                
        except Exception as e:
            log(TAG_CONNECT, f"Failed to send config: {str(e)}", is_error=True)
        return False

    def _transition_to_connected(self):
        """Helper to transition to connected state."""
        log(TAG_CONNECT, "[STATE] STANDALONE -> CONNECTED: Starting heartbeat")
        self.state = ConnectionState.CONNECTED

    def _handle_initial_detection(self):
        log(TAG_CONNECT, "[STATE] STANDALONE -> DETECTED: Base station detected (GP22 HIGH) - initializing connection")
        # Send current instrument config immediately
        if self.instrument_manager:
            self.send_config()
        
    def _handle_disconnection(self):
        log(TAG_CONNECT, "Base station disconnected (GP22 LOW)")
        self.state = ConnectionState.STANDALONE
        self.last_heartbeat_time = 0
            
    def _send_heartbeat(self):
        # Only send heartbeat if still detected
        if self.hardware.is_base_station_detected():
            if self._send_message("♡"):
                log(TAG_CONNECT, "♡", is_heartbeat=True)

    def is_connected(self):
        return self.state == ConnectionState.CONNECTED

    def cleanup(self):
        """Clean up resources when shutting down."""
        log(TAG_CONNECT, "Cleaning up connection manager resources")
        try:
            self.state = ConnectionState.STANDALONE
            self.uart = None
            self.midi = None
            self.hardware = None
            self.instrument_manager = None
        except Exception as e:
            log(TAG_CONNECT, f"Connection manager cleanup error: {str(e)}", is_error=True)
