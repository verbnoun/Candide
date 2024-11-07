import board
import busio
import digitalio
import time
import array
from instruments import Piano, ElectricOrgan, BendableOrgan, Instrument
from synthesizer import Synthesizer, SynthAudioOutputManager
from hardware import RotaryEncoderHandler, VolumePotHandler, Constants as HWConstants
from collections import deque

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
    
    # MIDI Constants
    MIDI_BAUD_RATE = 31250
    RUNNING_STATUS_TIMEOUT = 0.3  # Time before running status is invalidated
    BUFFER_SIZE = 1024  # Ring buffer size
    MESSAGE_TIMEOUT = 0.1  # Time before partial message is considered stale
    HEARTBEAT_INTERVAL = 0.5  # Send heartbeat every 0.5 seconds
    MESSAGE_COUNTS_AS_HEARTBEAT = True

    # MIDI Message Types
    NOTE_OFF = 0x80
    NOTE_ON = 0x90
    POLY_PRESSURE = 0xA0
    CONTROL_CHANGE = 0xB0
    PROGRAM_CHANGE = 0xC0
    CHANNEL_PRESSURE = 0xD0
    PITCH_BEND = 0xE0
    SYSTEM_MESSAGE = 0xF0

    # MIDI Control Numbers
    CC_CHANNEL_PRESSURE = 74

class RingBuffer:
    """Fixed-size ring buffer for MIDI data"""
    def __init__(self, size):
        self.size = size
        self.buffer = array.array('B', [0] * size)  # unsigned char array
        self.write_idx = 0
        self.read_idx = 0
        
    def write(self, data):
        """Write byte array to buffer, returns number of bytes written"""
        bytes_written = 0
        for byte in data:
            next_write = (self.write_idx + 1) % self.size
            if next_write != self.read_idx:  # if not full
                self.buffer[self.write_idx] = byte
                self.write_idx = next_write
                bytes_written += 1
            else:
                break
        return bytes_written
    
    def read(self, size=None):
        """Read up to size bytes from buffer, or all available if size=None"""
        result = array.array('B')
        available = self.available()
        if size is None:
            size = available
        else:
            size = min(size, available)
            
        for _ in range(size):
            if self.read_idx != self.write_idx:
                result.append(self.buffer[self.read_idx])
                self.read_idx = (self.read_idx + 1) % self.size
                
        return result
    
    def peek(self, offset=0):
        """Look at byte at read_idx + offset without removing it"""
        if offset >= self.available():
            return None
        peek_idx = (self.read_idx + offset) % self.size
        return self.buffer[peek_idx]
    
    def available(self):
        """Return number of bytes available to read"""
        if self.write_idx >= self.read_idx:
            return self.write_idx - self.read_idx
        return self.size - (self.read_idx - self.write_idx)
    
    def clear(self):
        """Reset buffer to empty state"""
        self.write_idx = self.read_idx = 0

