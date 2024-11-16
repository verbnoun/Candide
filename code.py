import board
import busio
import digitalio
import time
from synthesizer import Synthesizer, SynthAudioOutputManager
from hardware import RotaryEncoderHandler, VolumePotHandler, Constants as HWConstants
from instruments import Piano, Organ, Womp, WindChime, Instrument
from midi import MidiLogic

class Constants:
    # Debug Settings
    DEBUG = False
    
    # Hardware Setup
    SETUP_DELAY = 0.1
    
    # UART/MIDI Pins
    UART_TX = board.GP16
    UART_RX = board.GP17
    
    # Connection
    DETECT_PIN = board.GP22
    MESSAGE_TIMEOUT = 0.05
    HELLO_INTERVAL = 0.5  # How often to send hello when detecting
    HEARTBEAT_INTERVAL = 1.0  # How often to send heartbeat when connected
    HANDSHAKE_TIMEOUT = 5.0  # Maximum time to wait during any handshake stage
    HANDSHAKE_MAX_RETRIES = 10  # Maximum number of hello messages to send
    
    # New Connection Constants
    STARTUP_DELAY = 1.0  # Give devices time to initialize
    RETRY_DELAY = 5.0    # Delay after max retries before trying again
    RETRY_INTERVAL = 0.25   # Delay between connection attempts
    ERROR_RECOVERY_DELAY = 0.5  # Delay after errors before retry
    BUFFER_CLEAR_TIMEOUT = 0.1  # Time to wait for buffer clearing
    MAX_RETRIES = 3
    
    # UART Settings
    UART_BAUDRATE = 31250
    UART_TIMEOUT = 0.001
    
    # MIDI CC for Handshake
    HANDSHAKE_CC = 119  # Undefined CC number
    HANDSHAKE_VALUE = 42  # Arbitrary value
    WELCOME_VALUE = 43  # Handshake value + 1

class TransportManager:
    """Manages shared UART instance for both text and MIDI communication"""
    def __init__(self, tx_pin, rx_pin, baudrate=31250, timeout=0.001):
        print("Initializing shared transport...")
        self.uart = busio.UART(
            tx=tx_pin,
            rx=rx_pin,
            baudrate=baudrate,
            timeout=timeout,
            bits=8,
            parity=None,
            stop=1
        )
        print("Shared transport initialized")
        
    def get_uart(self):
        """Get the UART instance for text or MIDI use"""
        return self.uart
        
    def flush_buffers(self):
        """Clear any pending data in UART buffers"""
        start_time = time.monotonic()
        while (time.monotonic() - start_time) < Constants.BUFFER_CLEAR_TIMEOUT:
            if self.uart.in_waiting:
                self.uart.read()
            else:
                break
        
    def cleanup(self):
        """Clean shutdown of transport"""
        if self.uart:
            self.flush_buffers()
            self.uart.deinit()

class TextUart:
    """Handles text-based UART communication for sending config only"""
    def __init__(self, uart):
        self.uart = uart
        self.last_write = 0
        print("Text protocol initialized")

    def write(self, message):
        """Write text message with minimum delay between writes"""
        current_time = time.monotonic()
        delay_needed = Constants.MESSAGE_TIMEOUT - (current_time - self.last_write)
        if delay_needed > 0:
            time.sleep(delay_needed)
            
        if isinstance(message, str):
            message = message.encode('utf-8')
        result = self.uart.write(message)
        self.last_write = time.monotonic()
        return result

class AudioManager:
    def __init__(self):
        self.audio = None
        self._setup_audio()

    def _setup_audio(self):
        """Initialize audio subsystem"""
        print("Setting up audio...")
        self.audio = SynthAudioOutputManager()

    def set_volume(self, volume):
        self.audio.set_volume(volume)

class HardwareManager:
    def __init__(self):
        print("Setting up hardware...")
        self.encoder = None
        self.volume_pot = None
        self._setup_hardware()

    def _setup_hardware(self):
        """Initialize hardware components"""
        self.encoder = RotaryEncoderHandler(
            HWConstants.INSTRUMENT_ENC_CLK,
            HWConstants.INSTRUMENT_ENC_DT
        )
        self.volume_pot = VolumePotHandler(HWConstants.VOLUME_POT)

    def get_initial_volume(self):
        return self.volume_pot.normalize_value(self.volume_pot.pot.value)

    def read_encoder(self):
        return self.encoder.read_encoder()

    def read_pot(self):
        return self.volume_pot.read_pot()

