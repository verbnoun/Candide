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
    def __init__(self, text_uart, midi_interface, hardware_manager):
        if text_uart is None or midi_interface is None or hardware_manager is None:
            raise ValueError("Required arguments cannot be None")
        
        log(TAG_CONNECT, "Setting uart, midi_interface")
        self.uart = text_uart
        self.midi = midi_interface
        self.hardware = hardware_manager
        
        log(TAG_CONNECT, "Initializing state variables ...")
        self.state = ConnectionState.STANDALONE
        self.last_heartbeat_time = 0
        self.last_detection_time = 0
        self._observers = []
        
        log(TAG_CONNECT, "Candide connection manager initialized")

    def add_observer(self, observer):
        """Add an observer to be notified of connection state changes."""
        self._observers.append(observer)
        
    def remove_observer(self, observer):
        """Remove an observer."""
        if observer in self._observers:
            self._observers.remove(observer)

    def update_state(self):
        """Update connection state and notify observers of changes."""
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

    def send_config(self, config_string):
        """Send CC configuration to Bartleby."""
        try:
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

    def _notify_state_change(self, new_state):
        """Notify observers of connection state change."""
        for observer in self._observers:
            observer.on_connection_state_change(new_state)

    def _transition_to_connected(self):
        """Helper to transition to connected state."""
        log(TAG_CONNECT, "[STATE] STANDALONE -> CONNECTED: Starting heartbeat")
        self.state = ConnectionState.CONNECTED
        self._notify_state_change(ConnectionState.CONNECTED)

    def _handle_initial_detection(self):
        """Handle initial base station detection."""
        log(TAG_CONNECT, "[STATE] STANDALONE -> DETECTED: Base station detected (GP22 HIGH) - initializing connection")
        self._notify_state_change(ConnectionState.DETECTED)
        
    def _handle_disconnection(self):
        """Handle base station disconnection."""
        log(TAG_CONNECT, "Base station disconnected (GP22 LOW)")
        old_state = self.state
        self.state = ConnectionState.STANDALONE
        self.last_heartbeat_time = 0
        if old_state != ConnectionState.STANDALONE:
            self._notify_state_change(ConnectionState.STANDALONE)
            
    def _send_heartbeat(self):
        """Send heartbeat if still connected."""
        # Only send heartbeat if still detected
        if self.hardware.is_base_station_detected():
            if self._send_message("♡"):
                log(TAG_CONNECT, "♡", is_heartbeat=True)

    def is_connected(self):
        """Check if currently connected to base station."""
        return self.state == ConnectionState.CONNECTED

    def cleanup(self):
        """Clean up resources when shutting down."""
        log(TAG_CONNECT, "Cleaning up connection manager resources")
        try:
            self.state = ConnectionState.STANDALONE
            self._observers.clear()
            self.uart = None
            self.midi = None
            self.hardware = None
        except Exception as e:
            log(TAG_CONNECT, f"Connection manager cleanup error: {str(e)}", is_error=True)
