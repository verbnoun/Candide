"""
Main Execution Module for Candide Synthesizer

This module serves as the comprehensive orchestration center 
for the Candide Synthesizer, managing complex interactions 
between hardware, MIDI, audio, and system components.

Key Responsibilities:
- Coordinate hardware input processing
- Initialize system components
- Control synthesizer state and instrument selection
- Provide robust error handling and recovery mechanisms
- Define transport layer protocols and implementations
"""

import board
import time
import sys
import audiobusio
import audiomixer
import busio
from hardware import HardwareManager
from config import CASIO_PATHS, ORGAN_PATHS, MPE_PATHS, SIGNAL_CHAIN_ORDER
from midi import MidiLogic
from voices import VoiceManager
from router import Router
from connection_manager import CandideConnectionManager
from constants import *

import random

def _log(message, effect=None):
    """
    Conditional logging function with optional color animation.
    Args:
        message (str): Message to log
        effect (str): Animation effect - 'cycle' (default: None)
    """
    if not DEBUG:
        return

    # Basic ANSI colors that work well on most terminals
    COLORS = [
        "\033[96m",  # Light Cyan
        "\033[94m",  # Light Blue
        "\033[95m",  # Light Magenta
        "\033[92m",  # Light Green
        "\033[93m",  # Light Yellow
    ]
    RESET = "\033[0m"
    RED = "\033[31m"
    WHITE = "\033[37m"
    
    if effect == 'cycle':
        print("\033[s", end='', file=sys.stderr)
        
        for i in range(10):
            colored_text = ""
            for char in message:
                colored_text += random.choice(COLORS) + char
            
            if i == 0:
                print(f"{colored_text}{RESET}", file=sys.stderr)
            else:
                print(f"\033[u\033[K{colored_text}{RESET}", file=sys.stderr)
            time.sleep(0.1)
    else:
        color = RED if "[ERROR]" in message else WHITE
        print(f"{color}[CANDID] {message}{RESET}", file=sys.stderr)

class TransportProtocol:
    """Abstract base class for transport protocols"""
    def __init__(self):
        self.last_write = 0
        self.message_timeout = 0.1  # Default timeout

    def write(self, message):
        """Abstract method for writing messages"""
        raise NotImplementedError("Subclasses must implement write method")

    def read(self):
        """Abstract method for reading messages"""
        raise NotImplementedError("Subclasses must implement read method")

    def flush_buffers(self):
        """Abstract method for clearing communication buffers"""
        raise NotImplementedError("Subclasses must implement flush_buffers method")

    def cleanup(self):
        """Abstract method for cleaning up transport resources"""
        raise NotImplementedError("Subclasses must implement cleanup method")

class UartTransport(TransportProtocol):
    """UART-specific transport implementation"""
    def __init__(self, tx_pin, rx_pin, baudrate=MIDI_BAUDRATE, timeout=UART_TIMEOUT):
        super().__init__()
        _log("[TRANSPORT] Initializing UART transport...")
        
        try:
            self.uart = busio.UART(
                tx=tx_pin,
                rx=rx_pin,
                baudrate=baudrate,
                timeout=timeout,
                bits=8,
                parity=None,
                stop=1
            )
            _log("[TRANSPORT] UART transport initialized successfully")
        except Exception as e:
            _log(f"[TRANSPORT] [ERROR] UART initialization failed: {str(e)}")
            raise

    @property
    def in_waiting(self):
        """Number of bytes waiting to be read"""
        return self.uart.in_waiting

    def write(self, message):
        """Write message to UART with timing control"""
        current_time = time.monotonic()
        delay_needed = self.message_timeout - (current_time - self.last_write)
        
        if delay_needed > 0:
            time.sleep(delay_needed)
        
        if isinstance(message, str):
            message = message.encode('utf-8')
        
        result = self.uart.write(message)
        self.last_write = time.monotonic()
        return result

    def read(self, size=None):
        """Read from UART"""
        if size is None:
            return self.uart.read()
        return self.uart.read(size)

    def flush_buffers(self, timeout=5):
        """Clear UART input buffers"""
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if self.uart.in_waiting:
                self.uart.read()
            else:
                break

    def cleanup(self):
        """Clean shutdown of UART"""
        if hasattr(self, 'uart'):
            _log("[TRANSPORT] Deinitializing UART...")
            self.flush_buffers()
            self.uart.deinit()

