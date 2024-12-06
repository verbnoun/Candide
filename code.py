"""Main execution module for Candide UART logger managing core functionality and hardware interactions."""

import board
import time
import sys
import random
from constants import *
from hardware import HardwareManager, AudioSystem
from uart import UartManager
from connection import ConnectionManager
from instruments import InstrumentManager
from synthesizer import Synthesizer

def _log(message, effect=None):
    COLORS = [
        "\033[96m",
        "\033[94m",
        "\033[95m",
        "\033[92m",
        "\033[93m",
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

class Candide:
    def __init__(self):
        _log("\nWakeup Candide!\n", effect='cycle')
        
        _log("Initializing hardware manager...")
        self.hardware_manager = HardwareManager()

        _log("Initializing UART interfaces...")
        self.transport, self.text_uart = UartManager.get_interfaces()
        # Get MIDI interface explicitly
        self.midi_interface = UartManager.get_midi_interface()

        _log("Initializing synthesizer...")
        self.synthesizer = Synthesizer(self.midi_interface)

        _log("Initializing audio system...")
        self.audio_system = AudioSystem()

        _log("Initializing instrument manager...")
        self.instrument_manager = InstrumentManager()

        _log("Initializing connection manager...")
        self.connection_manager = ConnectionManager(
            self.text_uart,
            self.midi_interface,
            self.hardware_manager,
            self.instrument_manager
        )

        _log("Registering components with instrument manager...")
        self.instrument_manager.register_components(
            connection_manager=self.connection_manager,
            synthesizer=self.synthesizer
        )

        _log("Setting initial instrument...")
        # Get first available instrument
        initial_instrument = self.instrument_manager.get_available_instruments()[0]
        # Register connection callback before setting instrument
        self.synthesizer.register_ready_callback(self.connection_manager.on_synth_ready)
        # Set initial instrument to trigger ready flow
        self.instrument_manager.set_instrument(initial_instrument)

        try:
            _log("Setting initial volume...")
            initial_volume = self.hardware_manager.get_initial_volume()
            _log(f"Initial volume: {initial_volume:.3f}")
            self.audio_system.set_volume(initial_volume)
            self.hardware_manager.last_volume = initial_volume
            _log("\nCandide (v1.0) is awake!... ( ◔◡◔)♬\n", effect='cycle')

            # Check for base station after all initialization is complete
            _log("Checking for base station...")
            if self.hardware_manager.is_base_station_detected():
                self.connection_manager._handle_initial_detection()
                # Give time for synth to become ready and config to be sent
                time.sleep(0.1)
                self.connection_manager.update_state()

        except Exception as e:
            _log(f"[ERROR] Initialization error: {str(e)}")
            raise

    def update(self):
        try:
            if self.transport.in_waiting:
                self.transport.log_incoming_data()  # This will now handle distributing MIDI messages
            self.connection_manager.update_state()
            self.hardware_manager.check_encoder(self.instrument_manager)
            self.hardware_manager.check_volume(self.audio_system)
                
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
        if hasattr(self, 'transport'):
            _log("Cleaning up transport...")
            UartManager.cleanup()
        if self.instrument_manager:
            _log("Cleaning up instrument manager...")
            self.instrument_manager.cleanup()
        if self.synthesizer:
            _log("Cleaning up synthesizer...")
            self.synthesizer.cleanup()
        if self.connection_manager:
            _log("Cleaning up connection manager...")
            self.connection_manager.cleanup()
        if self.hardware_manager:
            _log("Cleaning up hardware...")
            self.hardware_manager.cleanup()
        if self.audio_system:
            _log("Cleaning up audio...")
            self.audio_system.cleanup()
        _log("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁\n")

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        _log(f"[ERROR] Fatal error: {str(e)}")

if __name__ == "__main__":
    main()
