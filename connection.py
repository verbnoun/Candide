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
        self._state_observers = []  # Observers for connection state
        self.path_parser = None  # Reference to router for config string
        
        log(TAG_CONNECT, "Candide connection manager initialized")

    def set_path_parser(self, path_parser):
        """Set reference to router for config string generation."""
        self.path_parser = path_parser

    def add_state_observer(self, observer):
        """Add an observer to be notified of connection state changes."""
        self._state_observers.append(observer)
        
    def remove_state_observer(self, observer):
        """Remove an observer."""
        if observer in self._state_observers:
            self._state_observers.remove(observer)

    def update_state(self):
        """Update connection state and notify observers of changes."""
        is_detected = self.hardware.is_base_station_detected()  # Checks GP22
        current_time = time.monotonic()
        
        # Handle disconnection in any state
        if not is_detected:
            if self.state != ConnectionState.STANDALONE:
                self._handle_disconnection()
            return
            
        # Handle connection states
        if self.state == ConnectionState.STANDALONE:
            # Rate limit detection attempts
            if current_time - self.last_detection_time >= DETECTION_RETRY_INTERVAL:
                self._handle_initial_detection()
                self.last_detection_time = current_time
                
        elif self.state == ConnectionState.DETECTED:
            # Already detected, waiting for connection completion
            pass
                
        elif self.state == ConnectionState.CONNECTED:
            # Send heartbeat if needed
            if current_time - self.last_heartbeat_time >= HEARTBEAT_INTERVAL:
                self._send_heartbeat()

    def _send_message(self, message, is_heartbeat=False):
        """Send complete message with newline."""
        try:
            # Only log non-heartbeat messages
            if not is_heartbeat:
                log(TAG_CONNECT, f"UART TX: {message}")
                
            # Ensure message ends with newline
            if not message.endswith('\n'):
                message += '\n'
                
            # Send complete message
            self.uart.write(message)
            
            # Only update heartbeat time for regular heartbeats
            if is_heartbeat and message == "♡\n":
                self.last_heartbeat_time = time.monotonic()
                
            return True
            
        except Exception as e:
            log(TAG_CONNECT, f"Failed to send message: {str(e)}", is_error=True)
            return False

    def _send_rapid_hearts(self):
        """Send 7 hearts as fast as possible."""
        try:
            log(TAG_CONNECT, "Sending 7 rapid hearts")
            for _ in range(7):
                # Send heart without affecting heartbeat timing
                if not self.uart.write("♡\n"):
                    return False
            return True
        except Exception as e:
            log(TAG_CONNECT, f"Failed to send rapid hearts: {str(e)}", is_error=True)
            return False

    def send_config(self):
        """Send CC configuration to Bartleby. Can be called by:
        1. Handshake (_handle_initial_detection)
        2. Synth setup (during instrument changes)"""
        try:
            # Send 7 rapid hearts before config
            # if not self._send_rapid_hearts():
            #     return False
            
            # Pull config string from router
            if not self.path_parser:
                log(TAG_CONNECT, "No path parser available", is_error=True)
                return False
                
            config_string = self.path_parser.get_cc_configs()
            
            if not config_string or config_string == "Candide|cc|":
                # Send blank CC config when no mappings exist
                config_string = "cc|"
                log(TAG_CONNECT, "Preparing blank config")
            else:
                log(TAG_CONNECT, f"Preparing config string: {config_string}")
            
            # Just send config - no state transition
            return self._send_message(config_string)
                
        except Exception as e:
            log(TAG_CONNECT, f"Failed to send config: {str(e)}", is_error=True)
        return False

    def _notify_state_change(self, new_state):
        """Notify observers of connection state change."""
        for observer in self._state_observers:
            observer.on_connection_state_change(new_state)

    def _transition_to_connected(self):
        """Helper to transition to connected state."""
        if self.state != ConnectionState.CONNECTED:
            log(TAG_CONNECT, "[STATE] -> CONNECTED: Starting heartbeat")
            self.state = ConnectionState.CONNECTED
            self._notify_state_change(ConnectionState.CONNECTED)

    def _handle_initial_detection(self):
        """Handle initial base station detection."""
        if self.state == ConnectionState.STANDALONE:
            log(TAG_CONNECT, "[STATE] STANDALONE -> DETECTED: Base station detected (GP22 HIGH)")
            self.state = ConnectionState.DETECTED
            self._notify_state_change(ConnectionState.DETECTED)
            
            # For initial detection: send config and transition if successful
            if self.send_config():
                self._transition_to_connected()
        
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
            if self._send_message("♡", is_heartbeat=True):
                log(TAG_CONNECT, "♡", is_heartbeat=True)

    def is_connected(self):
        """Check if currently connected to base station."""
        return self.state == ConnectionState.CONNECTED

    def get_state(self):
        """Get current connection state."""
        return self.state

    def cleanup(self):
        """Clean up resources when shutting down."""
        log(TAG_CONNECT, "Cleaning up connection manager resources")
        try:
            self.state = ConnectionState.STANDALONE
            self._state_observers.clear()
            self.uart = None
            self.midi = None
            self.hardware = None
            self.path_parser = None
        except Exception as e:
            log(TAG_CONNECT, f"Connection manager cleanup error: {str(e)}", is_error=True)
