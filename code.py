"""Main execution module for Candide UART logger managing core functionality and hardware interactions."""

import board
import time
import sys
import random
from constants import *
from hardware import HardwareManager, AudioSystem
from uart import UartManager
from midi import initialize_midi
from connection import ConnectionManager
from instruments import InstrumentManager
from synth import Synthesizer
from logging import log, TAG_CANDIDE, COLOR_CYAN, COLOR_BLUE, COLOR_MAGENTA, COLOR_GREEN, COLOR_YELLOW, COLOR_RESET

def _cycle_log(message):
    """Special logging effect for startup messages."""
    COLORS = [COLOR_CYAN, COLOR_BLUE, COLOR_MAGENTA, COLOR_GREEN, COLOR_YELLOW]
    
    print("\033[s", end='', file=sys.stderr)
    
    for i in range(10):
        colored_text = ""
        for char in message:
            colored_text += random.choice(COLORS) + char
        
        if i == 0:
            print(f"{colored_text}{COLOR_RESET}", file=sys.stderr)
        else:
            print(f"\033[u\033[K{colored_text}{COLOR_RESET}", file=sys.stderr)
        time.sleep(0.1)

class Candide:
    def __init__(self):
        _cycle_log("\nWakeup Candide!\n")
        
        # 1. Initialize core hardware and interfaces
        log(TAG_CANDIDE, "Initializing hardware manager...")
        self.hardware_manager = HardwareManager()

        log(TAG_CANDIDE, "Initializing UART interfaces...")
        self.transport, self.text_uart = UartManager.get_interfaces()
        # Initialize MIDI system (handles own UART setup)
        initialize_midi()

        log(TAG_CANDIDE, "Initializing audio system...")
        self.audio_system = AudioSystem()

        # Get MIDI interface and initialize connection manager
        log(TAG_CANDIDE, "Initializing connection manager...")
        self.midi_interface = UartManager.get_midi_interface()
        self.connection_manager = ConnectionManager(
            self.text_uart,
            self.midi_interface,
            self.hardware_manager
        )

        # Initialize instrument manager
        log(TAG_CANDIDE, "Initializing instrument manager...")
        self.instrument_manager = InstrumentManager()

        # Initialize synthesizer with audio
        log(TAG_CANDIDE, "Initializing synthesizer...")
        self.synthesizer = Synthesizer(self.audio_system)

        # Initialize patcher to handle MIDI routing
        log(TAG_CANDIDE, "Initializing patcher...")
        from patcher import MidiHandler
        self.patcher = MidiHandler(self.synthesizer)
        self.patcher.set_midi_interface(self.midi_interface)
        # Add patcher as instrument observer
        self.instrument_manager.add_observer(self.patcher)

        # Connect managers
        log(TAG_CANDIDE, "Connecting managers...")
        self.instrument_manager.set_connection_manager(self.connection_manager)
        self.connection_manager.set_instrument_manager(self.instrument_manager)

        # Set initial instrument
        log(TAG_CANDIDE, "Setting initial instrument...")
        initial_instrument = self.instrument_manager.get_available_instruments()[0]
        self.instrument_manager.set_instrument(initial_instrument)

        try:
            log(TAG_CANDIDE, "Setting initial volume...")
            initial_volume = self.hardware_manager.get_initial_volume()
            log(TAG_CANDIDE, f"Initial volume: {initial_volume:.3f}")
            self.audio_system.set_volume(initial_volume)
            self.hardware_manager.last_volume = initial_volume
            
            _cycle_log("\nCandide (v1.0) is awake!... ( ◔◡◔)♬\n")

            # Start connection detection
            log(TAG_CANDIDE, "Checking for base station...")
            # Just check state - connection manager will handle detection in update loop
            if self.hardware_manager.is_base_station_detected():
                log(TAG_CANDIDE, "Base station detected during boot")

        except Exception as e:
            log(TAG_CANDIDE, f"Initialization error: {str(e)}", is_error=True)
            raise

    def update(self):
        try:
            # Process any pending MIDI messages first
            if self.midi_interface:
                self.midi_interface.process_midi_messages()
            
            # Then handle other updates
            self.connection_manager.update_state()
            self.hardware_manager.check_encoder(self.instrument_manager)
            self.hardware_manager.check_volume(self.audio_system)
                
            return True
            
        except Exception as e:
            log(TAG_CANDIDE, f"Update error: {str(e)}", is_error=True)
            return False

    def run(self):
        log(TAG_CANDIDE, "Starting main loop...")
        try:
            while self.update():
                pass
        except KeyboardInterrupt:
            log(TAG_CANDIDE, "Keyboard interrupt received")
            pass
        except Exception as e:
            log(TAG_CANDIDE, f"Error in run loop: {str(e)}", is_error=True)
        finally:
            log(TAG_CANDIDE, "Cleaning up...")
            self.cleanup()

    def cleanup(self):
        if hasattr(self, 'midi_interface'):
            self.midi_interface = None
        if hasattr(self, 'transport'):
            log(TAG_CANDIDE, "Cleaning up transport...")
            UartManager.cleanup()
        if self.instrument_manager:
            log(TAG_CANDIDE, "Cleaning up instrument manager...")
            self.instrument_manager.cleanup()
        if self.synthesizer:
            log(TAG_CANDIDE, "Cleaning up synthesizer...")
            self.synthesizer.cleanup()
        if self.connection_manager:
            log(TAG_CANDIDE, "Cleaning up connection manager...")
            self.connection_manager.cleanup()
        if self.hardware_manager:
            log(TAG_CANDIDE, "Cleaning up hardware...")
            self.hardware_manager.cleanup()
        if self.audio_system:
            log(TAG_CANDIDE, "Cleaning up audio...")
            self.audio_system.cleanup()
        _cycle_log("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁\n")

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        log(TAG_CANDIDE, f"Fatal error: {str(e)}", is_error=True)

if __name__ == "__main__":
    main()
