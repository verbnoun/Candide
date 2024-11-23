"""
Centralized Constants for Candide Synthesizer Project

This file contains all project-wide constants, organized into logical groups 
for easy maintenance and reference.
"""

import board

# Debug Flags
DEBUG = True
HARDWARE_DEBUG = False
MIDI_DEBUG = True
ROUTER_DEBUG = False
VOICES_DEBUG = False
SYNTH_DEBUG = False
OUTPUT_DEBUG = False



# ADC (Analog-to-Digital Conversion) Constants
ADC_MAX = 65535
ADC_MIN = 1

# Audio Configuration
SAMPLE_RATE = 44100
AUDIO_BUFFER_SIZE = 8192  # Reduced for lower latency
MAX_BUFFER_FULLNESS = 0.8  # Target maximum buffer fullness
MIN_BUFFER_FULLNESS = 0.2  # Target minimum buffer fullness

# I2S Audio Output Pins
I2S_BIT_CLOCK = board.GP1
I2S_WORD_SELECT = board.GP2
I2S_DATA = board.GP0

# Voice Management
MAX_VOICES = 12  # Maximum concurrent voices
VOICE_TIMEOUT_MS = 2000  # Time before inactive voice cleanup
VOICE_STEAL_THRESHOLD = 0.9  # Load threshold for voice stealing
DEFAULT_MPE_PITCH_BEND_RANGE = 48  # semitones
DEFAULT_PRESSURE_SENSITIVITY = 0.7

# Volume Control
VOLUME_MIN_CHANGE = 0.01  # Minimum volume change to process
VOLUME_UPDATE_INTERVAL = 10  # ms between volume updates

# Modulation Configuration
LFO_UPDATE_RATE = 100  # Hz
MAX_MODULATION_SOURCES = 8
MAX_MODULATION_TARGETS = 8

# Waveform Generation
WAVE_TABLE_SIZE = 512
MAX_AMPLITUDE = 32767
MIN_AMPLITUDE = -32768

# Hardware Constants
INSTRUMENT_ENC_CLK = board.GP20
INSTRUMENT_ENC_DT = board.GP21
VOLUME_POT = board.GP26
UPDATE_INTERVAL = 0.01
ENCODER_SCAN_INTERVAL = 0.001
POT_THRESHOLD = 800
POT_LOWER_TRIM = 0.05
POT_UPPER_TRIM = 0.0

# MIDI and Communication Constants
UART_TX = board.GP16
UART_RX = board.GP17
UART_BAUDRATE = 31250
UART_TIMEOUT = 0.001
MIDI_BAUDRATE = 31250

# Hardware Setup
SETUP_DELAY = 0.1  # in seconds

# Connection Management
DETECT_PIN = board.GP22
MESSAGE_TIMEOUT = 0.05  # in seconds
HELLO_INTERVAL = 0.5  # in seconds
HEARTBEAT_INTERVAL = 1.0  # in seconds
HANDSHAKE_TIMEOUT = 5.0  # in seconds
HANDSHAKE_MAX_RETRIES = 10
HANDSHAKE_CC = 119
HANDSHAKE_VALUE = 42
WELCOME_VALUE = 43

# Connection Timing Constants
STARTUP_DELAY = 1.0  # in seconds
RETRY_DELAY = 5.0  # in seconds
RETRY_INTERVAL = 0.25  # in seconds
ERROR_RECOVERY_DELAY = 0.5  # in seconds
BUFFER_CLEAR_TIMEOUT = 0.1  # in seconds
MAX_RETRIES = 3

# Fixed Point Math Constants
FIXED_POINT_SCALE = 1 << 16
FIXED_POINT_MAX_VALUE = (1 << 31) - 1
FIXED_POINT_MIN_VALUE = -(1 << 31)
FIXED_POINT_ONE = 1 << 16
FIXED_POINT_HALF = 1 << 15
FIXED_POINT_ZERO = 0
MIDI_SCALE = 1.0 / 127
PITCH_BEND_SCALE = 8
PITCH_BEND_CENTER = 8192 << 16

# Modulation Source Types
class ModSource:
    NONE = 0
    PRESSURE = 1
    PITCH_BEND = 2
    TIMBRE = 3
    LFO1 = 4
    VELOCITY = 5
    NOTE = 6
    GATE = 7
    CC = 8

# Modulation Destination Types
class ModTarget:
    NONE = 0
    FILTER_CUTOFF = 1
    FILTER_RESONANCE = 2
    OSC_PITCH = 3
    AMPLITUDE = 4
    RING_FREQUENCY = 5
    ENVELOPE_LEVEL = 6
    FREQUENCY = 7
    WAVEFORM = 8

# Modulation Source Types (Alias for backwards compatibility)
ModulationSource = ModSource
ModulationDestination = ModTarget

# Modulation Source Types
class ModulationSourceType:
    NONE = 0
    PRESSURE = 1
    PITCH_BEND = 2
    TIMBRE = 3
    LFO1 = 4
    VELOCITY = 5
    NOTE = 6
    GATE = 7

# Modulation Destination Types
class ModulationDestinationType:
    NONE = 0
    FILTER_CUTOFF = 1
    FILTER_RESONANCE = 2
    OSC_PITCH = 3
    AMPLITUDE = 4
    RING_FREQUENCY = 5
    ENVELOPE_LEVEL = 6

# Filter Types
class FilterType:
    LOW_PASS = "low_pass"
    HIGH_PASS = "high_pass"
    BAND_PASS = "band_pass"

# Standard MIDI Control Change Numbers
class MidiCC:
    MODULATION_WHEEL = 1
    BREATH = 2
    FOOT = 4
    PORTAMENTO_TIME = 5
    VOLUME = 7
    BALANCE = 8
    PAN = 10
    EXPRESSION = 11
    EFFECT1 = 12
    
    # Sound Controllers
    SOUND_VARIATION = 70
    RESONANCE = 71
    RELEASE_TIME = 72
    ATTACK_TIME = 73
    BRIGHTNESS = 74
    
    # Effect Depths
    REVERB = 91
    TREMOLO = 92
    CHORUS = 93
    DETUNE = 94
    PHASER = 95

# MPE Configuration
class MPEConfig:
    ZONE_MANAGER = 0       # MIDI channel 1 (zero-based)
    ZONE_START = 1         # First member channel
    ZONE_END = 15          # Last member channel
    DEFAULT_ZONE_MEMBER_COUNT = 15
    MASTER_PITCH_BEND_RANGE = 2    # ±2 semitones default for Manager Channel
    MEMBER_PITCH_BEND_RANGE = 48   # ±48 semitones default for Member Channels

# MIDI Message Types
class MidiMessageType:
    NOTE_OFF = 0x80
    NOTE_ON = 0x90
    POLY_PRESSURE = 0xA0
    CONTROL_CHANGE = 0xB0
    PROGRAM_CHANGE = 0xC0
    CHANNEL_PRESSURE = 0xD0
    PITCH_BEND = 0xE0
    SYSTEM_MESSAGE = 0xF0

# Connection States
class ConnectionState:
    STANDALONE = 0
    DETECTED = 1
    HANDSHAKING = 2
    CONNECTED = 3
    RETRY_DELAY = 4
