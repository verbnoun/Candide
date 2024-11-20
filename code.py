"""
Main Execution Module for Candide Synthesizer

This module serves as the comprehensive orchestration center 
for the Candide Synthesizer, managing complex interactions 
between hardware, MIDI, audio, and system components.

Key Responsibilities:
- Coordinate hardware input processing
- Manage MIDI communication and event handling
- Control synthesizer state and instrument selection
- Handle system connection and communication protocols
- Provide robust error handling and recovery mechanisms

Primary Classes:
- TransportManager:
  * Manages UART communication infrastructure
  * Handles low-level transport layer operations
  * Provides buffer management and cleanup

- HardwareManager:
  * Initializes and manages hardware interfaces
  * Handles rotary encoder and volume potentiometer
  * Provides hardware input reading capabilities

- SynthManager:
  * Coordinates synthesizer instrument configuration
  * Manages instrument selection and MIDI event processing
  * Interfaces with audio output system

- CandideConnectionManager:
  * Manages connection state with base station
  * Handles handshake and communication protocols
  * Provides connection status tracking

- Candide:
  * Primary system coordinator
  * Integrates all system components
  * Manages main execution loop and system lifecycle

Key Features:
- Flexible hardware input processing
- Advanced MIDI event handling
- Dynamic instrument selection
- Robust communication protocols
- Comprehensive error management
- Configurable debug capabilities
"""

import board
import busio
import digitalio
import time
import sys
from hardware import RotaryEncoderHandler, VolumePotHandler
from instrument_config import create_instrument, list_instruments
from midi import MidiLogic
from output_system import AudioOutputManager
from voices import MPEVoiceManager
from router import Router  # Updated import
from constants import *

import random
import time
import sys

def _log(message, effect=None):
    """
    Conditional logging function with optional color animation.
    Args:
        message (str): Message to log
        effect (str): Animation effect - 'cycle' (default: None)
    """
    if not DEBUG:
        return

    # Basic ANSI colors that work well on most terminals
    COLORS = [
        "\033[36m",  # Cyan
        "\033[34m",  # Blue
        "\033[35m",  # Magenta
        "\033[32m",  # Green
        "\033[33m",  # Yellow
    ]
    RESET = "\033[0m"
    RED = "\033[31m"
    WHITE = "\033[37m"
    
    if effect == 'cycle':
        # Move up one line after first print
        print("\033[s", end='', file=sys.stderr)  # Save cursor position
        
        # Do 5 color cycles of the full string
        for i in range(20):
            colored_text = ""
            # Generate full string with random colors per character
            for char in message:
                colored_text += random.choice(COLORS) + char
            
            if i == 0:
                print(f"{colored_text}{RESET}", file=sys.stderr)
            else:
                # Restore position and clear line
                print(f"\033[u\033[K{colored_text}{RESET}", file=sys.stderr)
            time.sleep(0.1)
        
    else:
        # Normal logging behavior
        color = RED if "[ERROR]" in message else WHITE
        print(f"{color}[CANDID] {message}{RESET}", file=sys.stderr)

class TransportManager:
    def __init__(self, tx_pin, rx_pin, baudrate=MIDI_BAUDRATE, timeout=UART_TIMEOUT):
        _log("Initializing shared transport...")
        self.uart = busio.UART(
            tx=tx_pin,
            rx=rx_pin,
            baudrate=baudrate,
            timeout=timeout,
            bits=8,
            parity=None,
            stop=1
        )
        _log("Shared transport initialized")
        
    def get_uart(self):
        return self.uart
        
    def flush_buffers(self):
        start_time = time.monotonic()
        while time.monotonic() - start_time < BUFFER_CLEAR_TIMEOUT:
            if self.uart.in_waiting:
                self.uart.read()
            else:
                break
        
    def cleanup(self):
        if self.uart:
            self.flush_buffers()
            self.uart.deinit()

class TextUart:
    def __init__(self, uart):
        self.uart = uart
        self.last_write = 0
        _log("Text protocol initialized")

    def write(self, message):
        current_time = time.monotonic()
        delay_needed = MESSAGE_TIMEOUT - (current_time - self.last_write)
        if delay_needed > 0:
            time.sleep(delay_needed)
            
        if isinstance(message, str):
            message = message.encode('utf-8')
        result = self.uart.write(message)
        self.last_write = time.monotonic()
        return result

