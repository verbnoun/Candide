"""
Main Execution Module for Candide Synthesizer

This module serves as the comprehensive orchestration center 
for the Candide Synthesizer, managing complex interactions 
between hardware, MIDI, audio, and system components.

Key Responsibilities:
- Coordinate hardware input processing
- Manage MIDI communication and event handling
- Control synthesizer state and instrument selection
- Provide robust error handling and recovery mechanisms

Primary Classes:
- TransportManager: Manages UART communication infrastructure
- HardwareManager: Initializes and manages hardware interfaces
- SynthManager: Coordinates synth configuration and routing
- Candide: Primary system coordinator
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
from voices import VoiceManager
from router import OscillatorRouter, FilterRouter, AmplifierRouter
from connection_manager import CandideConnectionManager
from constants import *

import random

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
        print("\033[s", end='', file=sys.stderr)
        
        for i in range(10):
            colored_text = ""
            for char in message:
                colored_text += random.choice(COLORS) + char
            
            if i == 0:
                print(f"{colored_text}{RESET}", file=sys.stderr)
            else:
                print(f"\033[u\033[K{colored_text}{RESET}", file=sys.stderr)
            time.sleep(0.1)
    else:
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
        if self.encoder:
            self.encoder.cleanup()
        if self.volume_pot and self.volume_pot.pot:
            self.volume_pot.pot.deinit()

class SynthManager:
    """Manages instrument configuration and routing"""
    def __init__(self, output_manager):
        self.voice_manager = VoiceManager(output_manager)
        self.routers = {}
        self.current_instrument = None
        self._setup_synth()

    def _setup_synth(self):
        _log("Setting up synthesizer...")
        
        # Initialize routers
        self.routers = {
            'oscillator': OscillatorRouter(),
            'filter': FilterRouter(),
            'amplifier': AmplifierRouter()
        }
        
        # Set initial instrument
        self.current_instrument = create_instrument('piano')
        if self.current_instrument:
            self._configure_instrument(self.current_instrument)

    def _configure_instrument(self, instrument):
        """Configure system for new instrument"""
        config = instrument.get_config()
        if not config:
            return
            
        # Update voice manager config
        self.voice_manager.set_config(config)
        
        # Configure routers
        for router in self.routers.values():
            router.compile_routes(config)
            
        _log(f"Configured instrument: {instrument.name}")

    def set_instrument(self, instrument_name):
        """Switch to new instrument"""
        new_instrument = create_instrument(instrument_name)
        if new_instrument:
            self.current_instrument = new_instrument
            self._configure_instrument(new_instrument)

    def process_midi(self, message):
        """Route MIDI message through appropriate router"""
        if not message:
            return
            
        for router in self.routers.values():
            stream = router.process_message(message, self.voice_manager)
            if stream:
                self.voice_manager.process_parameter_stream(stream)

    def get_current_config(self):
        if self.current_instrument:
            return self.current_instrument.get_config()
        return None

    def format_cc_config(self):
        """Format CC configuration string for base station"""
        if not self.current_instrument:
            _log("[ERROR] No current instrument")
            return "cc:"
            
        config = self.current_instrument.get_config()
        if not config or 'cc_routing' not in config:
            _log("[ERROR] No CC routing found")
            return "cc:"
            
        assignments = []
        pot_number = 0
        
        for cc_number, routing in config['cc_routing'].items():
            cc_num = int(cc_number)
            if not (0 <= cc_num <= 127):
                _log(f"[ERROR] Invalid CC: {cc_num}")
                continue
                
            if pot_number > 13:
                break
                
            cc_name = routing.get('name', f"CC{cc_num}")
            assignments.append(f"{pot_number}={cc_num}:{cc_name}")
            pot_number += 1
            
        config_str = "cc:" + ",".join(assignments)
        _log(f"CC config: {config_str}")
        return config_str

class Candide:
    def __init__(self):
        _log("\nWakeup Candide!\n", effect='cycle')
        
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
        
        self.connection_manager = CandideConnectionManager(
            self.text_uart,
            self.synth_manager,
            self.transport
        )
        
        self.midi = MidiLogic(
            uart=shared_uart,
            text_callback=self.connection_manager.handle_midi_message,
        )
        
        self.last_encoder_scan = 0
        self.last_volume_scan = 0

        try:
            initial_volume = self.hardware_manager.get_initial_volume()
            _log(f"Initial volume: {initial_volume:.3f}")
            self.output_manager.set_volume(initial_volume)
            _log("\nCandide (v1.0) is awake!... ( ◔◡◔)♬\n", effect='cycle')
        except Exception as e:
            _log(f"[ERROR] Initialization error: {str(e)}")
            raise

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
            self.synth_manager.voice_manager.cleanup_voices()
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
        _log("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁\n", effect='cycle')

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        _log(f"[ERROR] Fatal error: {str(e)}")

if __name__ == "__main__":
    main()
