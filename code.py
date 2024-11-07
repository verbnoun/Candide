import board
import busio
import digitalio
import time
from instruments import Piano, ElectricOrgan, BendableOrgan, Instrument
from synthesizer import Synthesizer, SynthAudioOutputManager
from hardware import RotaryEncoderHandler, VolumePotHandler, Constants as HWConstants

class Constants:
    # System Constants
    DEBUG = True
    SEE_HEARTBEAT = False  

    # Hardware Setup Delay
    SETUP_DELAY = 0.1
    
    # UART Pins
    MIDI_TX = board.GP16  # TX for text output 
    MIDI_RX = board.GP17  # RX for MIDI input
    
    # Detect Pin
    DETECT_PIN = board.GP22
    
    # Heartbeat timing
    HEARTBEAT_INTERVAL = 0.5  # Send heartbeat every 0.5 seconds
    MESSAGE_COUNTS_AS_HEARTBEAT = True  # Any message resets heartbeat timer

    # MIDI Constants
    CC_CHANNEL_PRESSURE = 74  # Standard MPE channel pressure
    PITCH_BEND_CENTER = 8192

class UartHandler:
    """Handles MIDI input on RX and text output on TX"""
    def __init__(self, midi_callback, is_connected_callback):
        self.midi_callback = midi_callback
        self.is_connected_callback = is_connected_callback
        print(f"Initializing UART on TX={Constants.MIDI_TX}, RX={Constants.MIDI_RX}")
        
        try:
            # Initialize UART at MIDI baud rate for both MIDI and text
            self.uart = busio.UART(tx=Constants.MIDI_TX,
                                rx=Constants.MIDI_RX,
                                baudrate=31250,
                                bits=8,
                                parity=None,
                                stop=1)
            
            # Buffer for incomplete MIDI messages
            self.buffer = bytearray()
            self.last_byte_time = time.monotonic()
            print("UART initialization successful")
            
        except Exception as e:
            print(f"UART initialization error: {str(e)}")
            raise

    def send_text(self, message):
        """Send a text message via TX pin"""
        try:
            self.uart.write(bytes(message + "\n", 'utf-8'))
            if Constants.DEBUG and (Constants.SEE_HEARTBEAT or message != "♡"):
                print(f"Sent text: {message}")
            return True
        except Exception as e:
            if str(e):  # Only print if there's an actual error message
                print(f"Error sending text: {str(e)}")
            return False

    def check_for_messages(self):
        """Check for and process any incoming MIDI messages from RX pin"""
        try:
            current_time = time.monotonic()
            
            # If not connected, clear any waiting data and the buffer
            if not self.is_connected_callback():
                if self.uart.in_waiting:
                    self.uart.read(self.uart.in_waiting)  # Clear waiting data
                self.buffer.clear()  # Clear existing buffer
                return

            # Clear buffer if too much time has passed since last byte
            if current_time - self.last_byte_time > 0.1:  # 100ms timeout
                if self.buffer:
                    self.buffer = bytearray()

            # Check for available bytes
            if self.uart.in_waiting:
                # Read all available bytes
                new_bytes = self.uart.read(self.uart.in_waiting)
                if new_bytes:
                    self.buffer.extend(new_bytes)
                    self.last_byte_time = current_time

                    # Process complete MIDI messages
                    while self._process_midi_buffer():
                        pass

        except Exception as e:
            if str(e):  # Only print if there's an actual error message
                print(f"Error reading UART: {str(e)}")

    def _process_midi_buffer(self):
        """Process MIDI buffer and return True if a message was handled"""
        if not self.buffer:
            return False

        try:
            # Look for status byte
            if self.buffer[0] < 0x80:
                self.buffer = bytearray()
                return False

            status = self.buffer[0] & 0xF0  # Strip channel
            channel = (self.buffer[0] & 0x0F) + 1  # Get channel (1-16)
            key_id = channel - 1  # In MPE mode, channel maps to key

            # Determine message length
            if status in [0x80, 0x90, 0xA0, 0xB0, 0xE0]:  # 3-byte messages
                if len(self.buffer) >= 3:
                    msg = self.buffer[:3]
                    self.buffer = self.buffer[3:]
                    
                    if status == 0x90 and msg[2] > 0:  # Note On with velocity > 0
                        print(f"\nKey {key_id} MIDI Events:")
                        print(f"  Note ON:")
                        print(f"    Channel: {channel}")
                        print(f"    Note: {msg[1]}")
                        print(f"    Velocity: {msg[2]}")
                        
                    elif status == 0x80 or (status == 0x90 and msg[2] == 0):  # Note Off
                        print(f"\nKey {key_id} MIDI Events:")
                        print(f"  Note OFF:")
                        print(f"    Channel: {channel}")
                        print(f"    Note: {msg[1]}")
                            
                    elif status == 0xB0:  # Control Change
                        if msg[1] == Constants.CC_CHANNEL_PRESSURE:  # Channel Pressure
                            print(f"\nKey {key_id} MIDI Events:")
                            print(f"  MIDI Updates:")
                            print(f"    Channel: {channel}")
                            print(f"    Pressure: {msg[2]}")
                    
                    elif status == 0xE0:  # Pitch Bend
                        value = (msg[2] << 7) + msg[1]
                        normalized_bend = (value - Constants.PITCH_BEND_CENTER) / Constants.PITCH_BEND_CENTER
                        print(f"    Pitch Bend: {normalized_bend:+.3f}")
                        
                    self.midi_callback(msg)
                    return True
                    
            elif status in [0xC0, 0xD0]:  # 2-byte messages
                if len(self.buffer) >= 2:
                    msg = self.buffer[:2]
                    self.buffer = self.buffer[2:]
                    
                    if status == 0xC0:  # Program Change
                        print(f"Program Change - channel: {channel}, program: {msg[1]}")
                    elif status == 0xD0:  # Channel Pressure
                        print(f"Channel Pressure - channel: {channel}, pressure: {msg[1]}")
                        
                    self.midi_callback(msg)
                    return True
                    
            else:  # Single byte or system messages
                msg = self.buffer[:1]
                self.buffer = self.buffer[1:]
                print(f"System message: {[hex(b) for b in msg]}")
                self.midi_callback(msg)
                return True

        except Exception as e:
            if str(e):  # Only print if there's an actual error message
                print(f"Error processing MIDI buffer: {str(e)}")
            self.buffer = bytearray()
            
        return False

    def cleanup(self):
        """Clean shutdown"""
        try:
            self.uart.deinit()
            print("UART cleaned up")
        except Exception as e:
            if str(e):  # Only print if there's an actual error message
                print(f"Error during cleanup: {str(e)}")

