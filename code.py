import board
import digitalio
import time
from synthesizer import Synthesizer, SynthAudioOutputManager
from hardware import RotaryEncoderHandler, VolumePotHandler, Constants as HWConstants
from instruments import Piano, Organ, Womp, WindChime, Instrument
from midi import MidiLogic

class Constants:
    DEBUG = False
    SEE_HEARTBEAT = False

    # Hardware Setup Delay
    SETUP_DELAY = 0.1
    
    # UART/MIDI Pins
    UART_TX = board.GP16
    UART_RX = board.GP17
    
    # Detect Pin
    DETECT_PIN = board.GP22
    
    # Communication Timing
    HEARTBEAT_INTERVAL = 0.5
    MESSAGE_TIMEOUT = 0.05
    CONFIG_SEND_DELAY = 0.05
    MESSAGE_COUNTS_AS_HEARTBEAT = True

class Candide:
    def __init__(self):
        print("\nWakeup Candide!")
        self.audio = None
        self.synth = None
        self.current_instrument = None
        self.midi = None
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
        
    def _setup_hardware(self):
        """Initialize hardware components"""
        print("Setting up hardware...")
        self.encoder = RotaryEncoderHandler(
            HWConstants.INSTRUMENT_ENC_CLK,
            HWConstants.INSTRUMENT_ENC_DT
        )
        self.volume_pot = VolumePotHandler(HWConstants.VOLUME_POT)
        
        initial_volume = self.volume_pot.normalize_value(self.volume_pot.pot.value)
        if Constants.DEBUG:
            print(f"Initial volume: {initial_volume:.3f}")
        self.audio.set_volume(initial_volume)
        
    def _setup_synth(self):
        """Initialize synthesis subsystem"""
        print("Setting up synthesizer...")
        self.synth = Synthesizer(self.audio)
        
        Piano()
        Organ()
        Womp()
        WindChime()
        
        if Constants.DEBUG:
            print(f"Available instruments: {[i.name for i in Instrument.available_instruments]}")
        
        self.current_instrument = Instrument.get_current_instrument()
        self.synth.set_instrument(self.current_instrument)

    def _handle_text_message(self, message):
        """Handle text messages from Bartleby"""
        if Constants.DEBUG and message.strip() != "♡":
            print(f"Received message: {message}")
            
        if message.startswith("cc:"):
            self._handle_cc_config(message)
            
        self.last_message_time = time.monotonic()

    def _handle_cc_config(self, config):
        """Handle CC configuration message"""
        if Constants.DEBUG:
            print(f"Received config: {config}")
        # Process config as needed
        pass

    def _setup_midi(self):
        """Initialize MIDI interface"""
        print("Setting up MIDI...")
        self.midi = MidiLogic(
            Constants.UART_TX,
            Constants.UART_RX,
            self._handle_text_message
        )

    def _setup_initial_state(self):
        """Set initial state"""
        print("Setting up initial state...")
        
        self.detect_pin = digitalio.DigitalInOut(Constants.DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        self.connected = self.detect_pin.value
        if self.connected:
            print("Connected to Bartleby")
            self._send_connected_messages()
        else:
            print("Not connected to Bartleby")

    def _send_connected_messages(self):
        """Send initial messages when connected"""
        if not self.has_sent_hello:
            if self.midi.uart.write(bytes("hello from candide\n", 'utf-8')):
                time.sleep(Constants.CONFIG_SEND_DELAY)
                
                config_string = self.current_instrument.generate_cc_config()
                if config_string:
                    if self.midi.uart.write(bytes(f"{config_string}\n", 'utf-8')):
                        print(f"Sent initial config: {config_string}")
                        self.last_config_time = time.monotonic()
                        self.last_message_time = self.last_config_time
                        self.has_sent_hello = True

    def _send_heartbeat(self):
        """Send heartbeat message if needed"""
        current_time = time.monotonic()
        if (current_time - self.last_message_time) >= Constants.HEARTBEAT_INTERVAL:
            self.midi.uart.write(bytes("♡\n", 'utf-8'))
            self.last_message_time = current_time

    def _send_instrument_config(self):
        """Send current instrument's CC configuration"""
        if self.connected:
            config_string = self.current_instrument.generate_cc_config()
            if config_string:
                if self.midi.uart.write(bytes(f"{config_string}\n", 'utf-8')):
                    if Constants.DEBUG:
                        print(f"Sent instrument config: {config_string}")
                    self.last_config_time = time.monotonic()
                    self.last_message_time = self.last_config_time
                    return True
        return False

    def _check_volume(self):
        """Check and update volume"""
        current_time = time.monotonic()
        if (current_time - self.last_volume_scan) >= HWConstants.UPDATE_INTERVAL:
            new_volume = self.volume_pot.read_pot()
            if new_volume is not None:
                self.audio.set_volume(new_volume)
            self.last_volume_scan = current_time

    def _check_encoder(self):
        """Check encoder and handle changes"""
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
                # Clear any stale data
                while self.midi.uart.in_waiting:
                    self.midi.uart.read()
                self.connected = True
                self.has_sent_hello = False
                self._send_connected_messages()
            
            # Handle disconnection
            elif self.connected and not current_state:
                print("Detached from Bartleby")
                self.connected = False
                self.last_message_time = 0
                self.has_sent_hello = False
            
            # Check hardware
            self._check_encoder()
            self._check_volume()
            
            # Process MIDI and text messages
            if self.connected:
                events = self.midi.check_for_messages()
                if events:  # Got MPE events
                    self.synth.process_mpe_events(events)
                # Note: text messages are handled via callback
                
                # Send heartbeat if needed
                self._send_heartbeat()
            
            # Update synthesis
            self.synth.update()
            
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
        if self.synth:
            print("Stopping synthesizer...")
            self.synth.stop()
        if self.midi:
            print("Cleaning up MIDI...")
            self.midi.cleanup()
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