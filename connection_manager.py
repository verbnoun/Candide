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
    
    def __init__(self, text_uart, router_manager, transport_manager):
        """Initialize connection manager.
        
        Args:
            text_uart: Text protocol for communication
            router_manager: Router manager for instrument routing 
            transport_manager: Transport manager for MIDI
        """
        if text_uart is None or router_manager is None or transport_manager is None:
            raise ValueError("Required arguments cannot be None")
        
        _log("Setting uart, router_manager, transport")
        self.uart = text_uart
        self.router_manager = router_manager
        self.transport = transport_manager
        
        # Initialize detection pin
        _log("Initializing detection pin ...")
        self.detect_pin = digitalio.DigitalInOut(DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        # Initialize state variables 
        _log("Initializing state variables ...")
        self.state = ConnectionState.STANDALONE
        self.last_hello_time = 0
        self.last_heartbeat_time = 0
        self.handshake_start_time = 0
        self.hello_count = 0
        self.retry_start_time = 0
        
        _log("Candide connection manager initialized")

    def send_config(self):
        """Send current instrument config to base station"""
        try:
            paths = self.router_manager.get_current_config()
            if not paths:
                return False

            # Parse paths for CC numbers and names
            cc_configs = []
            seen_ccs = set()
            
            # Process each path
            for line in paths.strip().split('\n'):
                if not line:
                    continue
                    
                parts = line.split('/')
                # Find the CC number and corresponding parameter name
                for i, part in enumerate(parts):
                    if part.startswith('cc') and len(part) > 2:
                        try:
                            cc_num = int(part[2:])
                            if cc_num not in seen_ccs:
                                # Get parameter name from previous part in path
                                param_name = parts[i-2]  
                                cc_configs.append((cc_num, param_name))
                                seen_ccs.add(cc_num)
                                if len(cc_configs) >= 14:  # Limit to 14 pots
                                    break
                        except ValueError:
                            continue
                if len(cc_configs) >= 14:
                    break

            # Generate config string
            if cc_configs:
                config_parts = []
                for pot_num, (cc_num, param_name) in enumerate(cc_configs):
                    config_parts.append(f"{pot_num}={cc_num}:{param_name}")
                config_string = "cc:" + ",".join(config_parts) + "\n"
                _log(f"Sending config: {config_string.strip()}")  # Log the config being sent
                self.uart.write(config_string)
                return True
                
        except Exception as e:
            _log(f"[ERROR] Failed to send config: {str(e)}")
        return False

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
        try:
            # Only process CC messages during handshake
            if not event or not isinstance(event, dict) or event.get('type') != 'cc':
                return
                
            # Check for handshake CC on channel 0
            if (event.get('channel') == 0 and 
                event.get('data', {}).get('number') == HANDSHAKE_CC):
                
                # Validate handshake value when in DETECTED state
                if (event.get('data', {}).get('value') == HANDSHAKE_VALUE and 
                    self.state == ConnectionState.DETECTED):
                    _log("Handshake CC received - sending config")
                    self.state = ConnectionState.HANDSHAKING
                    self.handshake_start_time = time.monotonic()
                    self.send_config()
                    self.state = ConnectionState.CONNECTED
                    _log("Connection established")
                    
        except Exception as e:
            _log(f"[ERROR] MIDI message handling error: {str(e)}")
                
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