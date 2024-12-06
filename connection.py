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

class ConnectionManager:
    def __init__(self, text_uart, router_manager, midi_interface, hardware_manager):
        if text_uart is None or router_manager is None or midi_interface is None or hardware_manager is None:
            raise ValueError("Required arguments cannot be None")
        
        _log("Setting uart, router_manager, midi_interface")
        self.uart = text_uart
        self.router_manager = router_manager
        self.midi = midi_interface
        self.hardware = hardware_manager
        
        _log("Initializing state variables ...")
        self.state = ConnectionState.STANDALONE
        self.last_heartbeat_time = 0
        
        # Set initial instrument to envelope_minimum for CC controls
        if hasattr(self.router_manager, 'set_instrument'):
            _log("Setting instrument to envelope_minimum")
            if self.router_manager.set_instrument('envelope_minimum'):
                _log("Successfully set instrument to envelope_minimum")
            else:
                _log("[ERROR] Failed to set instrument to envelope_minimum")
        
        _log("Candide connection manager initialized")

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
                self._handle_initial_detection()
                
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
        try:
            # Get current config from router manager
            _log("Getting current config from router manager")
            paths = self.router_manager.get_current_config()
            if not paths:
                _log("[ERROR] No config paths available")
                return False

            _log(f"Processing config paths:\n{paths}")
            cc_configs = []
            seen_ccs = set()
            
            # Parse config paths for CC mappings
            for line in paths.strip().split('\n'):
                if not line:
                    continue
                    
                parts = line.split('/')
                scope_idx = -1
                for i, part in enumerate(parts):
                    if part in ('global', 'per_key'):
                        scope_idx = i
                        break
                        
                if scope_idx == -1:
                    continue

                midi_type = parts[-1]
                if midi_type.startswith('cc'):
                    try:
                        cc_num = int(midi_type[2:])
                        if cc_num not in seen_ccs:
                            param_name = parts[scope_idx - 1]
                            cc_configs.append((cc_num, param_name))
                            seen_ccs.add(cc_num)
                            _log(f"Found CC mapping: {cc_num} -> {param_name}")
                    except ValueError:
                        continue

            if cc_configs:
                # Build config string: cc|pot=cc|pot=cc|...
                config_parts = []
                for pot_num, (cc_num, param_name) in enumerate(cc_configs):
                    config_parts.append(f"{pot_num}={cc_num}")
                
                config_string = "cc|" + "|".join(config_parts)
                _log(f"Sending config string: {config_string}")
                
                # Send config
                self.uart.write(config_string)
                _log("Config sent successfully")
                
                # Immediately transition to CONNECTED and start heartbeat
                _log("Starting heartbeat", "STANDALONE -> CONNECTED")
                self.state = ConnectionState.CONNECTED
                self._send_heartbeat()
                self.last_heartbeat_time = time.monotonic()
                return True
            else:
                _log("[ERROR] No CC configurations generated")
                return False
                
        except Exception as e:
            _log(f"[ERROR] Failed to send config: {str(e)}")
        return False

    def _handle_initial_detection(self):
        _log("Base station detected (GP22 HIGH) - initializing connection", "STANDALONE -> DETECTED")
        self.send_config()
        
    def _handle_disconnection(self):
        _log("Base station disconnected (GP22 LOW)")
        self.state = ConnectionState.STANDALONE
        self.last_heartbeat_time = 0
            
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
            self.router_manager = None
            self.midi = None
            self.hardware = None
        except Exception as e:
            _log(f"[ERROR] Connection manager cleanup error: {str(e)}")
