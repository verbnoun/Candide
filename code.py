"""Main execution module for Candide UART logger managing core functionality and hardware interactions."""

import board
import time
import sys
import random
from constants import *
from hardware import HardwareManager, AudioSystem
from uart import UartManager
from midi import initialize_midi  # Add this import
from connection import ConnectionManager
from instruments import InstrumentManager
from synthesizer import Synthesizer

def _log(message, prefix=LOG_CANDIDE, color=LOG_WHITE, is_error=False):
    """Centralized logging function with consistent formatting."""
    if is_error:
        print(f"{color}{prefix} [ERROR] {message}{LOG_RESET}", file=sys.stderr)
    else:
        print(f"{color}{prefix} {message}{LOG_RESET}", file=sys.stderr)

def _cycle_log(message):
    """Special logging effect for startup messages."""
    COLORS = [LOG_LIGHT_CYAN, LOG_LIGHT_BLUE, LOG_LIGHT_MAGENTA, LOG_LIGHT_GREEN, LOG_LIGHT_YELLOW]
    
    print("\033[s", end='', file=sys.stderr)
    
    for i in range(10):
        colored_text = ""
        for char in message:
            colored_text += random.choice(COLORS) + char
        
        if i == 0:
            print(f"{colored_text}{LOG_RESET}", file=sys.stderr)
        else:
            print(f"\033[u\033[K{colored_text}{LOG_RESET}", file=sys.stderr)
        time.sleep(0.1)

class Candide:
    def __init__(self):
        _cycle_log("\nWakeup Candide!\n")
        
        _log("Initializing hardware manager...")
        self.hardware_manager = HardwareManager()

        _log("Initializing UART interfaces...")
        # Initialize UART and MIDI in correct order
        self.transport, self.text_uart = UartManager.get_interfaces()
        # Initialize MIDI interface
        self.midi_interface = initialize_midi()

        _log("Initializing audio system...")
        self.audio_system = AudioSystem()

        _log("Initializing synthesizer...")
        self.synthesizer = Synthesizer(self.midi_interface, self.audio_system)

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
            _cycle_log("\nCandide (v1.0) is awake!... ( ◔◡◔)♬\n")

            # Check for base station after all initialization is complete
            _log("Checking for base station...")
            if self.hardware_manager.is_base_station_detected():
                self.connection_manager._handle_initial_detection()
                # Give time for synth to become ready and config to be sent
                time.sleep(0.1)
                self.connection_manager.update_state()

        except Exception as e:
            _log(f"Initialization error: {str(e)}", is_error=True)
            raise

    def update(self):
        try:
            if self.transport.in_waiting:
                self.midi_interface.process_midi_messages()  # Updated to use midi_interface directly
            self.connection_manager.update_state()
            self.hardware_manager.check_encoder(self.instrument_manager)
            self.hardware_manager.check_volume(self.audio_system)
                
            return True
            
        except Exception as e:
            _log(f"Update error: {str(e)}", is_error=True)
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
            _log(f"Error in run loop: {str(e)}", is_error=True)
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
        _cycle_log("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁\n")

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        _log(f"Fatal error: {str(e)}", is_error=True)

if __name__ == "__main__":
    main()