class SynthManager:
    def __init__(self, audio_manager):
        self.synth = None
        self.current_instrument = None
        self.audio_manager = audio_manager
        self._setup_synth()

    def _setup_synth(self):
        """Initialize synthesis subsystem"""
        print("Setting up synthesizer...")
        self.synth = Synthesizer(self.audio_manager.audio)
        
        if Constants.DEBUG:
            print(f"Available instruments: {[i.name for i in Instrument.available_instruments]}")
        
        self.current_instrument = Instrument.get_current_instrument()
        self.synth.set_instrument(self.current_instrument)

    def set_instrument(self, instrument):
        self.current_instrument = instrument
        self.synth.set_instrument(instrument)

    def update(self):
        self.synth.update()

    def process_midi_events(self, events):
        """Process MIDI events through the synthesizer"""
        if events:
            if Constants.DEBUG:
                print("MIDI messages received")
            self.synth.process_mpe_events(events)
            
    def get_current_config(self):
        """Get current instrument's CC configuration"""
        if self.current_instrument:
            return self.current_instrument.generate_cc_config()
        return None

class CandideConnectionManager:
    """
    Manages connection state and handshake protocol for Candide (Cartridge).
    Uses text UART for sending config and hello, receives MIDI responses.
    """
    # States
    STANDALONE = 0      # Not inserted
    DETECTED = 1        # Inserted but no communication
    HANDSHAKING = 2     # In handshake process
    CONNECTED = 3       # Fully connected and operational
    RETRY_DELAY = 4     # Waiting before retrying connection
    
    def __init__(self, text_uart, synth_manager, transport_manager):
        self.uart = text_uart
        self.synth_manager = synth_manager
        self.transport = transport_manager
        
        # Setup detect pin as input with pulldown
        self.detect_pin = digitalio.DigitalInOut(Constants.DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        # Connection state
        self.state = self.STANDALONE
        self.last_hello_time = 0
        self.last_heartbeat_time = 0
        self.handshake_start_time = 0
        self.hello_count = 0
        self.retry_start_time = 0
        
        print("Candide connection manager initialized")
        
    def update_state(self):
        """Main state machine update"""
        current_time = time.monotonic()
        
        # Check physical connection
        if not self.detect_pin.value:
            if self.state != self.STANDALONE:
                self._handle_disconnection()
            return
            
        # Handle state-specific updates
        if self.state == self.STANDALONE and self.detect_pin.value:
            self._handle_initial_detection()
            
        elif self.state == self.DETECTED:
            if current_time - self.last_hello_time >= Constants.HELLO_INTERVAL:
                if self.hello_count < Constants.HANDSHAKE_MAX_RETRIES:
                    self._send_hello()
                    self.hello_count += 1
                else:
                    print("Max hello retries reached - entering retry delay")
                    self.state = self.RETRY_DELAY
                    self.retry_start_time = current_time
                    self.hello_count = 0  # Reset for next attempt
                    
        elif self.state == self.RETRY_DELAY:
            # Wait for 5 seconds before attempting to reconnect
            if current_time - self.retry_start_time >= Constants.RETRY_DELAY:
                print("Retry delay complete - returning to DETECTED state")
                self.state = self.DETECTED
                
        elif self.state == self.HANDSHAKING:
            if current_time - self.handshake_start_time >= Constants.HANDSHAKE_TIMEOUT:
                print("Handshake timeout - returning to DETECTED state")
                self.state = self.DETECTED
                self.hello_count = 0
                
        elif self.state == self.CONNECTED:
            if current_time - self.last_heartbeat_time >= Constants.HEARTBEAT_INTERVAL:
                self._send_heartbeat()
                
    def handle_midi_message(self, event):
        """Process incoming MIDI messages for handshake protocol"""
        if not event or event['type'] != 'cc':
            return
            
        # Check for handshake CC
        if (event['channel'] == 0 and 
            event['data']['number'] == Constants.HANDSHAKE_CC):
            
            if (event['data']['value'] == Constants.HANDSHAKE_VALUE and 
                self.state == self.DETECTED):
                print("Handshake CC received - sending config")
                self.state = self.HANDSHAKING
                self.handshake_start_time = time.monotonic()
                self._send_config()
                self.state = self.CONNECTED  # Candide is done after sending config
                print("Connection established")
                
    def _handle_initial_detection(self):
        """Handle initial physical connection"""
        print("Base station detected - initializing connection")
        self.transport.flush_buffers()
        time.sleep(Constants.SETUP_DELAY)
        self.state = self.DETECTED
        self.hello_count = 0
        self._send_hello()
        
    def _handle_disconnection(self):
        """Handle physical disconnection"""
        print("Base station disconnected")
        self.transport.flush_buffers()
        self.state = self.STANDALONE
        self.hello_count = 0
        
    def _send_hello(self):
        """Send hello message"""
        try:
            self.uart.write("hello\n")
            self.last_hello_time = time.monotonic()
        except Exception as e:
            print(f"Failed to send hello: {str(e)}")
            
    def _send_heartbeat(self):
        """Send heartbeat message"""
        try:
            self.uart.write("♥︎\n")
            self.last_heartbeat_time = time.monotonic()
        except Exception as e:
            print(f"Failed to send heartbeat: {str(e)}")
            
    def _send_config(self):
        """Send synthesizer configuration"""
        try:
            config = self.synth_manager.get_current_config()
            if config:
                self.uart.write(f"{config}\n")
                print("Config sent successfully")
        except Exception as e:
            print(f"Failed to send config: {str(e)}")
            self.state = self.DETECTED  # Return to detected state on error
            
    def cleanup(self):
        """Clean up resources"""
        if self.detect_pin:
            self.detect_pin.deinit()

    def is_connected(self):
        """Check if fully connected"""
        return self.state == self.CONNECTED

class Candide:
    def __init__(self):
        print("\nWakeup Candide!")
        self.audio_manager = AudioManager()
        self.hardware_manager = HardwareManager()
        self.synth_manager = SynthManager(self.audio_manager)
        
        # Initialize shared transport
        self.transport = TransportManager(
            tx_pin=Constants.UART_TX,
            rx_pin=Constants.UART_RX,
            baudrate=Constants.UART_BAUDRATE,
            timeout=Constants.UART_TIMEOUT
        )
        
        # Initialize UART and MIDI with shared transport
        shared_uart = self.transport.get_uart()
        self.text_uart = TextUart(shared_uart)
        self.midi = MidiLogic(
            uart=shared_uart,
            text_callback=self._handle_midi_message
        )
        
        # Initialize connection manager with text UART and transport
        self.connection_manager = CandideConnectionManager(
            self.text_uart,
            self.synth_manager,
            self.transport
        )
        
        # Timing state
        self.last_encoder_scan = 0
        self.last_volume_scan = 0

        try:
            initial_volume = self.hardware_manager.get_initial_volume()
            if Constants.DEBUG:
                print(f"Initial volume: {initial_volume:.3f}")
            self.audio_manager.set_volume(initial_volume)
            print("\nCandide (v1.0) is awake!... ( ◔◡◔)♬")
        except Exception as e:
            print(f"Initialization error: {str(e)}")
            raise

    def _handle_midi_message(self, event):
        """Handle MIDI messages"""
        if not event:
            return
            
        # Pass to connection manager first for handshake
        self.connection_manager.handle_midi_message(event)
            
        # Process MIDI messages after config is sent (in HANDSHAKING or CONNECTED state)
        if self.connection_manager.state in [CandideConnectionManager.HANDSHAKING, CandideConnectionManager.CONNECTED]:
            # Exclude note on/off messages during handshaking
            if event['type'] != 'note':
                self.synth_manager.process_midi_events([event])

    def _check_volume(self):
        """Check and update volume"""
        current_time = time.monotonic()
        if (current_time - self.last_volume_scan) >= HWConstants.UPDATE_INTERVAL:
            new_volume = self.hardware_manager.read_pot()
            if new_volume is not None:
                self.audio_manager.set_volume(new_volume)
            self.last_volume_scan = current_time

    def _check_encoder(self):
        """Check encoder and handle changes"""
        current_time = time.monotonic()
        if (current_time - self.last_encoder_scan) >= HWConstants.ENCODER_SCAN_INTERVAL:
            events = self.hardware_manager.read_encoder()
            
            if Constants.DEBUG and events:
                print(f"Encoder events: {events}")
            
            # Only process encoder events if we're not in the middle of handshaking
            if self.connection_manager.state in [CandideConnectionManager.STANDALONE, CandideConnectionManager.CONNECTED]:
                for event_type, direction in events:
                    if event_type == 'instrument_change':
                        new_instrument = Instrument.handle_instrument_change(direction)
                        if new_instrument != self.synth_manager.current_instrument:
                            print(f"Switching to instrument: {new_instrument.name}")
                            self.synth_manager.set_instrument(new_instrument)
                            # Only send config if we're fully connected
                            if self.connection_manager.state == CandideConnectionManager.CONNECTED:
                                self.connection_manager._send_config()
            
            self.last_encoder_scan = current_time

    def update(self):
        """Main update loop with improved error handling"""
        try:
            # midi - no need to capture return value anymore
            self.midi.check_for_messages()
            
            # Update connection state
            self.connection_manager.update_state()
            
            # Check hardware
            self._check_encoder()
            self._check_volume()
            
            # Update synth
            self.synth_manager.update()
            
            return True
            
        except Exception as e:
            print(f"Error in main loop: {str(e)}")
            return False

    def run(self):
        """Main run loop"""
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
        if self.synth_manager.synth:
            print("Stopping synthesizer...")
            self.synth_manager.synth.stop()
        if self.midi:
            print("Cleaning up MIDI...")
            self.midi.cleanup()
        if hasattr(self, 'transport'):
            print("Cleaning up transport...")
            self.transport.cleanup()
        if self.connection_manager:
            print("Cleaning up connection manager...")
            self.connection_manager.cleanup()
        if self.hardware_manager.encoder:
            print("Cleaning up encoder...")
            self.hardware_manager.encoder.cleanup()
        if self.hardware_manager.volume_pot:
            self.hardware_manager.volume_pot.pot.deinit()
        print("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁")

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        print(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    main()
