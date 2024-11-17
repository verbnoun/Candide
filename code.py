import board
import busio
import digitalio
import time
import supervisor
from synthesizer_coordinator import MPESynthesizer
from hardware import RotaryEncoderHandler, VolumePotHandler, Constants as HWConstants
from instrument_config import create_instrument, list_instruments
from midi import MidiLogic
from output_system import AudioOutputManager

class Constants:
    DEBUG = True
    
    # Hardware Setup
    SETUP_DELAY = 0.1  # in seconds
    
    # UART/MIDI Pins
    UART_TX = board.GP16
    UART_RX = board.GP17
    
    # Connection
    DETECT_PIN = board.GP22
    MESSAGE_TIMEOUT = 0.05  # in seconds
    HELLO_INTERVAL = 0.5  # in seconds
    HEARTBEAT_INTERVAL = 1.0  # in seconds
    HANDSHAKE_TIMEOUT = 5.0  # in seconds
    HANDSHAKE_MAX_RETRIES = 10
    
    # New Connection Constants
    STARTUP_DELAY = 1.0  # in seconds
    RETRY_DELAY = 5.0  # in seconds
    RETRY_INTERVAL = 0.25  # in seconds
    ERROR_RECOVERY_DELAY = 0.5  # in seconds
    BUFFER_CLEAR_TIMEOUT = 0.1  # in seconds
    MAX_RETRIES = 3
    
    # UART Settings
    UART_BAUDRATE = 31250
    UART_TIMEOUT = 0.001  # in seconds
    
    # MIDI CC for Handshake
    HANDSHAKE_CC = 119
    HANDSHAKE_VALUE = 42
    WELCOME_VALUE = 43

class TransportManager:
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
        return self.uart
        
    def flush_buffers(self):
        start_time = time.monotonic()
        while time.monotonic() - start_time < Constants.BUFFER_CLEAR_TIMEOUT:
            if self.uart.in_waiting:
                self.uart.read()
            else:
                break
        
    def cleanup(self):
        if self.uart:
            self.flush_buffers()
            self.uart.deinit()

class TextUart:
    def __init__(self, uart):
        self.uart = uart
        self.last_write = 0
        print("Text protocol initialized")

    def write(self, message):
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
        print("Setting up audio...")
        self.audio = AudioOutputManager()

    def set_volume(self, volume):
        self.audio.set_volume(volume)

class HardwareManager:
    def __init__(self):
        print("Setting up hardware...")
        self.encoder = None
        self.volume_pot = None
        self._setup_hardware()

    def _setup_hardware(self):
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
        print("Setting up synthesizer...")
        self.synth = MPESynthesizer(output_manager=self.audio_manager.audio)
        
        self.current_instrument = create_instrument('piano')
        if self.current_instrument:
            self.synth.set_instrument(self.current_instrument.get_config())

    def set_instrument(self, instrument_name):
        new_instrument = create_instrument(instrument_name)
        if new_instrument:
            self.current_instrument = new_instrument
            self.synth.set_instrument(new_instrument.get_config())

    def update(self):
        self.synth.update()

    def process_midi_events(self, events):
        if events:
            if Constants.DEBUG:
                print("MIDI messages received")
            self.synth.process_mpe_events(events)
            
    def get_current_config(self):
        if self.current_instrument:
            return self.current_instrument.get_config()
        return None

