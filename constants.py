"""
Centralized Constants for Candide Synthesizer Project

This file contains all project-wide constants, organized into logical groups 
for easy maintenance and reference.
"""

import board

# Debug Flags
DEBUG = True
HARDWARE_DEBUG = False
MIDI_DEBUG = False
ROUTER_DEBUG = True
SYNTH_DEBUG = True
OUTPUT_DEBUG = False

# ADC (Analog-to-Digital Conversion) Constants
ADC_MAX = 65535
ADC_MIN = 1

# Audio Configuration
SAMPLE_RATE = 44100
AUDIO_BUFFER_SIZE = 8192  # Reduced for lower latency
MAX_BUFFER_FULLNESS = 0.8  # Target maximum buffer fullness
MIN_BUFFER_FULLNESS = 0.2  # Target minimum buffer fullness
AUDIO_CHANNEL_COUNT = 2  # Number of audio channels (stereo)

# I2S Audio Output Pins
I2S_BIT_CLOCK = board.GP1
I2S_WORD_SELECT = board.GP2
I2S_DATA = board.GP0

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
    """Connection states for base station communication"""
    STANDALONE = "standalone"
    DETECTED = "detected"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"
    RETRY_DELAY = "retry_delay"
