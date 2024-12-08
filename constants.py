"""Centralized constants and configuration values for the Candide synthesizer project."""

import board

# Waveform sample sizes
STATIC_WAVEFORM_SAMPLES = 512   # Sample size for static waveforms
MORPHED_WAVEFORM_SAMPLES = 512  # Sample size for morphed waveforms

ADC_MAX = 65535
ADC_MIN = 1

SAMPLE_RATE = 44100
AUDIO_BUFFER_SIZE = 8192
MAX_BUFFER_FULLNESS = 0.8
MIN_BUFFER_FULLNESS = 0.2
AUDIO_CHANNEL_COUNT = 2

I2S_BIT_CLOCK = board.GP1
I2S_WORD_SELECT = board.GP2
I2S_DATA = board.GP0

INSTRUMENT_ENC_CLK = board.GP20
INSTRUMENT_ENC_DT = board.GP21
VOLUME_POT = board.GP26
UPDATE_INTERVAL = 0.01
ENCODER_SCAN_INTERVAL = 0.001
POT_THRESHOLD = 800
POT_LOWER_TRIM = 0.05
POT_UPPER_TRIM = 0.0

UART_TX = board.GP16
UART_RX = board.GP17
UART_BAUDRATE = 31250
UART_TIMEOUT = 0.001
MIDI_BAUDRATE = 31250

SETUP_DELAY = 0.1

DETECT_PIN = board.GP22
MESSAGE_TIMEOUT = 0.05
HELLO_INTERVAL = 0.5
HEARTBEAT_INTERVAL = 1.0
HANDSHAKE_TIMEOUT = 5.0
HANDSHAKE_MAX_RETRIES = 10
HANDSHAKE_CC = 119
HANDSHAKE_VALUE = 42
WELCOME_VALUE = 43

STARTUP_DELAY = 1.0
RETRY_DELAY = 5.0
RETRY_INTERVAL = 0.25
DETECTION_RETRY_INTERVAL = 0.25
ERROR_RECOVERY_DELAY = 0.5
BUFFER_CLEAR_TIMEOUT = 0.1
MAX_RETRIES = 3

class MidiMessageType:
    NOTE_OFF = 0x80
    NOTE_ON = 0x90
    POLY_PRESSURE = 0xA0
    CONTROL_CHANGE = 0xB0
    PROGRAM_CHANGE = 0xC0
    CHANNEL_PRESSURE = 0xD0
    PITCH_BEND = 0xE0
    SYSTEM_MESSAGE = 0xF0

class ConnectionState:
    STANDALONE = "standalone"
    DETECTED = "detected"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"
    RETRY_DELAY = "retry_delay"
