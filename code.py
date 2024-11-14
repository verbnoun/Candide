import board
import busio
import usb_midi
import digitalio
import time
from synthesizer import Synthesizer, SynthAudioOutputManager
from hardware import RotaryEncoderHandler, VolumePotHandler, Constants as HWConstants
from instruments import Piano, Organ, Womp, WindChime, Instrument
from midi import MidiLogic

class Constants:
    # Debug Settings
    DEBUG = True
    SEE_HEARTBEAT = True
    
    # Hardware Setup
    SETUP_DELAY = 0.1
    
    # UART/MIDI Pins
    UART_TX = board.GP16
    UART_RX = board.GP17
    
    # Connection
    DETECT_PIN = board.GP22
    CONNECTION_TIMEOUT = 1.0  # Updated
    HEARTBEAT_INTERVAL = 0.25
    MESSAGE_TIMEOUT = 0.05
    CONFIG_SEND_DELAY = 0.05
    INITIAL_PAUSE = 0.5
    HELLO_TIMEOUT = 0.5
    CONFIG_TIMEOUT = 1.0
    CONFIG_RETRY_INTERVAL = 0.1
    MAX_RETRIES = 3
    
    # UART Settings
    UART_BAUDRATE = 31250
    UART_TIMEOUT = 0.001

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
        
    def cleanup(self):
        """Clean shutdown of transport"""
        if self.uart:
            self.uart.deinit()

