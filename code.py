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
    DEBUG = True
    
    # Hardware Setup
    SETUP_DELAY = 0.1
    
    # UART/MIDI Pins
    UART_TX = board.GP16
    UART_RX = board.GP17
    
    # Connection
    DETECT_PIN = board.GP22
    CONNECTION_TIMEOUT = 2.0
    MESSAGE_TIMEOUT = 0.05
    CONFIG_SEND_DELAY = 0.05
    
    # New Connection Constants
    STARTUP_DELAY = 1.0  # Give devices time to initialize
    RETRY_DELAY = 0.25   # Delay between connection attempts
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
        
        Piano()
        Organ()
        Womp()
        WindChime()
        
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
    Handles the connection and handshake protocol for Candide (Client).
    Uses text UART for sending config, MIDI for all other communication.
    """
    STANDALONE = 0
    PIN_DETECTED = 1
    CONNECTING = 2
    CONFIGURING = 3
    CONNECTED = 4

    def __init__(self, text_uart, synth_manager, transport_manager):
        self.uart = text_uart
        self.synth_manager = synth_manager
        self.transport = transport_manager
        
        # Setup detect pin as input with pulldown
        self.detect_pin = digitalio.DigitalInOut(Constants.DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        # Initialize state
        self.state = self.STANDALONE
        self.last_message_time = 0
        self.connection_attempts = 0
        self.last_connection_attempt = 0
        
        print(f"Candide connection manager initialized")
        
    def update_state(self):
        """Main update loop with improved error handling"""
        current_time = time.monotonic()
        
        # Check physical connection
        current_state = self.detect_pin.value
        
        # Handle connection state changes
        if current_state and self.state == self.STANDALONE:
            self._handle_pin_detected()
        elif not current_state and self.state != self.STANDALONE:
            self._handle_disconnection()
            
        # Check for timeout in intermediate states
        if self.state not in [self.STANDALONE, self.CONNECTED]:
            if current_time - self.last_message_time > Constants.CONNECTION_TIMEOUT:
                print("Connection timeout - no response")
                self._handle_error()
            
    def handle_midi_message(self, event):
        """Process incoming MIDI events for handshake"""
        if Constants.DEBUG:
            print(f"DEBUG MIDI: Received event: {event}")
            
        if not event or event['type'] != 'cc':
            return
            
        # Check for handshake CC
        if (event['channel'] == 0 and 
            event['data']['number'] == Constants.HANDSHAKE_CC):
            
            if (event['data']['value'] == Constants.HANDSHAKE_VALUE and 
                self.state == self.CONNECTING):
                print("---------------")
                print("HANDSHAKE STEP 3: Handshake CC received")
                print("HANDSHAKE STEP 4: Sending config...")
                print("---------------")
                self.state = self.CONFIGURING
                self._send_config()
                
            elif (event['data']['value'] == Constants.WELCOME_VALUE and 
                  self.state == self.CONFIGURING):
                print("---------------")
                print("HANDSHAKE COMPLETE: Connection established")
                print("---------------")
                self.state = self.CONNECTED
                self.connection_attempts = 0
                
    def _handle_pin_detected(self):
        """Handle new physical connection with proper initialization"""
        print("---------------")
        print("HANDSHAKE STEP 1: Host detected")
        print("HANDSHAKE STEP 2: Sending hello...")
        print("---------------")
        
        # Give both devices time to initialize
        time.sleep(Constants.STARTUP_DELAY)
        
        self.state = self.PIN_DETECTED
        self.transport.flush_buffers()
        
        time.sleep(Constants.CONFIG_SEND_DELAY)
        self._attempt_connection()
        
    def _attempt_connection(self):
        """Attempt connection with retry logic"""
        current_time = time.monotonic()
        
        # Check if we should retry
        if self.connection_attempts >= Constants.MAX_RETRIES:
            print("Max connection attempts reached")
            self._handle_error()
            return
            
        # Ensure minimum delay between attempts
        if current_time - self.last_connection_attempt < Constants.RETRY_DELAY:
            return
            
        try:
            print(f"Connection attempt {self.connection_attempts + 1}/{Constants.MAX_RETRIES}")
            self.uart.write("hello\n")
            self.state = self.CONNECTING
            self.last_message_time = current_time
            self.last_connection_attempt = current_time
            self.connection_attempts += 1
        except Exception as e:
            print(f"Connection attempt failed: {str(e)}")
            self._handle_error()
            
    def _handle_error(self):
        """Handle errors with proper cleanup and delay"""
        print("Error occurred - cleaning up connection")
        self.transport.flush_buffers()
        time.sleep(Constants.ERROR_RECOVERY_DELAY)
                   
    def _handle_error(self):
        """Handle errors with proper cleanup and delay"""
        print("Error occurred - cleaning up connection")
        self.transport.flush_buffers()
        time.sleep(Constants.ERROR_RECOVERY_DELAY)
        self._reset_state()
            
    def _handle_disconnection(self):
        """Handle physical disconnection with cleanup"""
        print("Host disconnected")
        self.transport.flush_buffers()
        self._reset_state()
        
    def _reset_state(self):
        """Reset to initial state with cleanup"""
        self.state = self.STANDALONE
        self.last_message_time = 0
        self.connection_attempts = 0
        self.last_connection_attempt = 0
            
    def _send_config(self):
        """Send synthesizer configuration"""
        try:
            config = self.synth_manager.get_current_config()
            if config:
                self.uart.write(f"{config}\n")
                print("Config sent successfully")
                self.last_message_time = time.monotonic()
        except Exception as e:
            print(f"Failed to send config: {str(e)}")
            self._handle_error()
                    
    def cleanup(self):
        """Cleanup resources"""
        if self.detect_pin:
            self.detect_pin.deinit()

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
            
        # Process as MIDI if connected
        if self.connection_manager.state == CandideConnectionManager.CONNECTED:
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
