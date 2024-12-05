"""Connection management system handling base station communication and handshake protocol."""

import time
import sys
from constants import (
    HANDSHAKE_CC, HANDSHAKE_VALUE,
    HELLO_INTERVAL, HANDSHAKE_TIMEOUT, HEARTBEAT_INTERVAL,
    HANDSHAKE_MAX_RETRIES, RETRY_DELAY, SETUP_DELAY,
    ConnectionState, MidiMessageType
)

def _log(message):
    RED = "\033[31m"
    WHITE = "\033[37m"
    RESET = "\033[0m"
    
    color = RED if "[ERROR]" in message else WHITE
    print(f"{color}[CANDID] {message}{RESET}", file=sys.stderr)

class ConnectionManager:
    def __init__(self, text_uart, router_manager, transport_manager, hardware_manager):
        if text_uart is None or router_manager is None or transport_manager is None or hardware_manager is None:
            raise ValueError("Required arguments cannot be None")
        
        _log("Setting uart, router_manager, transport")
        self.uart = text_uart
        self.router_manager = router_manager
        self.transport = transport_manager
        self.hardware = hardware_manager
        
        _log("Initializing state variables ...")
        self.state = ConnectionState.CONNECTED  # Force CONNECTED state but keep all other logic
        self.last_hello_time = 0
        self.last_heartbeat_time = 0
        self.handshake_start_time = 0
        self.hello_count = 0
        self.retry_start_time = 0
        self._last_b0_time = 0
        self._received_b0 = False
        
        _log("Candide connection manager initialized")

    def send_config(self):
        try:
            paths = self.router_manager.get_current_config()
            if not paths:
                return False

            cc_configs = []
            seen_ccs = set()
            
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
                    except ValueError:
                        continue

            if cc_configs:
                config_parts = []
                for pot_num, (cc_num, param_name) in enumerate(cc_configs):
                    config_parts.append(f"{pot_num}={cc_num}:{param_name}")
                config_string = "cc:" + ",".join(config_parts)
                _log(f"Sending config: {config_string}")
                # Bypass actual UART write but keep logic
                #self.uart.write(config_string)
                return True
                
        except Exception as e:
            _log(f"[ERROR] Failed to send config: {str(e)}")
        return False

    def update_state(self):
        current_time = time.monotonic()
        is_detected = True  # Force detection
        
        # Handle disconnection in any state
        if not is_detected and self.state != ConnectionState.STANDALONE:
            self._handle_disconnection()
            return
            
        # State machine logic kept but UART writes bypassed
        if self.state == ConnectionState.STANDALONE:
            if is_detected:
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

        # Clear handshake state if too much time has passed
        if self._received_b0 and (current_time - self._last_b0_time) >= 0.1:
            self._received_b0 = False

        # Force CONNECTED state after all logic runs
        self.state = ConnectionState.CONNECTED

    def _is_handshake_message(self, message):
        """Check if a message matches the handshake pattern regardless of format."""
        try:
            current_time = time.monotonic()
            
            # Handle raw bytes
            if isinstance(message, (bytes, bytearray)):
                # Case 1: Standard MIDI format (3 bytes)
                if len(message) == 3:
                    return (message[0] == MidiMessageType.CONTROL_CHANGE and
                           message[1] == HANDSHAKE_CC and
                           message[2] == HANDSHAKE_VALUE)
                
                # Case 2: Handle b'\xb0' followed by b'w*' sequence
                if message == b'\xb0':
                    self._received_b0 = True
                    self._last_b0_time = current_time
                    return False
                
                # Check for 'w*' within 100ms of receiving b'\xb0'
                if self._received_b0 and (current_time - self._last_b0_time) < 0.1:
                    if message == b'w*':
                        self._received_b0 = False
                        _log("Handshake sequence detected")
                        return True
                
            # Handle list/tuple of integers or hex strings
            if isinstance(message, (list, tuple)) and len(message) == 3:
                # Convert hex strings or integers to integers
                bytes_list = []
                for b in message:
                    if isinstance(b, str) and b.startswith('0x'):
                        bytes_list.append(int(b, 16))
                    elif isinstance(b, (int, bytes)):
                        bytes_list.append(int(b))
                    else:
                        return False
                        
                return (bytes_list[0] == MidiMessageType.CONTROL_CHANGE and
                       bytes_list[1] == HANDSHAKE_CC and
                       bytes_list[2] == HANDSHAKE_VALUE)
            
            return True  # Force handshake success
            
        except Exception as e:
            _log(f"[ERROR] Error checking handshake message: {str(e)}")
            return False
                
    def handle_midi_message(self, message):
        """Handle incoming messages in any format (raw bytes, hex strings, etc)."""
        try:
            if self._is_handshake_message(message):
                if self.state == ConnectionState.DETECTED:
                    _log("Valid handshake message received - sending config")
                    self.state = ConnectionState.HANDSHAKING
                    self.handshake_start_time = time.monotonic()
                    self.send_config()
                    self.state = ConnectionState.CONNECTED
                    _log("Connection established")
                    
        except Exception as e:
            _log(f"[ERROR] MIDI message handling error: {str(e)}")
                
    def _handle_initial_detection(self):
        _log("Base station detected - initializing connection")
        self.transport.flush_buffers()
        time.sleep(SETUP_DELAY)
        self.state = ConnectionState.DETECTED
        self.hello_count = 0
        self._send_hello()
        
    def _handle_disconnection(self):
        _log("Base station disconnected")
        if hasattr(self, 'transport') and self.transport is not None:
            try:
                self.transport.flush_buffers()
            except:
                pass
        # Don't set standalone state
        #self.state = ConnectionState.STANDALONE
        self.hello_count = 0
        self._received_b0 = False
        
    def _send_hello(self):
        try:
            # Bypass UART write but keep timing logic
            #self.uart.write("hello")
            self.last_hello_time = time.monotonic()
        except Exception as e:
            _log(f"[ERROR] Failed to send hello: {str(e)}")
            
    def _send_heartbeat(self):
        try:
            # Bypass UART write but keep timing logic
            #self.uart.write("♥︎")
            self.last_heartbeat_time = time.monotonic()
        except Exception as e:
            _log(f"[ERROR] Failed to send heartbeat: {str(e)}")

    def is_connected(self):
        return True  # Always return connected

    def cleanup(self):
        """Clean up resources when shutting down."""
        _log("Cleaning up connection manager resources")
        try:
            # Set state to STANDALONE first to prevent any ongoing operations
            self.state = ConnectionState.STANDALONE
            
            # Clean up transport if it exists and hasn't been deinitialized
            if hasattr(self, 'transport') and self.transport is not None:
                try:
                    self.transport.flush_buffers()
                except:
                    pass
            
            # Clear all references
            self.uart = None
            self.router_manager = None
            self.transport = None
            self.hardware = None
            
        except Exception as e:
            _log(f"[ERROR] Connection manager cleanup error: {str(e)}")