class CandideConnectionManager:
    STANDALONE = 0
    DETECTED = 1
    HANDSHAKING = 2
    CONNECTED = 3
    RETRY_DELAY = 4
    
    def __init__(self, text_uart, synth_manager, transport_manager):
        self.uart = text_uart
        self.synth_manager = synth_manager
        self.transport = transport_manager
        
        self.detect_pin = digitalio.DigitalInOut(Constants.DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        self.state = self.STANDALONE
        self.last_hello_time = 0
        self.last_heartbeat_time = 0
        self.handshake_start_time = 0
        self.hello_count = 0
        self.retry_start_time = 0
        
        print("Candide connection manager initialized")
        
    def update_state(self):
        current_time = time.monotonic()
        
        if not self.detect_pin.value:
            if self.state != self.STANDALONE:
                self._handle_disconnection()
            return
            
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
                    self.hello_count = 0
                    
        elif self.state == self.RETRY_DELAY:
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
        if not event or event['type'] != 'cc':
            return
            
        if (event['channel'] == 0 and 
            event['data']['number'] == Constants.HANDSHAKE_CC):
            
            if (event['data']['value'] == Constants.HANDSHAKE_VALUE and 
                self.state == self.DETECTED):
                print("Handshake CC received - sending config")
                self.state = self.HANDSHAKING
                self.handshake_start_time = time.monotonic()
                self._send_config()
                self.state = self.CONNECTED
                print("Connection established")
                
    def _handle_initial_detection(self):
        print("Base station detected - initializing connection")
        self.transport.flush_buffers()
        time.sleep(Constants.SETUP_DELAY)
        self.state = self.DETECTED
        self.hello_count = 0
        self._send_hello()
        
    def _handle_disconnection(self):
        print("Base station disconnected")
        self.transport.flush_buffers()
        self.state = self.STANDALONE
        self.hello_count = 0
        
    def _send_hello(self):
        try:
            self.uart.write("hello\n")
            self.last_hello_time = time.monotonic()
        except Exception as e:
            print(f"Failed to send hello: {str(e)}")
            
    def _send_heartbeat(self):
        try:
            self.uart.write("♥︎\n")
            self.last_heartbeat_time = time.monotonic()
        except Exception as e:
            print(f"Failed to send heartbeat: {str(e)}")
            
    def _send_config(self):
        try:
            config = self.synth_manager.get_current_config()
            if config:
                self.uart.write(f"{config}\n")
                print("Config sent successfully")
        except Exception as e:
            print(f"Failed to send config: {str(e)}")
            self.state = self.DETECTED
            
    def cleanup(self):
        if self.detect_pin:
            self.detect_pin.deinit()

    def is_connected(self):
        return self.state == self.CONNECTED

class Candide:
    def __init__(self):
        print("\nWakeup Candide!")
        self.audio_manager = AudioManager()
        self.hardware_manager = HardwareManager()
        self.synth_manager = SynthManager(self.audio_manager)
        
        self.transport = TransportManager(
            tx_pin=Constants.UART_TX,
            rx_pin=Constants.UART_RX,
            baudrate=Constants.UART_BAUDRATE,
            timeout=Constants.UART_TIMEOUT
        )
        
        shared_uart = self.transport.get_uart()
        self.text_uart = TextUart(shared_uart)
        self.midi = MidiLogic(
            uart=shared_uart,
            text_callback=self._handle_midi_message
        )
        
        self.connection_manager = CandideConnectionManager(
            self.text_uart,
            self.synth_manager,
            self.transport
        )
        
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
        if not event:
            return
            
        self.connection_manager.handle_midi_message(event)
            
        if self.connection_manager.state in [CandideConnectionManager.HANDSHAKING, CandideConnectionManager.CONNECTED]:
            if event['type'] != 'note':
                self.synth_manager.process_midi_events([event])

    def _check_volume(self):
        current_time = time.monotonic()
        if current_time - self.last_volume_scan >= HWConstants.UPDATE_INTERVAL:
            new_volume = self.hardware_manager.read_pot()
            if new_volume is not None:
                self.audio_manager.set_volume(new_volume)
            self.last_volume_scan = current_time

    def _check_encoder(self):
        current_time = time.monotonic()
        if current_time - self.last_encoder_scan >= HWConstants.ENCODER_SCAN_INTERVAL:
            events = self.hardware_manager.read_encoder()
            
            if Constants.DEBUG and events:
                print(f"Encoder events: {events}")
            
            if self.connection_manager.state in [CandideConnectionManager.STANDALONE, CandideConnectionManager.CONNECTED]:
                for event_type, direction in events:
                    if event_type == 'instrument_change':
                        instruments = list_instruments()
                        current_idx = instruments.index(self.synth_manager.current_instrument.name)
                        new_idx = (current_idx + direction) % len(instruments)
                        new_instrument = instruments[new_idx].lower().replace(' ', '_')
                        print(f"Switching to instrument: {new_instrument}")
                        self.synth_manager.set_instrument(new_instrument)
                        if self.connection_manager.state == CandideConnectionManager.CONNECTED:
                            self.connection_manager._send_config()
            
            self.last_encoder_scan = current_time

    def update(self):
        try:
            self.midi.check_for_messages()
            self.connection_manager.update_state()
            self._check_encoder()
            self._check_volume()
            self.synth_manager.update()
            return True
            
        except Exception as e:
            print(f"Update error: {str(e)}")
            return False

    def run(self):
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
        if self.synth_manager.synth:
            print("Stopping synthesizer...")
            self.synth_manager.synth.cleanup()
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