class HardwareManager:
    def __init__(self):
        _log("Setting up hardware...")
        self.encoder = None
        self.volume_pot = None
        self._setup_hardware()

    def _setup_hardware(self):
        self.encoder = RotaryEncoderHandler(
            INSTRUMENT_ENC_CLK,
            INSTRUMENT_ENC_DT
        )
        self.volume_pot = VolumePotHandler(VOLUME_POT)

    def get_initial_volume(self):
        return self.volume_pot.normalize_value(self.volume_pot.pot.value)

    def read_encoder(self):
        return self.encoder.read_encoder()

    def read_pot(self):
        return self.volume_pot.read_pot()
        
    def cleanup(self):
        """Clean up hardware resources"""
        if self.encoder:
            self.encoder.cleanup()
        if self.volume_pot and self.volume_pot.pot:
            self.volume_pot.pot.deinit()

class SynthManager:
    def __init__(self, output_manager):
        self.voice_manager = None
        self.message_router = None
        self.current_instrument = None
        self.output_manager = output_manager
        self._setup_synth()

    def _setup_synth(self):
        _log("Setting up synthesizer...")
        # Initialize voice manager with output manager
        self.voice_manager = MPEVoiceManager(self.output_manager)
        
        # Initialize message router with voice manager
        self.message_router = Router(self.voice_manager)  # Updated class name
        
        # Set initial instrument
        self.current_instrument = create_instrument('piano')
        if self.current_instrument:
            config = self.current_instrument.get_config()
            self.voice_manager.set_config(config)
            self.message_router.set_config(config)

    def set_instrument(self, instrument_name):
        new_instrument = create_instrument(instrument_name)
        if new_instrument:
            self.current_instrument = new_instrument
            config = new_instrument.get_config()
            self.voice_manager.set_config(config)
            self.message_router.set_config(config)

    def update(self):
        self.message_router.process_updates()

    def process_midi_events(self, events):
        if events:
            for event in events:
                self.message_router.route_message(event)
            
    def get_current_config(self):
        if self.current_instrument:
            return self.current_instrument.get_config()
        return None

    def format_cc_config(self):
        """Format CC configuration string based on current instrument config"""
        if not self.current_instrument:
            _log("[ERROR] No current instrument to format CC config")
            return "cc:"  # Return minimal valid config if no instrument
            
        config = self.current_instrument.get_config()
        if not config or 'cc_routing' not in config:
            _log("[ERROR] No CC routing configuration found")
            return "cc:"
            
        # Create pot to CC assignments with names
        assignments = []
        pot_number = 0
        
        for cc_number, routing in config['cc_routing'].items():
            # Validate CC number is within range 0-127
            cc_num = int(cc_number)
            if not (0 <= cc_num <= 127):
                _log(f"[ERROR] Invalid CC number: {cc_num}")
                continue
                
            # Validate pot number is within range 0-13
            if pot_number > 13:
                _log("[ERROR] Exceeded maximum pot number")
                break
                
            # Get CC name from routing if available, otherwise use "CC{number}"
            cc_name = routing.get('name', f"CC{cc_num}")
            assignments.append(f"{pot_number}={cc_num}:{cc_name}")
            pot_number += 1
            
        # Join assignments with commas
        config_str = "cc:" + ",".join(assignments)
        
        _log(f"Sending CC config: {config_str}")
            
        return config_str

