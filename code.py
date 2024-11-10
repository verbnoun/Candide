import board
import busio
import digitalio
import time
import array
from instruments import Piano, Organ, Womp, WindChime, Instrument
from synthesizer import Synthesizer, SynthAudioOutputManager
from hardware import RotaryEncoderHandler, VolumePotHandler, Constants as HWConstants
from collections import deque

class Constants:
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
    RUNNING_STATUS_TIMEOUT = 0.2  # More lenient for continuous control
    BUFFER_SIZE = 4096        # Increased for MPE bandwidth
    MESSAGE_TIMEOUT = 0.05    # More time for message assembly    
    HEARTBEAT_INTERVAL = 0.5
    MESSAGE_COUNTS_AS_HEARTBEAT = True
    CONFIG_SEND_DELAY = 0.05

    # Audio Constants
    AUDIO_BUFFER_SIZE = 4096
    SAMPLE_RATE = 44100

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
    CC_MODULATION = 1
    CC_VOLUME = 7
    CC_FILTER_RESONANCE = 71
    CC_RELEASE_TIME = 72
    CC_ATTACK_TIME = 73
    CC_FILTER_CUTOFF = 74
    CC_DECAY_TIME = 75
    CC_SUSTAIN_LEVEL = 76
    CC_CHANNEL_PRESSURE = 74