class UartHandler:
    """Handles MIDI input on RX and text output on TX with improved buffering"""
    def __init__(self, midi_callback, is_connected_callback):
        self.midi_callback = midi_callback
        self.is_connected_callback = is_connected_callback
        print(f"Initializing UART on TX={Constants.MIDI_TX}, RX={Constants.MIDI_RX}")
        
        try:
            self.uart = busio.UART(tx=Constants.MIDI_TX,
                                rx=Constants.MIDI_RX,
                                baudrate=Constants.MIDI_BAUD_RATE,
                                bits=8,
                                parity=None,
                                stop=1)
            
            # Initialize state
            self.ring_buffer = RingBuffer(Constants.BUFFER_SIZE)
            self.last_status = None
            self.last_status_time = 0
            self.current_message = array.array('B')
            self.message_start_time = 0
            self.expected_length = 0
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
            if str(e):
                print(f"Error sending text: {str(e)}")
            return False

    def _get_message_length(self, status):
        """Return expected message length (including status byte) for a given status byte"""
        if status >= Constants.SYSTEM_MESSAGE:
            return 1  # System message (we don't handle sysex yet)
        command = status & 0xF0
        if command in (Constants.PROGRAM_CHANGE, Constants.CHANNEL_PRESSURE):
            return 2
        return 3  # All other channel messages

    def _process_midi_message(self, message):
        """Process a complete MIDI message"""
        if not message:
            return
            
        try:
            status = message[0]
            channel = (status & 0x0F) + 1
            command = status & 0xF0
            key_id = channel - 1  # In MPE mode, channel maps to key
            
            if command == Constants.NOTE_ON and len(message) >= 3:
                if message[2] > 0:  # Note On with velocity > 0
                    print(f"\nKey {key_id} MIDI Events:")
                    print(f"  Note ON:")
                    print(f"    Channel: {channel}")
                    print(f"    Note: {message[1]}")
                    print(f"    Velocity: {message[2]}")
                else:  # Note On with velocity 0 = Note Off
                    print(f"\nKey {key_id} MIDI Events:")
                    print(f"  Note OFF:")
                    print(f"    Channel: {channel}")
                    print(f"    Note: {message[1]}")
                    
            elif command == Constants.NOTE_OFF and len(message) >= 3:
                print(f"\nKey {key_id} MIDI Events:")
                print(f"  Note OFF:")
                print(f"    Channel: {channel}")
                print(f"    Note: {message[1]}")
                    
            elif command == Constants.CONTROL_CHANGE and len(message) >= 3:
                if message[1] == Constants.CC_CHANNEL_PRESSURE:
                    print(f"\nKey {key_id} MIDI Events:")
                    print(f"  MIDI Updates:")
                    print(f"    Channel: {channel}")
                    print(f"    Pressure: {message[2]}")
                    
            elif command == Constants.PITCH_BEND and len(message) >= 3:
                value = (message[2] << 7) + message[1]
                normalized_bend = (value - 8192) / 8192.0
                print(f"    Pitch Bend: {normalized_bend:+.3f}")
                
            self.midi_callback(message)
            
        except Exception as e:
            if str(e):
                print(f"Error processing MIDI message: {str(e)}")

    def check_for_messages(self):
        """Check for and process any incoming MIDI messages"""
        try:
            current_time = time.monotonic()
            
            # If not connected, clear buffers
            if not self.is_connected_callback():
                if self.uart.in_waiting:
                    self.uart.read(self.uart.in_waiting)
                self.ring_buffer.clear()
                self.current_message = array.array('B')
                self.last_status = None
                return

            # Read any available bytes into ring buffer
            if self.uart.in_waiting:
                new_bytes = self.uart.read(self.uart.in_waiting)
                if new_bytes:
                    self.ring_buffer.write(new_bytes)
                    
            # Process bytes in ring buffer
            while self.ring_buffer.available():
                # Start new message if needed
                if not self.current_message:
                    byte = self.ring_buffer.peek()
                    
                    # Handle running status
                    if byte < 0x80:  # Data byte
                        if self.last_status and \
                           (current_time - self.last_status_time) < Constants.RUNNING_STATUS_TIMEOUT:
                            self.current_message.append(self.last_status)
                        else:
                            self.ring_buffer.read(1)  # Discard invalid data byte
                            continue
                    else:  # Status byte
                        self.last_status = byte
                        self.last_status_time = current_time
                    
                    self.message_start_time = current_time
                    self.expected_length = self._get_message_length(self.last_status)
                
                # Add bytes to current message
                while len(self.current_message) < self.expected_length and self.ring_buffer.available():
                    self.current_message.append(self.ring_buffer.read(1)[0])
                
                # Process complete message
                if len(self.current_message) == self.expected_length:
                    self._process_midi_message(self.current_message)
                    self.current_message = array.array('B')
                    continue
                    
                # Check for message timeout
                if (current_time - self.message_start_time) > Constants.MESSAGE_TIMEOUT:
                    self.current_message = array.array('B')
                
                break  # Exit loop if we need more bytes
                
        except Exception as e:
            if str(e):
                print(f"Error reading UART: {str(e)}")

    def cleanup(self):
        """Clean shutdown"""
        try:
            self.uart.deinit()
            print("UART cleaned up")
        except Exception as e:
            if str(e):
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
        self.last_message_time = 0
        self.has_sent_hello = False
        
        # Timing state
        self.last_encoder_scan = 0
        self.last_volume_scan = 0
        
        try:
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
        if not data or not self.connected:
            return

        try:
            status = data[0] & 0xF0  # Strip channel
            channel = (data[0] & 0x0F) + 1  # Get channel (1-16)
            
            if status == Constants.NOTE_ON and data[2] > 0:  # Note On with velocity > 0
                event = ('note_on', data[1], data[2], channel-1)
                self.synth.process_midi_event(event)
                
            elif status == Constants.NOTE_OFF or (status == Constants.NOTE_ON and data[2] == 0):
                event = ('note_off', data[1], 0, channel-1)
                self.synth.process_midi_event(event)
                
            elif status == Constants.CONTROL_CHANGE:
                if data[1] == Constants.CC_CHANNEL_PRESSURE:
                    normalized_value = data[2] / 127.0
                    event = ('control_change', data[1], data[2], normalized_value)
                    self.synth.process_midi_event(event)
                    
            elif status == Constants.PITCH_BEND:
                value = (data[2] << 7) + data[1]
                event = ('pitch_bend', data[1], data[2], channel-1)
                self.synth.process_midi_event(event)
                
        except Exception as e:
            print(f"Error processing MIDI message: {str(e)}")

    def _check_volume(self):
        """Check volume pot and update mixer"""
        current_time = time.monotonic()
        
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
        
        if (current_time - self.last_encoder_scan) >= HWConstants.ENCODER_SCAN_INTERVAL:
            events = self.encoder.read_encoder()
            
            if Constants.DEBUG and events:
                print(f"Encoder events: {events}")
            
            for event_type, direction in events:
                if event_type == 'instrument_change':
                    new_instrument = Instrument.handle_instrument_change(direction)
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