class CandideConnectionManager:
    def __init__(self, text_uart, synth_manager, transport_manager):
        self.uart = text_uart
        self.synth_manager = synth_manager
        self.transport = transport_manager
        
        self.detect_pin = digitalio.DigitalInOut(DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        self.state = ConnectionState.STANDALONE
        self.last_hello_time = 0
        self.last_heartbeat_time = 0
        self.handshake_start_time = 0
        self.hello_count = 0
        self.retry_start_time = 0
        
        _log("Candide connection manager initialized")
        
    def update_state(self):
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
        if not event or event['type'] != 'cc':
            return
            
        if (event['channel'] == 0 and 
            event['data']['number'] == HANDSHAKE_CC):
            
            if (event['data']['value'] == HANDSHAKE_VALUE and 
                self.state == ConnectionState.DETECTED):
                _log("Handshake CC received - sending config")
                self.state = ConnectionState.HANDSHAKING
                self.handshake_start_time = time.monotonic()
                # Send properly formatted CC config
                config_str = self.synth_manager.format_cc_config()
                self.uart.write(f"{config_str}\n")
                self.state = ConnectionState.CONNECTED
                _log("Connection established")
                
    def _handle_initial_detection(self):
        _log("Base station detected - initializing connection")
        self.transport.flush_buffers()
        time.sleep(SETUP_DELAY)
        self.state = ConnectionState.DETECTED
        self.hello_count = 0
        self._send_hello()
        
    def _handle_disconnection(self):
        _log("Base station disconnected")
        self.transport.flush_buffers()
        self.state = ConnectionState.STANDALONE
        self.hello_count = 0
        
    def _send_hello(self):
        try:
            self.uart.write("hello\n")
            self.last_hello_time = time.monotonic()
        except Exception as e:
            _log(f"[ERROR] Failed to send hello: {str(e)}")
            
    def _send_heartbeat(self):
        try:
            self.uart.write("♥︎\n")
            self.last_heartbeat_time = time.monotonic()
        except Exception as e:
            _log(f"[ERROR] Failed to send heartbeat: {str(e)}")
            
    def cleanup(self):
        if self.detect_pin:
            self.detect_pin.deinit()

    def is_connected(self):
        return self.state == ConnectionState.CONNECTED

class Candide:
    def __init__(self):
        _log("\nWakeup Candide!", effect='cycle')
        
        # Initialize audio output first
        self.output_manager = AudioOutputManager()
        
        self.hardware_manager = HardwareManager()
        self.synth_manager = SynthManager(self.output_manager)
        
        self.transport = TransportManager(
            tx_pin=UART_TX,
            rx_pin=UART_RX,
            baudrate=UART_BAUDRATE,
            timeout=UART_TIMEOUT
        )
        
        shared_uart = self.transport.get_uart()
        self.text_uart = TextUart(shared_uart)
        self.midi = MidiLogic(
            uart=shared_uart,
            text_callback=self._handle_midi_message
        )
        
        self.connection_manager = CandideConnectionManager(
            self.text_uart,
            self.synth_manager,
            self.transport
        )
        
        self.last_encoder_scan = 0
        self.last_volume_scan = 0

        try:
            initial_volume = self.hardware_manager.get_initial_volume()
            _log(f"Initial volume: {initial_volume:.3f}")
            self.output_manager.set_volume(initial_volume)
            _log("\nCandide (v1.0) is awake!... ( ◔◡◔)♬", effect='cycle')
        except Exception as e:
            _log(f"[ERROR] Initialization error: {str(e)}")
            raise

    def _handle_midi_message(self, event):
        if not event:
            return
            
        self.connection_manager.handle_midi_message(event)
            
        if self.connection_manager.state in [ConnectionState.HANDSHAKING, ConnectionState.CONNECTED]:
            if event['type'] != 'note':
                self.synth_manager.process_midi_events([event])

    def _check_volume(self):
        current_time = time.monotonic()
        if current_time - self.last_volume_scan >= UPDATE_INTERVAL:
            new_volume = self.hardware_manager.read_pot()
            if new_volume is not None:
                self.output_manager.set_volume(new_volume)
            self.last_volume_scan = current_time

    def _check_encoder(self):
        current_time = time.monotonic()
        if current_time - self.last_encoder_scan >= ENCODER_SCAN_INTERVAL:
            events = self.hardware_manager.read_encoder()
            if self.connection_manager.state in [ConnectionState.STANDALONE, ConnectionState.CONNECTED]:
                for event_type, direction in events:
                    _log(f"Encoder events: {events}")
                    if event_type == 'instrument_change':
                        instruments = list_instruments()
                        current_idx = instruments.index(self.synth_manager.current_instrument.name)
                        new_idx = (current_idx + direction) % len(instruments)
                        new_instrument = instruments[new_idx].lower().replace(' ', '_')
                        _log(f"Switching to instrument: {new_instrument}")
                        self.synth_manager.set_instrument(new_instrument)
                        if self.connection_manager.state == ConnectionState.CONNECTED:
                            config_str = self.synth_manager.format_cc_config()
                            self.text_uart.write(f"{config_str}\n")
                            
            self.last_encoder_scan = current_time

    def update(self):
        try:
            self.midi.check_for_messages()
            self.connection_manager.update_state()
            self._check_encoder()
            self._check_volume()
            self.synth_manager.update()
            return True
            
        except Exception as e:
            _log(f"[ERROR] Update error: {str(e)}")
            return False

    def run(self):
        _log("Starting main loop...")
        try:
            while self.update():
                pass
        except KeyboardInterrupt:
            _log("Keyboard interrupt received")
            pass
        except Exception as e:
            _log(f"[ERROR] Error in run loop: {str(e)}")
        finally:
            _log("Cleaning up...")
            self.cleanup()

    def cleanup(self):
        if self.synth_manager and self.synth_manager.voice_manager:
            _log("Stopping synthesizer...")
            self.synth_manager.voice_manager.cleanup_voices()
        if self.midi:
            _log("Cleaning up MIDI...")
            self.midi.cleanup()
        if hasattr(self, 'transport'):
            _log("Cleaning up transport...")
            self.transport.cleanup()
        if self.connection_manager:
            _log("Cleaning up connection manager...")
            self.connection_manager.cleanup()
        if self.hardware_manager:
            _log("Cleaning up hardware...")
            self.hardware_manager.cleanup()
        if self.output_manager:
            _log("Cleaning up audio...")
            self.output_manager.cleanup()
        _log("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁", effect='cycle')

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        _log(f"[ERROR] Fatal error: {str(e)}")

if __name__ == "__main__":
    main()