class RingBuffer:
    """Optimized ring buffer for high-bandwidth MPE MIDI data"""
    def __init__(self, size):
        self.size = size
        self.buffer = array.array('B', [0] * size)  # unsigned char array
        self.write_idx = 0
        self.read_idx = 0
        
    def write(self, data):
        """Write byte array to buffer with overflow protection"""
        bytes_written = 0
        data_len = len(data)
        
        # Fast path for small writes
        if data_len <= 3:  # Typical MIDI message size
            for byte in data:
                next_write = (self.write_idx + 1) % self.size
                if next_write != self.read_idx:
                    self.buffer[self.write_idx] = byte
                    self.write_idx = next_write
                    bytes_written += 1
                else:
                    break
            return bytes_written
            
        # Bulk write path
        space_available = self.size - self.available() - 1
        write_size = min(data_len, space_available)
        
        # Calculate continuous space to end of buffer
        to_end = self.size - self.write_idx
        
        if write_size <= to_end:
            # Single copy case
            self.buffer[self.write_idx:self.write_idx + write_size] = data[:write_size]
            self.write_idx = (self.write_idx + write_size) % self.size
            return write_size
            
        # Split copy case
        first_chunk = data[:to_end]
        second_chunk = data[to_end:write_size]
        
        self.buffer[self.write_idx:] = first_chunk
        self.buffer[:len(second_chunk)] = second_chunk
        self.write_idx = len(second_chunk)
        
        return write_size
    
    def read(self, size=None):
        """Optimized read with preallocated array"""
        available = self.available()
        if size is None:
            size = available
        else:
            size = min(size, available)
            
        if size == 0:
            return array.array('B')
            
        result = array.array('B', [0] * size)
        read_count = 0
        
        # Calculate continuous data to end of buffer
        to_end = self.size - self.read_idx
        
        if size <= to_end:
            # Single copy case
            result[0:size] = self.buffer[self.read_idx:self.read_idx + size]
            self.read_idx = (self.read_idx + size) % self.size
            return result
            
        # Split copy case
        first_chunk_size = to_end
        second_chunk_size = size - to_end
        
        result[0:first_chunk_size] = self.buffer[self.read_idx:self.read_idx + first_chunk_size]
        result[first_chunk_size:size] = self.buffer[0:second_chunk_size]
        
        self.read_idx = second_chunk_size
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
    """Optimized UART handler for high-bandwidth MPE MIDI"""
    def __init__(self, midi_callback, is_connected_callback):
        self.midi_callback = midi_callback
        self.is_connected_callback = is_connected_callback
        print(f"Initializing UART on TX={Constants.MIDI_TX}, RX={Constants.MIDI_RX}")
        
        try:
            self.uart = busio.UART(
                tx=Constants.MIDI_TX,
                rx=Constants.MIDI_RX,
                baudrate=Constants.MIDI_BAUD_RATE,
                bits=8,
                parity=None,
                stop=1,
                timeout=0.001  # Short timeout for non-blocking reads
            )
            
            # Initialize state
            self.ring_buffer = RingBuffer(Constants.BUFFER_SIZE)
            self.last_status = None
            self.last_status_time = 0
            self.current_message = array.array('B')
            self.message_start_time = 0
            self.expected_length = 0
            self.temp_buffer = bytearray(32)  # Preallocated temp buffer for UART reads
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
        """Fast message length lookup using status byte"""
        if status >= Constants.SYSTEM_MESSAGE:
            return 1
        return 3 if (status & 0xF0) not in (Constants.PROGRAM_CHANGE, Constants.CHANNEL_PRESSURE) else 2

    def _process_midi_message(self, message):
        """Process a complete MIDI message with improved MPE handling"""
        if not message:
            return
            
        try:
            status = message[0]
            channel = (status & 0x0F) + 1
            command = status & 0xF0
            key_id = channel - 1  # In MPE mode, channel maps to key
                
            self.midi_callback(message)
            
        except Exception as e:
            if str(e):
                print(f"Error processing MIDI message: {str(e)}")

    def check_for_messages(self):
        """Optimized MIDI message processing"""
        try:
            current_time = time.monotonic()
            
            if not self.is_connected_callback():
                if self.uart.in_waiting:
                    self.uart.read(self.uart.in_waiting)
                self.ring_buffer.clear()
                self.current_message = array.array('B')
                self.last_status = None
                return

            # Read available bytes in chunks
            while self.uart.in_waiting:
                bytes_read = self.uart.readinto(self.temp_buffer)
                if bytes_read:
                    self.ring_buffer.write(memoryview(self.temp_buffer)[:bytes_read])
                    
            # Process messages
            while self.ring_buffer.available():
                if not self.current_message:
                    byte = self.ring_buffer.peek()
                    
                    if byte < 0x80:  # Data byte
                        if self.last_status and \
                           (current_time - self.last_status_time) < Constants.RUNNING_STATUS_TIMEOUT:
                            self.current_message.append(self.last_status)
                        else:
                            self.ring_buffer.read(1)
                            continue
                    else:  # Status byte
                        self.last_status = byte
                        self.last_status_time = current_time
                        self.ring_buffer.read(1)
                        self.current_message.append(byte)
                    
                    self.message_start_time = current_time
                    self.expected_length = self._get_message_length(self.last_status)
                
                # Complete message assembly
                while len(self.current_message) < self.expected_length and self.ring_buffer.available():
                    self.current_message.append(self.ring_buffer.read(1)[0])
                
                if len(self.current_message) == self.expected_length:
                    self._process_midi_message(bytes(self.current_message))
                    self.current_message = array.array('B')
                    continue
                    
                if (current_time - self.message_start_time) > Constants.MESSAGE_TIMEOUT:
                    self.current_message = array.array('B')
                
                break
                
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
        print("\nWakeup Candide!")
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
        self.last_config_time = 0
        
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
        Organ()
        Womp()
        WindChime()
        
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

    def _send_connected_messages(self):
        """Send initial messages when connected, including CC configuration"""
        if not self.has_sent_hello:
            if self.uart.send_text("hello from candide"):
                time.sleep(Constants.CONFIG_SEND_DELAY)  # Give Bartleby time to process
                
                # Send initial instrument config
                config_string = self.current_instrument.generate_cc_config()
                if config_string and self.uart.send_text(config_string):
                    print(f"Sent initial config: {config_string}")
                    self.last_config_time = time.monotonic()
                    self.last_message_time = self.last_config_time
                    self.has_sent_hello = True

    def _send_heartbeat(self):
        """Send heartbeat message if needed"""
        current_time = time.monotonic()
        
        # Only send heartbeat if we haven't sent any message recently
        if (current_time - self.last_message_time) >= Constants.HEARTBEAT_INTERVAL:
            if self.uart.send_text("♡"):
                self.last_message_time = current_time

    def _send_instrument_config(self):
        """Send current instrument's CC configuration"""
        if self.connected:
            config_string = self.current_instrument.generate_cc_config()
            if config_string and self.uart.send_text(config_string):
                if Constants.DEBUG:
                    print(f"Sent instrument config: {config_string}")
                self.last_config_time = time.monotonic()
                self.last_message_time = self.last_config_time
                return True
        return False

    def is_connected(self):
        """Helper method to check connection state"""
        return self.connected

    def process_midi_message(self, data):
        """Process MPE MIDI message"""
        if not data or not self.connected:
            return

        try:
            status = data[0] & 0xF0  # Strip channel
            channel = (data[0] & 0x0F) + 1  # Get channel (1-16)
            
            # Master channel is 1, Member channels are 2-16
            is_master_channel = (channel == 1)
            
            if Constants.DEBUG:
                print(f"\nMPE Message:")
                print(f"  Channel: {channel} ({'Master' if is_master_channel else 'Member'})")
                print(f"  Status: 0x{status:02X}")

            if status == Constants.NOTE_ON and data[2] > 0:
                if Constants.DEBUG:
                    print(f"  Note On:")
                    print(f"    Channel: {channel}")
                    print(f"    Note: {data[1]}")
                    print(f"    Velocity: {data[2]}")
                    if not is_master_channel:
                        print("    Type: MPE Member Channel Note")
                event = ('note_on', data[1], data[2], channel-1)
                self.synth.process_midi_event(event)
                    
            elif status == Constants.NOTE_OFF or (status == Constants.NOTE_ON and data[2] == 0):
                if Constants.DEBUG:
                    print(f"  Note Off:")
                    print(f"    Channel: {channel}")
                    print(f"    Note: {data[1]}")
                    if not is_master_channel:
                        print("    Type: MPE Member Channel Note")
                event = ('note_off', data[1], 0, channel-1)
                self.synth.process_midi_event(event)
                    
            elif status == Constants.CONTROL_CHANGE:
                normalized_value = data[2] / 127.0
                if Constants.DEBUG:
                    print(f"  Control Change:")
                    print(f"    Channel: {channel}")
                    print(f"    Controller: {data[1]}")
                    print(f"    Value: {data[2]} ({normalized_value:.3f})")
                    if not is_master_channel:
                        print("    Type: MPE Member Channel CC")
                event = ('control_change', data[1], data[2], normalized_value)
                self.synth.process_midi_event(event)
                        
            elif status == Constants.PITCH_BEND:
                lsb = data[1]
                msb = data[2]
                bend_value = (msb << 7) + lsb
                normalized_bend = (bend_value - 8192) / 8192.0
                if Constants.DEBUG:
                    print(f"  Pitch Bend:")
                    print(f"    Channel: {channel}")
                    print(f"    LSB: {lsb}, MSB: {msb}")
                    print(f"    Combined Value: {bend_value}")
                    print(f"    Normalized: {normalized_bend:+.3f}")
                    if not is_master_channel:
                        print("    Type: MPE Member Channel Pitch Bend")
                event = ('pitch_bend', channel-1, normalized_bend)
                self.synth.process_midi_event(event)

            elif status == Constants.CHANNEL_PRESSURE:
                normalized_pressure = data[1] / 127.0
                if Constants.DEBUG:
                    print(f"  Channel Pressure:")
                    print(f"    Channel: {channel}")
                    print(f"    Value: {data[1]} ({normalized_pressure:.3f})")
                    if not is_master_channel:
                        print("    Type: MPE Member Channel Pressure")
                event = ('pressure', channel-1, normalized_pressure)
                self.synth.process_midi_event(event)
                    
        except Exception as e:
            print(f"Error processing MIDI message: {str(e)}")

    def _check_volume(self):
        """Check volume pot and update mixer"""
        current_time = time.monotonic()
        
        if (current_time - self.last_volume_scan) >= HWConstants.UPDATE_INTERVAL:
            new_volume = self.volume_pot.read_pot()
            if new_volume is not None:
                # if Constants.DEBUG:
                #     print(f"Volume: {new_volume:.3f}")
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
                        # Send new instrument's CC config
                        if self.connected:
                            self._send_instrument_config()
            
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