class TextProtocol(TransportProtocol):
    """Text protocol implementation that uses an existing transport"""
    def __init__(self, transport):
        super().__init__()
        self.transport = transport
        self.message_timeout = 0.05  # Shorter timeout for text messages
        _log("[TRANSPORT] Text protocol initialized")

    def write(self, message):
        """Write text message with protocol-specific handling"""
        if not isinstance(message, str):
            message = str(message)
        
        # Ensure message ends with newline for protocol consistency
        if not message.endswith('\n'):
            message += '\n'
        
        current_time = time.monotonic()
        delay_needed = self.message_timeout - (current_time - self.last_write)
        if delay_needed > 0:
            time.sleep(delay_needed)
            
        result = self.transport.write(message)
        self.last_write = time.monotonic()
        return result

    def read(self, size=None):
        """Read using underlying transport"""
        return self.transport.read(size)

    def flush_buffers(self):
        """Flush using underlying transport"""
        self.transport.flush_buffers()

    def cleanup(self):
        """No cleanup needed as we don't own the transport"""
        pass

class TransportFactory:
    """Factory for creating transport instances"""
    @staticmethod
    def create_uart_transport(tx_pin, rx_pin, **kwargs):
        """Create a UART transport"""
        return UartTransport(tx_pin, rx_pin, **kwargs)

    @staticmethod
    def create_text_protocol(transport):
        """Create a text protocol using existing transport"""
        return TextProtocol(transport)

class AudioSystem:
    """Manages audio output and processing"""
    def __init__(self, voice_manager):
        _log("Initializing AudioSystem")
        self.audio_out = None
        self.mixer = None
        self.voice_manager = voice_manager
        self._setup_audio()

    def _setup_audio(self):
        """Initialize audio hardware and mixer"""
        try:
            # Setup I2S
            _log("Setting up I2S output...")
            
            audiobusio.I2SOut(I2S_BIT_CLOCK, I2S_WORD_SELECT, I2S_DATA).deinit()

            self.audio_out = audiobusio.I2SOut(
                bit_clock=I2S_BIT_CLOCK,
                word_select=I2S_WORD_SELECT,
                data=I2S_DATA
            )

            # Initialize mixer with keyword args
            _log("Initializing audio mixer...")
            self.mixer = audiomixer.Mixer(
                sample_rate=SAMPLE_RATE,
                buffer_size=AUDIO_BUFFER_SIZE,
                channel_count=AUDIO_CHANNEL_COUNT
            )

            # Connect components - voice manager's synth -> mixer -> audio out
            self.audio_out.play(self.mixer)
            self.mixer.voice[0].play(self.voice_manager.get_synth())
            
            # Set initial low volume for test
            original_volume = self.mixer.voice[0].level
            self.mixer.voice[0].level = 0.1
            
            # Test audio path
            self.voice_manager.test_audio_hardware()
            
            # Restore volume
            self.mixer.voice[0].level = original_volume

            _log("Audio system initialized successfully")

        except Exception as e:
            _log(f"[ERROR] Audio setup failed: {str(e)}")
            self.cleanup()  # Ensure cleanup on error
            raise

    def set_volume(self, normalized_volume):
        """Set volume for the primary mixer channel"""
        try:
            volume = max(0.0, min(1.0, normalized_volume))
            if self.mixer:
                self.mixer.voice[0].level = volume
        except Exception as e:
            _log(f"[ERROR] Volume update failed: {str(e)}")

    def cleanup(self):
        """Cleanup audio system"""
        _log("Starting audio system cleanup")
        try:
            if self.mixer:
                self.mixer.voice[0].level = 0
                time.sleep(0.01)  # Brief pause to let audio settle
            if self.audio_out:
                self.audio_out.stop()
                self.audio_out.deinit()
        except Exception as e:
            _log(f"[ERROR] Audio cleanup failed: {str(e)}")

class RouterManager:  # Renamed from SynthManager to clarify purpose
    """Manages instrument configuration and routing"""
    def __init__(self, voice_manager):
        _log("Router Manager init ...")  # Updated log message
        self.voice_manager = voice_manager
        self.router = None
        self.current_instrument = 'casio'
        self._setup_router()

    def _setup_router(self):
        _log("Setting up router ...")
        # Pass CASIO_PATHS as a positional argument
        self.router = Router(CASIO_PATHS)  # Fixed - using positional arg
        _log("Router setup complete")

    def set_instrument(self, instrument_name):
        """Switch to new instrument"""
        _log(f"Switching to instrument: {instrument_name}")
        try:
            paths = None
            if instrument_name == 'casio':
                paths = CASIO_PATHS
            elif instrument_name == 'organ':
                paths = ORGAN_PATHS
            elif instrument_name == 'mpe':
                paths = MPE_PATHS
            else:
                _log(f"[ERROR] Unknown instrument: {instrument_name}")
                return
            
            # Create new Router with paths as positional argument    
            self.router = Router(paths)  # Fixed - using positional arg
            self.current_instrument = instrument_name
            _log(f"Switched to {instrument_name}")
            
        except Exception as e:
            _log(f"[ERROR] Failed to set instrument: {str(e)}")

    def get_current_config(self):
        """Get current instrument configuration"""
        if self.current_instrument == 'casio':
            return CASIO_PATHS
        elif self.current_instrument == 'organ':
            return ORGAN_PATHS
        elif self.current_instrument == 'mpe':
            return MPE_PATHS
        return None