class Candide:
    def __init__(self):
        print("\nInitializing Candide...")
        self.audio = None
        self.synth = None
        self.current_instrument = None
        self.uart = None
        self.detect_pin = None
        self.connected = False
        self.encoder = None
        self.volume_pot = None
        
        # Communication state
        self.last_message_time = 0  # Track when we last sent any message
        self.has_sent_hello = False  # Track if we've sent initial hello
        
        # Timing state for hardware
        self.last_encoder_scan = 0
        self.last_volume_scan = 0
        
        try:
            # Setup order matters - audio system first, then hardware, then synth
            self._setup_audio()
            self._setup_hardware()
            self._setup_synth()
            self._setup_uart()
            self._setup_initial_state()
            print("\nCandide (v1.0) is ready... (◕‿◕✿)")
        except Exception as e:
            print(f"Initialization error: {str(e)}")
            raise
        
    def _setup_audio(self):
        """Initialize audio subsystem"""
        print("Setting up audio...")
        self.audio = SynthAudioOutputManager()
        
    def _setup_hardware(self):
        """Initialize hardware components"""
        print("Setting up hardware...")
        self.encoder = RotaryEncoderHandler(
            HWConstants.INSTRUMENT_ENC_CLK,
            HWConstants.INSTRUMENT_ENC_DT
        )
        self.volume_pot = VolumePotHandler(HWConstants.VOLUME_POT)
        
        # Get and set initial volume
        initial_volume = self.volume_pot.normalize_value(self.volume_pot.pot.value)
        if Constants.DEBUG:
            print(f"Initial volume: {initial_volume:.3f}")
        self.audio.set_volume(initial_volume)
        
    def _setup_synth(self):
        """Initialize synthesis subsystem"""
        print("Setting up synthesizer...")
        self.synth = Synthesizer(self.audio)
        
        # Create instruments (they'll auto-register themselves)
        Piano()
        ElectricOrgan()
        BendableOrgan()
        
        if Constants.DEBUG:
            print(f"Available instruments: {[i.name for i in Instrument.available_instruments]}")
        
        self.current_instrument = Instrument.get_current_instrument()
        self.synth.set_instrument(self.current_instrument)

    def _setup_uart(self):
        """Initialize UART for MIDI input and text output"""
        print("Setting up UART...")
        self.uart = UartHandler(self.process_midi_message, self.is_connected)

    def _setup_initial_state(self):
        """Set initial state for synthesizer"""
        print("Setting up initial state...")
        
        # Setup detect pin as input with pull-down
        self.detect_pin = digitalio.DigitalInOut(Constants.DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        # Check initial connection state
        self.connected = self.detect_pin.value
        if self.connected:
            print("Connected to Bartleby")
            self._send_connected_messages()
        else:
            print("Not connected to Bartleby")

    def is_connected(self):
        """Helper method to check connection state"""
        return self.connected

    def _send_connected_messages(self):
        """Send initial messages when connected"""
        if not self.has_sent_hello:  # Only send hello once per connection
            if self.uart.send_text("hello from candide"):
                self.last_message_time = time.monotonic()
                self.has_sent_hello = True

    def _send_heartbeat(self):
        """Send heartbeat message if needed"""
        current_time = time.monotonic()
        
        # Only send heartbeat if we haven't sent any message recently
        if (current_time - self.last_message_time) >= Constants.HEARTBEAT_INTERVAL:
            if self.uart.send_text("♡"):
                self.last_message_time = current_time

    def process_midi_message(self, data):
        """Process MIDI message"""
        if not data or not self.connected:  # Double check connection
            return

        try:
            status = data[0] & 0xF0  # Strip channel
            
            if status == 0x90:  # Note On
                event = ('note_on', data[1], data[2], 0)
                self.synth.process_midi_event(event)
                
            elif status == 0x80:  # Note Off
                event = ('note_off', data[1], 0, 0)
                self.synth.process_midi_event(event)
                
            elif status == 0xB0:  # Control Change
                normalized_value = data[2] / 127.0
                event = ('control_change', data[1], data[2], normalized_value)
                self.synth.process_midi_event(event)
                
        except Exception as e:
            print(f"Error processing MIDI message: {str(e)}")

    def _check_volume(self):
        """Check volume pot and update mixer"""
        current_time = time.monotonic()
        
        # Only check at specified interval
        if (current_time - self.last_volume_scan) >= HWConstants.UPDATE_INTERVAL:
            new_volume = self.volume_pot.read_pot()
            if new_volume is not None:
                if Constants.DEBUG:
                    print(f"Volume: {new_volume:.3f}")
                self.audio.set_volume(new_volume)
            self.last_volume_scan = current_time

    def _check_encoder(self):
        """Check encoder and handle any changes"""
        current_time = time.monotonic()
        
        # Only check at specified interval
        if (current_time - self.last_encoder_scan) >= HWConstants.ENCODER_SCAN_INTERVAL:
            events = self.encoder.read_encoder()

            if Constants.DEBUG and events:
                print(f"Encoder events: {events}")
            
            for event_type, direction in events:
                if event_type == 'instrument_change':
                    # Use instrument class method to change instrument
                    if Constants.DEBUG:
                        print(f"Current instrument index: {Instrument.current_instrument_index}")
                    new_instrument = Instrument.handle_instrument_change(direction)
                    if Constants.DEBUG:
                        print(f"New instrument index: {Instrument.current_instrument_index}")
                    if new_instrument != self.current_instrument:
                        print(f"Switching to instrument: {new_instrument.name}")
                        self.current_instrument = new_instrument
                        self.synth.set_instrument(self.current_instrument)  

            
            self.last_encoder_scan = current_time

    def update(self):
        """Main update loop"""
        try:
            # Check connection state
            current_state = self.detect_pin.value
            
            # Handle new connection
            if not self.connected and current_state:
                print("Connected to Bartleby")
                
                # First clear any stale MIDI data
                while self.uart.uart.in_waiting:
                    self.uart.uart.read(self.uart.uart.in_waiting)
                self.uart.buffer = bytearray()
                
                # Now start fresh
                self.connected = True
                self.has_sent_hello = False
                self._send_connected_messages()
            
            # Handle disconnection
            elif self.connected and not current_state:
                print("Detached from Bartleby")
                self.connected = False
                self.last_message_time = 0
                self.has_sent_hello = False
                
                # Clear any pending data on disconnect too
                while self.uart.uart.in_waiting:
                    self.uart.uart.read(self.uart.uart.in_waiting)
                self.uart.buffer = bytearray()
            
            # Check encoder regardless of connection state
            self._check_encoder()
            self._check_volume()
            
            # Only process MIDI and send heartbeat if connected
            if self.connected:
                # Check for MIDI messages
                self.uart.check_for_messages()
                
                # Send heartbeat if needed
                self._send_heartbeat()
            
            # Always update synthesis
            self.synth.update([])
            
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
        if self.uart:
            print("Cleaning up UART...")
            self.uart.cleanup()
        if self.detect_pin:
            self.detect_pin.deinit()
        if self.encoder:
            print("Cleaning up encoder...")
            self.encoder.cleanup()
        if self.volume_pot:
            self.volume_pot.pot.deinit()
        print("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁")

def main():
    try:
        synth = Candide()
        synth.run()
    except Exception as e:
        print(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    main()
