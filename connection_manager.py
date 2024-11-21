"""
Connection Management System for Candide Synthesizer

Handles connection state and handshake protocol with base station.
Validates handshake MIDI messages and manages connection state.
"""

import time
import sys
import digitalio
from constants import (
    DETECT_PIN, HANDSHAKE_CC, HANDSHAKE_VALUE,
    HELLO_INTERVAL, HANDSHAKE_TIMEOUT, HEARTBEAT_INTERVAL,
    HANDSHAKE_MAX_RETRIES, RETRY_DELAY, SETUP_DELAY
)

def _log(message):
    """Conditional logging with consistent formatting"""
    RED = "\033[31m"
    WHITE = "\033[37m"
    RESET = "\033[0m"
    
    color = RED if "[ERROR]" in message else WHITE
    print(f"{color}[CANDID] {message}{RESET}", file=sys.stderr)

class ConnectionState:
    """Connection states for base station communication"""
    STANDALONE = "standalone"
    DETECTED = "detected"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"
    RETRY_DELAY = "retry_delay"

class CandideConnectionManager:
    """Manages connection state and handshake protocol"""
    
    def __init__(self, text_uart, synth_manager, transport_manager):
        self.uart = text_uart
        self.synth_manager = synth_manager
        self.transport = transport_manager
        
        # Initialize detection pin
        self.detect_pin = digitalio.DigitalInOut(DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        # Initialize state variables
        self.state = ConnectionState.STANDALONE
        self.last_hello_time = 0
        self.last_heartbeat_time = 0
        self.handshake_start_time = 0
        self.hello_count = 0
        self.retry_start_time = 0
        
        _log("Candide connection manager initialized")
        
    def update_state(self):
        """Update connection state based on current conditions"""
        current_time = time.monotonic()
        
        if not self.detect_pin.value:
            if self.state != ConnectionState.STANDALONE:
                self._handle_disconnection()
            return
            
        if self.state == ConnectionState.STANDALONE and self.detect_pin.value:
            self._handle_initial_detection()
            
        elif self.state == ConnectionState.DETECTED:
            if current_time - self.last_hello_time >= HELLO_INTERVAL:
                if self.hello_count < HANDSHAKE_MAX_RETRIES:
                    self._send_hello()
                    self.hello_count += 1
                else:
                    _log("Max hello retries reached - entering retry delay")
                    self.state = ConnectionState.RETRY_DELAY
                    self.retry_start_time = current_time
                    self.hello_count = 0
                    
        elif self.state == ConnectionState.RETRY_DELAY:
            if current_time - self.retry_start_time >= RETRY_DELAY:
                _log("Retry delay complete - returning to DETECTED state")
                self.state = ConnectionState.DETECTED
                
        elif self.state == ConnectionState.HANDSHAKING:
            if current_time - self.handshake_start_time >= HANDSHAKE_TIMEOUT:
                _log("Handshake timeout - returning to DETECTED state")
                self.state = ConnectionState.DETECTED
                self.hello_count = 0
                
        elif self.state == ConnectionState.CONNECTED:
            if current_time - self.last_heartbeat_time >= HEARTBEAT_INTERVAL:
                self._send_heartbeat()
                
    def handle_midi_message(self, event):
        """Handle MIDI messages for handshake validation"""
        # Only process CC messages during handshake
        if not event or event['type'] != 'cc':
            return
            
        # Check for handshake CC on channel 0
        if (event['channel'] == 0 and 
            event['data']['number'] == HANDSHAKE_CC):
            
            # Validate handshake value when in DETECTED state
            if (event['data']['value'] == HANDSHAKE_VALUE and 
                self.state == ConnectionState.DETECTED):
                _log("Handshake CC received - sending config")
                self.state = ConnectionState.HANDSHAKING
                self.handshake_start_time = time.monotonic()
                config_str = self.synth_manager.format_cc_config()
                self.uart.write(f"{config_str}\n")
                self.state = ConnectionState.CONNECTED
                _log("Connection established")
                
    def _handle_initial_detection(self):
        """Handle initial base station detection"""
        _log("Base station detected - initializing connection")
        self.transport.flush_buffers()
        time.sleep(SETUP_DELAY)
        self.state = ConnectionState.DETECTED
        self.hello_count = 0
        self._send_hello()
        
    def _handle_disconnection(self):
        """Handle base station disconnection"""
        _log("Base station disconnected")
        self.transport.flush_buffers()
        self.state = ConnectionState.STANDALONE
        self.hello_count = 0
        
    def _send_hello(self):
        """Send hello message to base station"""
        try:
            self.uart.write("hello\n")
            self.last_hello_time = time.monotonic()
        except Exception as e:
            _log(f"[ERROR] Failed to send hello: {str(e)}")
            
    def _send_heartbeat(self):
        """Send heartbeat message to base station"""
        try:
            self.uart.write("♥︎\n")
            self.last_heartbeat_time = time.monotonic()
        except Exception as e:
            _log(f"[ERROR] Failed to send heartbeat: {str(e)}")
            
    def cleanup(self):
        """Clean up resources"""
        if self.detect_pin:
            self.detect_pin.deinit()

    def is_connected(self):
        """Check if currently connected to base station"""
        return self.state == ConnectionState.CONNECTED
