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
    HEARTBEAT_INTERVAL = 0.25
    MESSAGE_TIMEOUT = 0.05
    CONFIG_SEND_DELAY = 0.05
    INITIAL_PAUSE = 0.5  # Added pause before sending config
    MESSAGE_COUNTS_AS_HEARTBEAT = True

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

class MidiManager:
    def __init__(self, handle_text_message):
        self.midi = None
        self._setup_midi(handle_text_message)

    def _setup_midi(self, handle_text_message):
        """Initialize MIDI interface"""
        print("Setting up MIDI...")
        self.midi = MidiLogic(
            Constants.UART_TX,
            Constants.UART_RX,
            handle_text_message
        )

    def check_for_messages(self):
        return self.midi.check_for_messages()

    def write(self, message):
        """Write text message over UART"""
        if Constants.DEBUG:
            print("Sending message")
        return self.midi.uart.write(message.encode('utf-8'))

    def clear_buffers(self):
        """Clear UART buffers"""
        self.midi.uart.message_buffer = []

class ConnectionManager:
    def __init__(self, midi_manager, synth_manager):
        self.detect_pin = None
        self.connected = False
        self.has_sent_hello = False
        self.last_message_time = 0
        self.last_config_time = 0
        self.midi_manager = midi_manager
        self.synth_manager = synth_manager
        self._setup_initial_state()

    def _setup_initial_state(self):
        """Set initial state"""
        print("Setting up initial state...")
        
        self.detect_pin = digitalio.DigitalInOut(Constants.DETECT_PIN)
        self.detect_pin.direction = digitalio.Direction.INPUT
        self.detect_pin.pull = digitalio.Pull.DOWN
        
        self.connected = False
        self.has_sent_hello = False
        
        if self.detect_pin.value:
            self._handle_new_connection()

    def _handle_new_connection(self):
        """Handle new physical connection"""
        print("Connected to Bartleby")
        self.midi_manager.clear_buffers()
        self.connected = True
        self.has_sent_hello = False
        self._send_hello()

    def _send_hello(self):
        """Send hello message"""
        if not self.has_sent_hello:
            if self.midi_manager.write("hello\n"):
                print("Sent hello...")
                self.has_sent_hello = True
                time.sleep(Constants.INITIAL_PAUSE)  # Pause before sending config
                self._send_instrument_config()

    def _send_heartbeat(self):
        """Send heartbeat message if needed"""
        current_time = time.monotonic()
        if (current_time - self.last_message_time) >= Constants.HEARTBEAT_INTERVAL:
            self.midi_manager.write("heartbeat\n")
            self.last_message_time = current_time

    def _send_instrument_config(self):
        """Send current instrument's CC configuration"""
        if self.connected:
            config_string = self.synth_manager.current_instrument.generate_cc_config()
            if config_string:
                if self.midi_manager.write(f"{config_string}\n"):
                    if Constants.DEBUG:
                        print("Sent instrument config")
                    self.last_config_time = time.monotonic()
                    self.last_message_time = self.last_config_time
                    return True
        return False

    def update_connection_state(self):
        """Update connection state"""
        current_state = self.detect_pin.value
        
        if current_state and not self.connected:
            # New connection detected
            self._handle_new_connection()
        elif not current_state and self.connected:
            # Disconnection detected
            print("Detached from Bartleby")
            self.connected = False
            self.has_sent_hello = False
            self.last_message_time = 0

class Candide:
    def __init__(self):
        print("\nWakeup Candide!")
        self.audio_manager = AudioManager()
        self.hardware_manager = HardwareManager()
        self.synth_manager = SynthManager(self.audio_manager)
        self.midi_manager = MidiManager(self._handle_text_message)
        self.connection_manager = ConnectionManager(self.midi_manager, self.synth_manager)
        
        # Timing state
        self.last_encoder_scan = 0
        self.last_volume_scan = 0

        try:
            initial_volume = self.hardware_manager.get_initial_volume()
            if Constants.DEBUG:
                print(f"Initial volume: {initial_volume:.3f}")
            self.audio_manager.set_volume(initial_volume)
            print("\nCandide (v1.0) is ready... (◕‿◕✿)")
        except Exception as e:
            print(f"Initialization error: {str(e)}")
            raise

    def _handle_text_message(self, message_dict):
        """Handle text messages from Bartleby"""
        if not isinstance(message_dict, dict):
            return
            
        message = message_dict.get('message', '')
        if not message:
            return
            
        if Constants.DEBUG and message != "heartbeat":
            print("Message received")
            
        if message.startswith("cc:"):
            self._handle_cc_config(message)
            
        self.connection_manager.last_message_time = time.monotonic()

    def _handle_cc_config(self, config):
        """Handle CC configuration message"""
        if Constants.DEBUG:
            print("CC config received")
        # Process config as needed
        pass

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
                        if self.connection_manager.connected:
                            self.connection_manager._send_instrument_config()
            
            self.last_encoder_scan = current_time

    def update(self):
        """Main update loop"""
        try:
            self.connection_manager.update_connection_state()
            
            self._check_encoder()
            self._check_volume()
            
            if self.connection_manager.connected:
                # Check for messages using check_for_messages
                messages = self.midi_manager.check_for_messages()
                if messages:
                    # Route MIDI messages to synthesizer
                    self.synth_manager.process_midi_events(messages)
                    for message in messages:
                        self._handle_text_message(message)
                self.connection_manager._send_heartbeat()
            
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
        if self.midi_manager.midi:
            print("Cleaning up MIDI...")
            self.midi_manager.midi.cleanup()
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
