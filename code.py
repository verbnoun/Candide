"""
Main Execution Module for Candide Synthesizer

This module serves as the comprehensive orchestration center 
for the Candide Synthesizer, managing complex interactions 
between hardware, MIDI, audio, and system components.

Key Responsibilities:
- Coordinate hardware input processing
- Initialize system components
- Control synthesizer state and instrument selection
- Provide robust error handling and recovery mechanisms
"""

import board
import time
import sys
from hardware import HardwareManager
from transport import TransportFactory
from instrument_config import create_instrument, list_instruments
from midi import MidiLogic
from output_system import AudioPipeline
from voices import VoiceManager
from router import Router
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
        "\033[96m",  # Light Cyan
        "\033[94m",  # Light Blue
        "\033[95m",  # Light Magenta
        "\033[92m",  # Light Green
        "\033[93m",  # Light Yellow
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

class SynthManager:
    """Manages instrument configuration and routing"""
    def __init__(self, output_manager):
        _log("Synth Manager init ...")
        self.voice_manager = VoiceManager(output_manager)
        self.router = None
        self.current_instrument = None
        self._setup_synth()

    def _setup_synth(self):
        _log("Setting up synth ...")
        
        # Create single router
        self.router = Router()
        
        # Set initial instrument
        self.current_instrument = create_instrument('piano')
        if self.current_instrument:
            self._configure_instrument(self.current_instrument)

    def _configure_instrument(self, instrument):
        """Configure system for new instrument"""
        _log("Configuring system for new instrument ...")
        try:
            config = instrument.get_config()
            if not config or not isinstance(config, dict):
                _log("[ERROR] Invalid config format")
                return
                
            # Configure router with new instrument config
            self.router.compile_routes(config)
                
            _log(f"Configured instrument: {instrument.name}")
        except Exception as e:
            _log(f"[ERROR] Configuration error: {str(e)}")
            raise

    def set_instrument(self, instrument_name):
        """Switch to new instrument"""
        _log("Switching to new instrument ...")
        new_instrument = create_instrument(instrument_name)
        if new_instrument:
            self.current_instrument = new_instrument
            self._configure_instrument(new_instrument)

    def get_current_config(self):
        """Get current instrument configuration"""
        _log("Getting current instrument config ...")
        if not self.current_instrument:
            return None
        try:
            config = self.current_instrument.get_config()
            if not isinstance(config, dict):
                _log("[ERROR] Invalid config format")
                return None
            return config
        except Exception as e:
            _log(f"[ERROR] Error getting config: {str(e)}")
            return None

class Candide:
    def __init__(self):
        _log("\nWakeup Candide!\n", effect='cycle')
        
        self.output_manager = AudioPipeline()
        self.hardware_manager = HardwareManager()
        self.synth_manager = SynthManager(self.output_manager)
        
        # Create single shared UART transport
        self.transport = TransportFactory.create_uart_transport(
            tx_pin=UART_TX,
            rx_pin=UART_RX,
            baudrate=UART_BAUDRATE,
            timeout=UART_TIMEOUT
        )
        
        # Create text protocol using shared transport
        self.text_uart = TransportFactory.create_text_protocol(self.transport)
        
        self.connection_manager = CandideConnectionManager(
            self.text_uart,
            self.synth_manager,
            self.transport
        )
        
        # Initialize MIDI with shared transport and router
        self.midi = MidiLogic(
            uart=self.transport,
            router=self.synth_manager.router,
            connection_manager=self.connection_manager,
            voice_manager=self.synth_manager.voice_manager
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
            new_volume = self.hardware_manager.read_volume()
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
                        # Send new config if connected
                        self.connection_manager.send_config()
                            
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
        _log("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁\n")

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        _log(f"[ERROR] Fatal error: {str(e)}")

if __name__ == "__main__":
    main()
