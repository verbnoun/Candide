"""Connection management system handling base station communication and handshake protocol."""

import time
import sys
from adafruit_midi.control_change import ControlChange
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
    print(f"{color}[CONNCT] {message}{RESET}", file=sys.stderr)

class ConnectionManager:
    def __init__(self, text_uart, router_manager, midi_interface, hardware_manager):
        if text_uart is None or router_manager is None or midi_interface is None or hardware_manager is None:
            raise ValueError("Required arguments cannot be None")
        
        _log("Setting uart, router_manager, midi_interface")
        self.uart = text_uart
        self.router_manager = router_manager
        self.midi = midi_interface  # Store MIDI interface directly
        self.hardware = hardware_manager
        
        _log("Initializing state variables ...")
        self.state = ConnectionState.STANDALONE  # Start in standalone state
        self.last_hello_time = 0
        self.last_heartbeat_time = 0
        self.handshake_start_time = 0
        self.hello_count = 0
        self.retry_start_time = 0
        self._last_b0_time = 0
        self._received_b0 = False
        self.midi_subscription = None
        self.last_subscription_attempt = 0
        
        # Set initial instrument to envelope_minimum for CC controls
        if hasattr(self.router_manager, 'set_instrument'):
            _log("Setting instrument to envelope_minimum")
            if self.router_manager.set_instrument('envelope_minimum'):
                _log("Successfully set instrument to envelope_minimum")
            else:
                _log("[ERROR] Failed to set instrument to envelope_minimum")
        
        # Start listening for handshake CC
        self._subscribe_to_handshake()
        _log("Candide connection manager initialized")

    def _handle_handshake_cc(self, msg):
        """Callback for handshake CC messages"""
        try:
            _log(f"MIDI message received - Type: {type(msg).__name__}")
            
            # Immediately check pin state
            is_connected = self.hardware.is_base_station_detected()
            if not is_connected:
                _log("[ERROR] Cannot handle handshake - GP22 is LOW")
                return
            
            # Validate message type
            if not isinstance(msg, ControlChange):
                _log(f"[ERROR] Expected ControlChange message, got {type(msg).__name__}")
                return
                
            _log(f"CC details - Number: {msg.control}, Value: {msg.value}, Current State: {self.state}")
            
            # Double check we're still connected before proceeding with handshake
            if not self.hardware.is_base_station_detected():
                _log("[ERROR] Lost connection during handshake - GP22 went LOW")
                return
                
            # Validate CC number and value
            if msg.control != HANDSHAKE_CC:
                _log(f"[ERROR] Wrong CC number - Expected {HANDSHAKE_CC}, got {msg.control}")
                return
                
            if msg.value != HANDSHAKE_VALUE:
                _log(f"[ERROR] Wrong CC value - Expected {HANDSHAKE_VALUE}, got {msg.value}")
                return
                
            _log(f"Valid handshake CC received (cc:{msg.control}:{msg.value})")
            
            # Final connection check before state change
            if not self.hardware.is_base_station_detected():
                _log("[ERROR] Lost connection before state change - GP22 went LOW")
                return
                
            if self.state == ConnectionState.DETECTED:
                _log("Starting handshake sequence")
                self.state = ConnectionState.HANDSHAKING
                self.handshake_start_time = time.monotonic()
                
                # Send handshake response only if still connected
                if self.midi and self.hardware.is_base_station_detected():
                    self.midi.send(ControlChange(HANDSHAKE_CC, HANDSHAKE_VALUE))
                    _log("Handshake response sent")
                    
                    # Send config only if still connected
                    if self.hardware.is_base_station_detected():
                        _log("Sending config after handshake")
                        if self.send_config():
                            self.state = ConnectionState.CONNECTED
                            _log("Connection established")
                        else:
                            _log("[ERROR] Config send failed - returning to DETECTED")
                            self.state = ConnectionState.DETECTED
                            self.hello_count = 0
            elif self.state == ConnectionState.HANDSHAKING:
                _log("Already in handshaking state, ignoring duplicate handshake")
                
        except Exception as e:
            _log(f"[ERROR] Exception in handshake handler: {str(e)}")

    def _subscribe_to_handshake(self):
        """Subscribe to handshake CC messages"""
        current_time = time.monotonic()
        
        # Only attempt subscription if enough time has passed since last attempt
        if current_time - self.last_subscription_attempt < 1.0:
            return
            
        self.last_subscription_attempt = current_time
        
        if self.midi_subscription is None:
            if self.midi:
                try:
                    self.midi_subscription = self.midi.subscribe(
                        callback=self._handle_handshake_cc,
                        message_types=[ControlChange],
                        cc_numbers=[HANDSHAKE_CC]
                    )
                    _log(f"Successfully subscribed to CC {HANDSHAKE_CC} messages")
                except Exception as e:
                    _log(f"[ERROR] Failed to subscribe to MIDI messages: {str(e)}")
            else:
                _log("[ERROR] No MIDI interface available for subscription")

    def send_config(self):
        """
        Send current CC configuration to Bartleby.
        Can be called at any time to update pot mappings, not just during handshake.
        Bartleby will reset its pots when receiving this config.
        """
        try:
            # Verify GP22 is still high before sending config
            if not self.hardware.is_base_station_detected():
                _log("[ERROR] Cannot send config - GP22 is LOW")
                return False
                
            _log("Getting current config from router manager")
            paths = self.router_manager.get_current_config()
            if not paths:
                _log("[ERROR] No config paths available")
                return False

            _log(f"Processing config paths:\n{paths}")
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
                            _log(f"Found CC mapping: {cc_num} -> {param_name}")
                    except ValueError:
                        continue

            if cc_configs:
                config_parts = []
                for pot_num, (cc_num, param_name) in enumerate(cc_configs):
                    # Remove spaces to match Bartleby's expected format
                    config_parts.append(f"{pot_num}={cc_num}:{param_name}")
                
                # Join with commas but no spaces
                config_string = "cc:" + ",".join(config_parts)
                _log(f"Sending config string: {config_string}")
                
                # Send the config string using TextProtocol's write method
                self.uart.write(config_string)
                _log("Config sent successfully")
                return True
            else:
                _log("[ERROR] No CC configurations generated")
                return False
                
        except Exception as e:
            _log(f"[ERROR] Failed to send config: {str(e)}")
        return False

    def update_state(self):
        current_time = time.monotonic()
        is_detected = self.hardware.is_base_station_detected()
        
        # Retry subscription if needed
        if self.midi_subscription is None:
            self._subscribe_to_handshake()
        
        # Handle disconnection in any state
        if not is_detected and self.state != ConnectionState.STANDALONE:
            self._handle_disconnection()
            return
            
        # Only proceed with state updates if GP22 is high
        if self.state == ConnectionState.STANDALONE:
            if is_detected:
                self._handle_initial_detection()
                
        elif self.state == ConnectionState.DETECTED:
            if not is_detected:
                _log("GP22 went LOW while in DETECTED state - returning to STANDALONE")
                self._handle_disconnection()
                return
                
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
            if not is_detected:
                _log("GP22 went LOW while in RETRY_DELAY state - returning to STANDALONE")
                self._handle_disconnection()
                return
                
            if current_time - self.retry_start_time >= RETRY_DELAY:
                _log("Retry delay complete - returning to DETECTED state")
                self.state = ConnectionState.DETECTED
                
        elif self.state == ConnectionState.HANDSHAKING:
            if not is_detected:
                _log("GP22 went LOW during handshake - aborting")
                self._handle_disconnection()
                return
                
            if current_time - self.handshake_start_time >= HANDSHAKE_TIMEOUT:
                _log("Handshake timeout - returning to standalone")
                self.state = ConnectionState.STANDALONE
                self.hello_count = 0
                
        elif self.state == ConnectionState.CONNECTED:
            if not is_detected:
                _log("GP22 went LOW while connected - disconnecting")
                self._handle_disconnection()
                return
                
            if current_time - self.last_heartbeat_time >= HEARTBEAT_INTERVAL:
                self._send_heartbeat()

    def _handle_initial_detection(self):
        _log("Base station detected (GP22 HIGH) - initializing connection")
        if hasattr(self, 'midi') and self.midi is not None:
            try:
                self.midi.reset_input_buffer()
                self.midi.reset_output_buffer()
            except:
                pass
        time.sleep(SETUP_DELAY)
        self.state = ConnectionState.DETECTED
        self.hello_count = 0
        self._send_hello()
        
    def _handle_disconnection(self):
        _log("Base station disconnected (GP22 LOW)")
        if hasattr(self, 'midi') and self.midi is not None:
            try:
                self.midi.reset_input_buffer()
                self.midi.reset_output_buffer()
            except:
                pass
        self.state = ConnectionState.STANDALONE
        self.hello_count = 0
        self._received_b0 = False
            
    def _send_hello(self):
        try:
            # Verify GP22 is still high before sending hello
            if not self.hardware.is_base_station_detected():
                _log("[ERROR] Cannot send hello - GP22 is LOW")
                return
                
            self.uart.write("hello")
            self.last_hello_time = time.monotonic()
        except Exception as e:
            _log(f"[ERROR] Failed to send hello: {str(e)}")
            
    def _send_heartbeat(self):
        try:
            # Verify GP22 is still high before sending heartbeat
            if not self.hardware.is_base_station_detected():
                _log("[ERROR] Cannot send heartbeat - GP22 is LOW")
                return
                
            self.uart.write("♥︎")
            self.last_heartbeat_time = time.monotonic()
        except Exception as e:
            _log(f"[ERROR] Failed to send heartbeat: {str(e)}")

    def is_connected(self):
        return self.state == ConnectionState.CONNECTED

    def cleanup(self):
        """Clean up resources when shutting down."""
        _log("Cleaning up connection manager resources")
        try:
            # Unsubscribe from MIDI messages
            if self.midi_subscription is None:
                if self.midi:
                    self.midi.unsubscribe(self.midi_subscription)
                self.midi_subscription = None
            
            # Set state to STANDALONE first to prevent any ongoing operations
            self.state = ConnectionState.STANDALONE
            
            # Clean up MIDI interface if it exists
            if hasattr(self, 'midi') and self.midi is not None:
                try:
                    self.midi.reset_input_buffer()
                    self.midi.reset_output_buffer()
                except:
                    pass
            
            # Clear all references
            self.uart = None
            self.router_manager = None
            self.midi = None
            self.hardware = None
            
        except Exception as e:
            _log(f"[ERROR] Connection manager cleanup error: {str(e)}")
