import board
import time
import busio
import digitalio
from adafruit_bus_device.spi_device import SPIDevice
from instruments import Piano, ElectricOrgan, BendableOrgan, Instrument
from synthesizer import Synthesizer, SynthAudioOutputManager

class Constants:
    # System Constants
    DEBUG = False
    LOG_GLOBAL = True
    LOG_HARDWARE = True
    LOG_MIDI = True
    LOG_SYNTH = True
    LOG_MISC = True

    # Hardware Setup Delay
    SETUP_DELAY = 0.1
    
    # SPI Pins
    SPI_CLOCK = board.GP18
    SPI_MOSI = board.GP19
    SPI_MISO = board.GP16
    SPI_CS = board.GP17
    CART_DETECT = board.GP22
    
    # Message sizes
    PROTOCOL_MSG_SIZE = 4
    MIDI_MSG_SIZE = 4

class SPIReceiver:
    """Handles SPI communication for cartridge with proper sync and timing"""
    # Protocol markers (must match base)
    SYNC_REQUEST = 0xF0
    SYNC_ACK = 0xF1
    HELLO_BART = 0xA0
    HI_CANDIDE = 0xA1
    PROTOCOL_VERSION = 0x01
    
    # Message types
    MSG_TYPE_PROTOCOL = 0x00
    MSG_TYPE_MIDI = 0x01
    
    # States
    DISCONNECTED = 0
    SYNC_STARTED = 1
    SYNC_COMPLETE = 2
    HANDSHAKE_STARTED = 3
    CONNECTED = 4
    
    def __init__(self, midi_callback):
        print("Initializing SPI Receiver (Cartridge)...")
        
        self.state = self.DISCONNECTED
        self.last_sync_time = 0
        self.midi_callback = midi_callback
        
        # Configure detect pin to announce presence
        self.detect = digitalio.DigitalInOut(Constants.CART_DETECT)
        self.detect.direction = digitalio.Direction.OUTPUT
        self.detect.value = True  # Announce presence
        
        # Configure SPI - Cartridge is slave
        self.spi = busio.SPI(
            clock=Constants.SPI_CLOCK,
            MOSI=Constants.SPI_MOSI,
            MISO=Constants.SPI_MISO
        )
        
        # Wait for SPI to be ready
        while not self.spi.try_lock():
            pass
        self.spi.configure(
            baudrate=500000,
            polarity=1,
            phase=1
        )
        self.spi.unlock()
        
        # Monitor CS as INPUT since we're the slave
        self.cs = digitalio.DigitalInOut(Constants.SPI_CS)
        self.cs.direction = digitalio.Direction.INPUT
        self.cs.pull = digitalio.Pull.UP  # Pull up when not selected
        
        # Initialize SPI device without chip select (we're slave)
        self.spi_device = SPIDevice(
            self.spi,
            chip_select=None,  # No CS for slave
            baudrate=500000,
            polarity=1,
            phase=1
        )
        
        # Separate buffers for protocol and MIDI
        self._protocol_out = bytearray(Constants.PROTOCOL_MSG_SIZE)
        self._protocol_in = bytearray(Constants.PROTOCOL_MSG_SIZE)
        self._midi_buffer = bytearray(Constants.MIDI_MSG_SIZE)
        
        # Prepare initial sync response
        self._prepare_sync_response()
        
        print(f"[Cart {time.monotonic():.3f}] SPI initialized, signaling presence")
        print(f"[Cart {time.monotonic():.3f}] Waiting for base station...")

    def _prepare_sync_response(self):
        """Prepare sync acknowledgment response"""
        self._protocol_out[0] = self.SYNC_ACK  # Protocol marker first
        self._protocol_out[1] = self.PROTOCOL_VERSION
        self._protocol_out[2] = self.MSG_TYPE_PROTOCOL  # Message type moved
        self._protocol_out[3] = 0
        print(f"[Cart {time.monotonic():.3f}] Prepared sync response")

    def _prepare_handshake_response(self):
        """Prepare handshake response"""
        self._protocol_out[0] = self.MSG_TYPE_PROTOCOL
        self._protocol_out[1] = self.HELLO_BART
        self._protocol_out[2] = 0
        self._protocol_out[3] = 0
        print(f"[Cart {time.monotonic():.3f}] Prepared handshake response")

    def _handle_spi_transfer(self):
        """Handle SPI transfer based on current state"""
        current_time = time.monotonic()
        try:
            # Single transaction to receive message
            with self.spi_device as device:
                if self.state == self.DISCONNECTED:
                    device.write_readinto(self._protocol_out, self._protocol_in)
                    
                    # Check for sync request
                    if (self._protocol_in[0] == self.MSG_TYPE_PROTOCOL and
                        self._protocol_in[1] == self.SYNC_REQUEST and
                        self._protocol_in[2] == self.PROTOCOL_VERSION):
                        print(f"[Cart {current_time:.3f}] Valid sync request - proceeding to handshake")
                        self.state = self.SYNC_COMPLETE
                        self._prepare_handshake_response()
                        
                elif self.state == self.CONNECTED:
                    # Read incoming message
                    device.readinto(self._midi_buffer)
                    
                    # Process MIDI message if received
                    if self._midi_buffer[0] == self.MSG_TYPE_MIDI:
                        self.midi_callback(self._midi_buffer[1:])
                    
        except Exception as e:
            print(f"[Cart {current_time:.3f}] Transfer error: {str(e)}")

    def check_connection(self):
        """Process incoming communication based on state"""
        try:
            if not self.cs.value:  # CS is active low
                self._handle_spi_transfer()
            return self.state == self.CONNECTED
                        
        except Exception as e:
            print(f"[Cart {time.monotonic():.3f}] Connection error: {str(e)}")
            return False

    def reset_state(self):
        """Reset to initial state"""
        self.state = self.DISCONNECTED
        self._prepare_sync_response()
        print(f"[Cart {time.monotonic():.3f}] Reset to initial state")

    def is_ready(self):
        """Check if connection is established"""
        return self.state == self.CONNECTED

    def cleanup(self):
        """Clean shutdown"""
        self.detect.value = False
        self.reset_state()
        time.sleep(0.1)
        self.spi.deinit()
        self.cs.deinit()
        self.detect.deinit()

