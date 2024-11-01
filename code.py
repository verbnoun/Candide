import board
import busio
import time
from instruments import Piano, ElectricOrgan, BendableOrgan, Instrument
from synthesizer import Synthesizer, SynthAudioOutputManager

class Constants:
    # System Constants
    DEBUG = True  # Enable debug output
    LOG_GLOBAL = True
    LOG_HARDWARE = True
    LOG_MIDI = True
    LOG_SYNTH = True
    LOG_MISC = True

    # Hardware Setup Delay
    SETUP_DELAY = 0.1
    
    # UART MIDI Pin
    MIDI_RX = board.GP17

class HardwareMIDI:
    """Handles UART MIDI input"""
    def __init__(self, midi_callback):
        self.midi_callback = midi_callback
        print(f"Initializing UART MIDI on {Constants.MIDI_RX}")
        
        try:
            # Initialize UART at MIDI baud rate
            self.uart = busio.UART(tx=None,  # No TX needed
                                rx=Constants.MIDI_RX,
                                baudrate=31250,
                                bits=8,
                                parity=None,
                                stop=1)
            
            # Buffer for incomplete messages
            self.buffer = bytearray()
            self.last_byte_time = time.monotonic()
            print("UART MIDI initialization successful")
            
        except Exception as e:
            print(f"UART initialization error: {str(e)}")
            raise

    def check_for_messages(self):
        """Check for and process any incoming MIDI messages"""
        try:
            current_time = time.monotonic()
            
            # Clear buffer if too much time has passed since last byte
            if current_time - self.last_byte_time > 0.1:  # 100ms timeout
                if self.buffer:
                    if Constants.DEBUG:
                        print(f"Clearing stale buffer: {[hex(b) for b in self.buffer]}")
                    self.buffer = bytearray()

            # Check for available bytes
            if self.uart.in_waiting:
                # Read all available bytes
                new_bytes = self.uart.read(self.uart.in_waiting)
                if new_bytes:
                    if Constants.DEBUG:
                        print(f"Received bytes: {[hex(b) for b in new_bytes]}")
                    self.buffer.extend(new_bytes)
                    self.last_byte_time = current_time

                    # Process complete messages
                    while self._process_buffer():
                        pass

        except Exception as e:
            print(f"Error reading UART: {str(e)}")

    def _process_buffer(self):
        """Process buffer and return True if a message was handled"""
        if not self.buffer:
            return False

        try:
            # Look for status byte
            if self.buffer[0] < 0x80:
                if Constants.DEBUG:
                    print(f"Discarding invalid data: {[hex(b) for b in self.buffer]}")
                self.buffer = bytearray()
                return False

            status = self.buffer[0] & 0xF0  # Strip channel

            # Determine message length
            if status in [0x80, 0x90, 0xA0, 0xB0, 0xE0]:  # 3-byte messages
                if len(self.buffer) >= 3:
                    msg = self.buffer[:3]
                    self.buffer = self.buffer[3:]
                    if Constants.DEBUG:
                        print(f"Processing message: {[hex(b) for b in msg]}")
                    self.midi_callback(msg)
                    return True
            elif status in [0xC0, 0xD0]:  # 2-byte messages
                if len(self.buffer) >= 2:
                    msg = self.buffer[:2]
                    self.buffer = self.buffer[2:]
                    if Constants.DEBUG:
                        print(f"Processing message: {[hex(b) for b in msg]}")
                    self.midi_callback(msg)
                    return True
            else:  # Single byte or system messages
                msg = self.buffer[:1]
                self.buffer = self.buffer[1:]
                if Constants.DEBUG:
                    print(f"Processing message: {[hex(b) for b in msg]}")
                self.midi_callback(msg)
                return True

        except Exception as e:
            print(f"Error processing buffer: {str(e)}")
            self.buffer = bytearray()
            
        return False

    def cleanup(self):
        """Clean shutdown"""
        try:
            self.uart.deinit()
            print("UART MIDI cleaned up")
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")

class Candide:
    def __init__(self):
        print("\nInitializing Candide...")
        self.audio = None
        self.synth = None
        self.current_instrument = None
        self.hw_midi = None
        
        try:
            # Setup order matters - audio system first
            self._setup_audio()
            self._setup_synth()
            self._setup_midi()
            self._setup_initial_state()
            print("\nCandide (v1.0) is ready... (◕‿◕✿)")
        except Exception as e:
            print(f"Initialization error: {str(e)}")
            raise
        
    def _setup_audio(self):
        """Initialize audio subsystem"""
        print("Setting up audio...")
        self.audio = SynthAudioOutputManager()
        
    def _setup_synth(self):
        """Initialize synthesis subsystem"""
        print("Setting up synthesizer...")
        self.synth = Synthesizer(self.audio)
        self.current_instrument = Piano()  # Default instrument
        self.synth.set_instrument(self.current_instrument)

    def _setup_midi(self):
        """Initialize MIDI hardware"""
        print("Setting up MIDI hardware...")
        self.hw_midi = HardwareMIDI(self.process_midi_message)

    def _setup_initial_state(self):
        """Set initial state for synthesizer"""
        print("Setting up initial state...")
        pass  # Can be expanded as needed

    def process_midi_message(self, data):
        """Process MIDI message"""
        if not data:
            return

        try:
            status = data[0] & 0xF0  # Strip channel
            
            if status == 0x90:  # Note On
                note = data[1]
                velocity = data[2]
                if Constants.DEBUG:
                    print(f"Note On: note={note}, velocity={velocity}")
                event = ('note_on', note, velocity, 0)
                self.synth.process_midi_event(event)
                
            elif status == 0x80:  # Note Off
                note = data[1]
                if Constants.DEBUG:
                    print(f"Note Off: note={note}")
                event = ('note_off', note, 0, 0)
                self.synth.process_midi_event(event)
                
            elif status == 0xB0:  # Control Change
                cc_num = data[1]
                value = data[2]
                normalized_value = value / 127.0
                if Constants.DEBUG:
                    print(f"Control Change: cc={cc_num}, value={value}")
                event = ('control_change', cc_num, value, normalized_value)
                self.synth.process_midi_event(event)
                
        except Exception as e:
            print(f"Error processing MIDI message: {str(e)}")

    def update(self):
        """Main update loop"""
        try:
            # Check for MIDI messages first
            self.hw_midi.check_for_messages()
            
            # Update synthesis
            self.synth.update([])  # Pass empty list when no MIDI events
            return True
            
        except Exception as e:
            print(f"Error in main loop: {str(e)}")
            return False

    def run(self):
        """Main run loop - no sleep to maintain audio performance"""
        print("Starting main loop...")
        try:
            while self.update():
                pass
        except KeyboardInterrupt:
            print("Keyboard interrupt received")
            pass
        except Exception as e:
            print(f"Error in run loop: {str(e)}")
        finally:
            print("Cleaning up...")
            self.cleanup()

    def cleanup(self):
        """Clean shutdown"""
        if self.synth:
            print("Stopping synthesizer...")
            self.synth.stop()
        if self.hw_midi:
            print("Cleaning up MIDI...")
            self.hw_midi.cleanup()
        print("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁")

def main():
    try:
        synth = Candide()
        synth.run()
    except Exception as e:
        print(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    main()