class Candide:
    def __init__(self):
        _log("\nWakeup Candide!\n", effect='cycle')
        
        # Initialize hardware manager (includes boot beep)
        _log("Initializing hardware manager...")
        self.hardware_manager = HardwareManager()

        # Create single shared UART transport
        _log("Creating UART transport...")
        self.transport = TransportFactory.create_uart_transport(
            tx_pin=UART_TX,
            rx_pin=UART_RX,
            baudrate=UART_BAUDRATE,
            timeout=UART_TIMEOUT
        )

        # Create text protocol using shared transport
        _log("Creating text protocol...")
        self.text_uart = TransportFactory.create_text_protocol(self.transport)

        # Initialize voice manager first since it owns synthio
        _log("Initializing voice manager...")
        self.voice_manager = VoiceManager()

        # Initialize audio system with voice manager
        _log("Initializing audio system...")
        self.audio_system = AudioSystem(self.voice_manager)
        
        # Initialize router manager with voice manager
        _log("Initializing router manager...")
        self.router_manager = RouterManager(self.voice_manager)

        # Initialize connection manager
        _log("Initializing connection manager...")
        self.connection_manager = CandideConnectionManager(
            self.text_uart,
            self.router_manager,  # Needed for getting instrument config
            self.transport
        )

        # Initialize MIDI after connection manager
        _log("Initializing MIDI system...")
        self.midi = MidiLogic(
            uart=self.transport,
            router=self.router_manager.router,
            connection_manager=self.connection_manager,
            voice_manager=self.voice_manager
        )
        
        self.last_encoder_scan = 0
        self.last_volume_scan = 0

        try:
            _log("Setting initial volume...")
            initial_volume = self.hardware_manager.get_initial_volume()
            _log(f"Initial volume: {initial_volume:.3f}")
            self.audio_system.set_volume(initial_volume)
            _log("\nCandide (v1.0) is awake!... ( ◔◡◔)♬\n", effect='cycle')
        except Exception as e:
            _log(f"[ERROR] Initialization error: {str(e)}")
            raise

    def _check_volume(self):
        current_time = time.monotonic()
        if current_time - self.last_volume_scan >= UPDATE_INTERVAL:
            new_volume = self.hardware_manager.read_volume()
            if new_volume is not None:
                self.audio_system.set_volume(new_volume)
            self.last_volume_scan = current_time

    def _check_encoder(self):
        current_time = time.monotonic()
        if current_time - self.last_encoder_scan >= ENCODER_SCAN_INTERVAL:
            events = self.hardware_manager.read_encoder()
            if self.connection_manager.state in [ConnectionState.STANDALONE, ConnectionState.CONNECTED]:
                for event_type, direction in events:
                    _log(f"Encoder events: {events}")
                    if event_type == 'instrument_change':
                        instruments = ['casio', 'organ', 'mpe']
                        current_idx = instruments.index(self.router_manager.current_instrument)  # Updated reference
                        new_idx = (current_idx + direction) % len(instruments)
                        new_instrument = instruments[new_idx]
                        _log(f"Switching to instrument: {new_instrument}")
                        self.router_manager.set_instrument(new_instrument)  # Updated reference
                        # Send new config if connected
                        self.connection_manager.send_config()
                            
            self.last_encoder_scan = current_time

    def update(self):
        try:
            self.midi.check_for_messages()
            self.connection_manager.update_state()
            self._check_encoder()
            self._check_volume()
            self.voice_manager.cleanup_voices()
            return True
            
        except Exception as e:
            _log(f"[ERROR] Update error: {str(e)}")
            return False

    def run(self):
        _log("Starting main loop...")
        try:
            while self.update():
                pass
        except KeyboardInterrupt:
            _log("Keyboard interrupt received")
            pass
        except Exception as e:
            _log(f"[ERROR] Error in run loop: {str(e)}")
        finally:
            _log("Cleaning up...")
            self.cleanup()

    def cleanup(self):
        if self.voice_manager:
            _log("Stopping synthesizer...")
            self.voice_manager.cleanup()
        if self.midi:
            _log("Cleaning up MIDI...")
            self.midi.cleanup()
        if hasattr(self, 'transport'):
            _log("Cleaning up transport...")
            self.transport.cleanup()
        if self.connection_manager:
            _log("Cleaning up connection manager...")
            self.connection_manager.cleanup()
        if self.hardware_manager:
            _log("Cleaning up hardware...")
            self.hardware_manager.cleanup()
        if self.audio_system:
            _log("Cleaning up audio...")
            self.audio_system.cleanup()
        _log("\nCandide goes to sleep... ( ◡_◡)ᶻ 𝗓 𐰁\n")

def main():
    try:
        candide = Candide()
        candide.run()
    except Exception as e:
        _log(f"[ERROR] Fatal error: {str(e)}")

if __name__ == "__main__":
    main()