class Candide:
    def __init__(self):
        print("\nInitializing Candide...")
        self.spi_receiver = None
        self.audio = None
        self.synth = None
        self.current_instrument = None
        
        # Setup order matters - audio system first
        self._setup_audio()
        self._setup_synth()
        self._setup_spi()
        self._setup_initial_state()
        print("\nCandide (v1.0) is ready... (◕‿◕✿)")
        
    def _setup_audio(self):
        """Initialize audio subsystem"""
        self.audio = SynthAudioOutputManager()
        
    def _setup_synth(self):
        """Initialize synthesis subsystem"""
        self.synth = Synthesizer(self.audio)
        self.current_instrument = Piano()  # Default instrument
        self.synth.set_instrument(self.current_instrument)
        
    def _setup_spi(self):
        """Initialize SPI with MIDI callback"""
        print("Setting up SPI...")
        self.spi_receiver = SPIReceiver(self._handle_midi_message)

    def _setup_initial_state(self):
        """Set initial state for synthesizer"""
        pass  # Can be expanded as needed

    def _handle_midi_message(self, data):
        """Process incoming MIDI message"""
        if not data:
            return

        status = data[0] & 0xF0  # Strip channel
        
        if status == 0x90:  # Note On
            note = data[1]
            velocity = data[2]
            event = ('note_on', note, velocity, 0)  # Key ID not used in synthesis
            self.synth.process_midi_event(event)
            
        elif status == 0x80:  # Note Off
            note = data[1]
            event = ('note_off', note, 0, 0)
            self.synth.process_midi_event(event)
            
        elif status == 0xB0:  # Control Change
            cc_num = data[1]
            value = data[2]
            normalized_value = value / 127.0
            event = ('control_change', cc_num, value, normalized_value)
            self.synth.process_midi_event(event)

    def update(self):
        """Main update loop"""
        try:
            # Update synthesis first with empty midi events list
            self.synth.update([])  # Pass empty list when no MIDI events
            
            # Then check SPI - will trigger MIDI callback if message received
            if not self.spi_receiver.is_ready():
                self.spi_receiver.check_connection()
                
            return True
            
        except Exception as e:
            print(f"[Cart {time.monotonic():.3f}] Error in main loop: {str(e)}")
            return False

    def run(self):
        """Main run loop - no sleep to maintain audio performance"""
        try:
            while self.update():
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean shutdown"""
        if self.synth:
            self.synth.stop()
        if self.spi_receiver:
            self.spi_receiver.cleanup()
        print("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁")

def main():
    synth = Candide()
    synth.run()

if __name__ == "__main__":
    main()