class TextUart:
    """Handles text-based UART communication, separate from MIDI"""
    def __init__(self, uart):
        self.uart = uart
        print("Text protocol initialized")

    def write(self, message):
        """Write text message, converting to bytes if needed"""
        if isinstance(message, str):
            message = message.encode('utf-8')
        return self.uart.write(message)

    def read(self, size=None):
        """Read available data"""
        if size is None and self.uart.in_waiting:
            size = self.uart.in_waiting
        if size:
            return self.uart.read(size)
        return None

    @property
    def in_waiting(self):
        """Number of bytes waiting to be read"""
        return self.uart.in_waiting

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
        self.encoder = None
        self.volume_pot = None
        self._setup_hardware()

    def _setup_hardware(self):
        """Initialize hardware components"""
        print("Setting up hardware...")
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
    Uses text UART for communication, separate from MIDI.
    
    State Machine:
    1. STANDALONE -> No physical connection detected (detect_pin low)
    2. CONNECTING -> Physical connection detected (detect_pin high), sending hello
    3. CONFIGURING -> Config request received, sending config
    4. CONNECTED -> Connection confirmed, sending heartbeats
    """
    STANDALONE = 0
    CONNECTING = 1
    CONFIGURING = 2
    CONNECTED = 3

    def __init__(self, text_uart, synth_manager):
        # Setup communication
        self.uart = text_uart
        self.synth_manager = synth_manager
        
        # Setup detect pin as input with pulldown
        self.detect_pin = digitalio.DigitalInOut(Constants.DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        # Initialize state
        self.state = self.STANDALONE
        self.last_heartbeat = 0
        self.last_message_time = 0
        
        print(f"Candide connection manager initialized")
        
    def update_state(self):
        """Main update loop - detect connection and maintain heartbeat"""
        # Check physical connection via detect pin
        current_state = self.detect_pin.value
        
        # Handle connection state changes
        if current_state and self.state == self.STANDALONE:
            self._handle_new_connection()
        elif not current_state and self.state != self.STANDALONE:
            self._handle_disconnection()
            
        # Send heartbeat if connected
        if self.state == self.CONNECTED:
            self._send_heartbeat()
            
        # Check for timeout if we're not standalone
        if self.state != self.STANDALONE:
            if time.monotonic() - self.last_message_time > Constants.CONNECTION_TIMEOUT:
                print("Connection timeout - no response from Bartleby")
                self._handle_timeout()
            
    def handle_message(self, message):
        """Process incoming messages based on current state"""
        if not message:
            return
            
        self.last_message_time = time.monotonic()
        
        if self.state == self.CONNECTING and message == "request_config":
            print("---------------")
            print("HANDSHAKE STEP 3: Config requested by Bartleby")
            print("HANDSHAKE STEP 4: Sending instrument config...")
            print("---------------")
            self.state = self.CONFIGURING
            self._send_config()
            
        elif self.state == self.CONFIGURING and message == "welcome":
            print("---------------")
            print("HANDSHAKE COMPLETE: Connection established with Bartleby")
            print("---------------")
            self.state = self.CONNECTED
            self.last_heartbeat = time.monotonic()
            
    def _handle_new_connection(self):
        """Handle new physical connection detection"""
        print("---------------")
        print("HANDSHAKE STEP 1: Bartleby detected")
        print("HANDSHAKE STEP 2: Sending hello...")
        print("---------------")
        self.state = self.CONNECTING
        # Clear any old messages in buffer
        while self.uart.in_waiting:
            self.uart.read()
        
        # Add delay to ensure buffers are clear
        time.sleep(Constants.CONFIG_SEND_DELAY)
        self._send_hello()
        
    def _handle_disconnection(self):
        """Handle physical disconnection"""
        print("Detached from Bartleby")
        self._reset_state()
        
    def _handle_timeout(self):
        """Handle communication timeout"""
        if self.state != self.STANDALONE:
            print("Communication timeout with Bartleby")
            self._reset_state()
            
    def _reset_state(self):
        """Reset to initial state"""
        self.state = self.STANDALONE
        self.last_message_time = 0
        self.last_heartbeat = 0
            
    def _send_hello(self):
        """Send initial hello message with retries"""
        retries = 0
        while retries < Constants.MAX_RETRIES:
            try:
                if Constants.DEBUG:
                    print(f"DEBUG: Sending hello (attempt {retries + 1})")
                self.uart.write("hello\n")
                print("DEBUG: Hello message sent")
                self.last_message_time = time.monotonic()
                time.sleep(Constants.CONFIG_RETRY_INTERVAL)  # Wait between attempts
                return True
            except Exception as e:
                print(f"Failed to send hello (attempt {retries + 1}): {str(e)}")
                retries += 1
                if retries >= Constants.MAX_RETRIES:
                    self._handle_timeout()
                    return False
            
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
            self._handle_timeout()
            
    def _send_heartbeat(self):
        """Send periodic heartbeat when connected"""
        current_time = time.monotonic()
        if current_time - self.last_heartbeat >= Constants.HEARTBEAT_INTERVAL:
            try:
                self.uart.write("heartbeat\n")
                self.last_heartbeat = current_time
            except Exception as e:
                if Constants.DEBUG:
                    print(f"Failed to send heartbeat: {str(e)}")
                    self._handle_timeout()
                    
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
        
        # Initialize connection manager with text UART
        self.connection_manager = CandideConnectionManager(
            self.text_uart, 
            self.synth_manager
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

    def _handle_midi_message(self, message_dict):
        """Handle MIDI-specific messages"""
        if not isinstance(message_dict, dict):
            return
            
        message = message_dict.get('message', '')
        if not message:
            return
            
        if Constants.DEBUG and message != "heartbeat":
            print("MIDI message received")

    def _handle_text_message(self, message):
        """Handle text protocol messages"""
        if not message:
            return
            
        if Constants.DEBUG and message != "heartbeat":
            print(f"Text message received: {message}")
            
        self.connection_manager.handle_message(message)

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
            
            for event_type, direction in events:
                if event_type == 'instrument_change':
                    new_instrument = Instrument.handle_instrument_change(direction)
                    if new_instrument != self.synth_manager.current_instrument:
                        print(f"Switching to instrument: {new_instrument.name}")
                        self.synth_manager.set_instrument(new_instrument)
                        if self.connection_manager.state == CandideConnectionManager.CONNECTED:
                            self.connection_manager._send_config()
            
            self.last_encoder_scan = current_time

    def update(self):
        """Main update loop"""
        try:
            # Update connection state
            self.connection_manager.update_state()
            
            # Check hardware
            self._check_encoder()
            self._check_volume()
            
            # Check for text messages
            if self.text_uart.in_waiting:
                new_bytes = self.text_uart.read()
                if new_bytes:
                    try:
                        message = new_bytes.decode('utf-8').strip()
                        if message:
                            self._handle_text_message(message)
                    except Exception as e:
                        if str(e):
                            print(f"Error decoding message: {str(e)}")
            
            # Process MIDI if connected
            if self.connection_manager.state == CandideConnectionManager.CONNECTED:
                messages = self.midi.check_for_messages()
                if messages:
                    self.synth_manager.process_midi_events(messages)
            
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
        if self.connection_manager.detect_pin:
            self.connection_manager.detect_pin.deinit()
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

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        print(f"Fatal error: {str(e)}")

if __name__ == "__main__":
    main()