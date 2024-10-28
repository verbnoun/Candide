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
    
    # Main Loop Interval (in seconds)
    MAIN_LOOP_INTERVAL = 0.001

class SPIReceiver:
    """Handles SPI communication for cartridge with proper sync and timing"""
    # Protocol markers (must match base)
    SYNC_REQUEST = 0xF0
    SYNC_ACK = 0xF1
    HELLO_BART = 0xA0
    HI_CANDIDE = 0xA1
    PROTOCOL_VERSION = 0x01
    
    # States
    DISCONNECTED = 0
    SYNC_STARTED = 1
    SYNC_COMPLETE = 2
    HANDSHAKE_STARTED = 3
    CONNECTED = 4
    
    def __init__(self):
        print("Initializing SPI Receiver (Cartridge)...")
        
        self.state = self.DISCONNECTED
        self.last_sync_time = 0
        
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
        
        # Monitor CS as INPUT since we're the slave
        self.cs = digitalio.DigitalInOut(Constants.SPI_CS)
        self.cs.direction = digitalio.Direction.INPUT
        self.cs.pull = digitalio.Pull.UP  # Pull up when not selected
        
        # Initialize SPI device without chip select (we're slave)
        self.spi_device = SPIDevice(
            self.spi,
            baudrate=1000000,  # 1MHz to match base
            polarity=0,
            phase=0
        )
        
        # Initialize buffers
        self._out_buffer = bytearray(4)  # Response buffer
        self._in_buffer = bytearray(4)   # Receive buffer
        
        # Prepare initial sync response
        self._prepare_sync_response()
        
        print("[Cart] SPI initialized, signaling presence")
        print("[Cart] Waiting for base station...")

    def _prepare_sync_response(self):
        """Prepare sync acknowledgment response"""
        self._out_buffer[0] = self.SYNC_ACK
        self._out_buffer[1] = self.PROTOCOL_VERSION
        self._out_buffer[2] = 0
        self._out_buffer[3] = 0
        print("[Cart] Prepared sync response")

    def _prepare_handshake_response(self):
        """Prepare handshake response"""
        self._out_buffer[0] = self.HELLO_BART
        self._out_buffer[1] = 0
        self._out_buffer[2] = 0
        self._out_buffer[3] = 0
        print("[Cart] Prepared handshake response")

    def _prepare_connected_response(self):
        """Prepare normal operation response"""
        self._out_buffer[0] = self.SYNC_ACK
        self._out_buffer[1] = 0
        self._out_buffer[2] = 0
        self._out_buffer[3] = 0

    def check_connection(self):
        """Process incoming communication based on state"""
        try:
            # Only process when CS is active (low)
            if not self.cs.value:  # CS is active low
                with self.spi_device as device:
                    # Read incoming data
                    device.readinto(self._in_buffer)
                    
                    if any(self._in_buffer):  # If we received any data
                        print(f"[Cart] Received: {[hex(b) for b in self._in_buffer]}")
                        
                        if self.state == self.DISCONNECTED:
                            self._handle_sync()
                        elif self.state == self.SYNC_COMPLETE:
                            self._handle_handshake()
                        elif self.state == self.CONNECTED:
                            self._handle_communication()
                            
                    # Write response after processing
                    device.write(self._out_buffer)
                    print(f"[Cart] Sent: {[hex(b) for b in self._out_buffer]}")
                    
            return self.state == self.CONNECTED
                    
        except Exception as e:
            print(f"[Cart] Connection error: {str(e)}")
            return False

    def _handle_sync(self):
        """Handle sync request from base"""
        try:
            if (self._in_buffer[0] == self.SYNC_REQUEST and
                self._in_buffer[1] == self.PROTOCOL_VERSION):
                
                print("[Cart] Sync request received")
                self.state = self.SYNC_COMPLETE
                self.last_sync_time = time.monotonic()
                self._prepare_handshake_response()
                print("[Cart] Sync complete - Ready for handshake")
                return True

        except Exception as e:
            print(f"[Cart] Sync error: {str(e)}")

        return False

    def _handle_handshake(self):
        """Handle handshake phase"""
        try:
            if self._in_buffer[0] == self.HI_CANDIDE:
                print("[Cart] Handshake received")
                self.state = self.CONNECTED
                self._prepare_connected_response()
                print("[Cart] Connected to base station!")
                return True
                    
        except Exception as e:
            print(f"[Cart] Handshake error: {str(e)}")
            
        return False

    def _handle_communication(self):
        """Handle normal operation communication"""
        try:
            if self._in_buffer[0] == self.SYNC_REQUEST:
                self._prepare_connected_response()
                return True
            elif any(self._in_buffer):  # Process other commands
                return self._process_command()
                    
        except Exception as e:
            print(f"[Cart] Communication error: {str(e)}")
            self.reset_state()
            
        return False

    def _process_command(self):
        """Process received command"""
        command = self._in_buffer[0]
        print(f"[Cart] Processing command: {hex(command)}")
        # Command processing logic here
        return True

    def reset_state(self):
        """Reset to initial state"""
        self.state = self.DISCONNECTED
        self._prepare_sync_response()
        print("[Cart] Reset to initial state")

    def is_ready(self):
        """Check if connection is established"""
        return self.state == self.CONNECTED

    def read_message(self):
        """Read a message if connection is ready"""
        if not self.is_ready():
            return None
            
        try:
            if not self.cs.value:  # Only read when selected
                with self.spi_device as device:
                    device.readinto(self._in_buffer)
                    return bytes(self._in_buffer) if any(self._in_buffer) else None
                    
        except Exception as e:
            print(f"[Cart] Read error: {str(e)}")
            
        return None

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
        
        self._setup_spi()
        self._setup_audio()
        self._setup_synth()
        self._setup_initial_state()
        print("\nCandide (v1.0) is ready... (◕‿◕✿)")
        
    def _setup_spi(self):
        print("Setting up SPI...")
        self.spi_receiver = SPIReceiver()
        
    def _setup_audio(self):
        """Initialize audio subsystem"""
        self.audio = SynthAudioOutputManager()
        
    def _setup_synth(self):
        """Initialize synthesis subsystem"""
        self.synth = Synthesizer(self.audio)
        self.current_instrument = Piano()  # Default instrument
        self.synth.set_instrument(self.current_instrument)

    def _setup_initial_state(self):
        """Set initial state for synthesizer"""
        pass  # Can be expanded as needed

    def read_spi(self):
        """Read a message from SPI if available"""
        return self.spi_receiver.read_message()

    def process_midi_message(self, data):
        """Process MIDI message and generate audio"""
        if not data:
            return

        print(f"Processing MIDI: {[hex(b) for b in data]}")

        status = data[0]
        message_type = status & 0xF0

        if message_type == 0x90:  # Note On
            note = data[1]
            velocity = data[2]
            key_id = data[3]
            event = ('note_on', note, velocity, key_id)
            print(f"Note On: note={note}, velocity={velocity}, key={key_id}")
            self.synth.process_midi_event(event)

        elif message_type == 0x80:  # Note Off
            note = data[1]
            key_id = data[3]
            event = ('note_off', note, 0, key_id)
            print(f"Note Off: note={note}, key={key_id}")
            self.synth.process_midi_event(event)

        elif message_type == 0xB0:  # Control Change
            cc_num = data[1]
            value = data[2]
            normalized_value = value / 127.0
            event = ('control_change', cc_num, value, normalized_value)
            print(f"Control Change: CC#{cc_num} = {value}")
            self.synth.process_midi_event(event)

    def update(self):
        """Main update loop"""
        try:
            # Check for base station connection
            if not self.spi_receiver.is_ready():
                self.spi_receiver.check_connection()

            message = self.read_spi()
            if message:
                print(f"Received message: {[hex(b) for b in message]}")
                self.process_midi_message(message)
            return True
        except Exception as e:
            print(f"Error in main loop: {str(e)}")
            return False

    def run(self):
        """Main run loop"""
        try:
            while self.update():
                time.sleep(Constants.MAIN_LOOP_INTERVAL)
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
