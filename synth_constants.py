import board

class Constants:
    DEBUG = True
    
    # Audio Hardware (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2
    I2S_DATA = board.GP0
    
    # Audio Configuration
    SAMPLE_RATE = 44100
    AUDIO_BUFFER_SIZE = 8192
    
    # Synthesis Configuration
    MAX_VOICES = 8
    VOICE_TIMEOUT_MS = 2000
    
    # MPE Configuration
    DEFAULT_MPE_PITCH_BEND_RANGE = 48  # semitones
    DEFAULT_PRESSURE_SENSITIVITY = 0.7
    MPE_LOAD_CHECK_INTERVAL = 100  # ms
    
    # Modulation Configuration
    LFO_UPDATE_RATE = 100  # Hz
    MAX_MODULATION_SOURCES = 8
    MAX_MODULATION_TARGETS = 8
    
    # Waveform Generation
    WAVE_TABLE_SIZE = 512
    MAX_AMPLITUDE = 32767
    MIN_AMPLITUDE = -32768

# Modulation sources and targets
class ModSource:
    NONE = 0
    PRESSURE = 1
    PITCH_BEND = 2
    TIMBRE = 3
    LFO1 = 4
    VELOCITY = 5
    NOTE = 6
    GATE = 7

class ModTarget:
    NONE = 0
    FILTER_CUTOFF = 1
    FILTER_RESONANCE = 2
    OSC_PITCH = 3
    AMPLITUDE = 4
    RING_FREQUENCY = 5

class FilterType:
    LOW_PASS = "low_pass"
    HIGH_PASS = "high_pass"
    BAND_PASS = "band_pass"
