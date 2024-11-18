import board

class Constants:
    DEBUG = True
    
    # Audio Hardware (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2  
    I2S_DATA = board.GP0
    
    # Audio Configuration
    SAMPLE_RATE = 44100
    AUDIO_BUFFER_SIZE = 4096  # Reduced for lower latency
    MAX_BUFFER_FULLNESS = 0.8 # Target maximum buffer fullness
    MIN_BUFFER_FULLNESS = 0.2 # Target minimum buffer fullness
    
    # Voice Management
    MAX_VOICES = 12  # Maximum concurrent voices
    VOICE_TIMEOUT_MS = 2000  # Time before inactive voice cleanup
    VOICE_STEAL_THRESHOLD = 0.9  # Load threshold for voice stealing
    
    # Performance Monitoring
    MPE_LOAD_CHECK_INTERVAL = 50  # ms between load checks
    PERFORMANCE_LOG_INTERVAL = 1000  # ms between detailed logs
    ERROR_THRESHOLD = 5  # Errors before throttling
    LOAD_THROTTLE_THRESHOLD = 0.8  # System load causing throttling
    
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

    # System Monitor
    DISABLE_THROTTLING = False

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
    
    @classmethod
    def get_name(cls, source):
        names = {
            cls.NONE: "None",
            cls.PRESSURE: "Pressure",
            cls.PITCH_BEND: "Pitch Bend",
            cls.TIMBRE: "Timbre",
            cls.LFO1: "LFO 1",
            cls.VELOCITY: "Velocity",
            cls.NOTE: "Note",
            cls.GATE: "Gate"
        }
        return names.get(source, f"Unknown Source ({source})")

class ModTarget:
    NONE = 0
    FILTER_CUTOFF = 1
    FILTER_RESONANCE = 2
    OSC_PITCH = 3
    AMPLITUDE = 4
    RING_FREQUENCY = 5
    ENVELOPE_LEVEL = 6
    
    @classmethod
    def get_name(cls, target):
        names = {
            cls.NONE: "None",
            cls.FILTER_CUTOFF: "Filter Cutoff",
            cls.FILTER_RESONANCE: "Filter Resonance",
            cls.OSC_PITCH: "Oscillator Pitch",
            cls.AMPLITUDE: "Amplitude",
            cls.RING_FREQUENCY: "Ring Frequency",
            cls.ENVELOPE_LEVEL: "Envelope Level"
        }
        return names.get(target, f"Unknown Target ({target})")

class FilterType:
    LOW_PASS = "low_pass"
    HIGH_PASS = "high_pass"
    BAND_PASS = "band_pass"
    
    @classmethod
    def get_name(cls, filter_type):
        names = {
            cls.LOW_PASS: "Low Pass",
            cls.HIGH_PASS: "High Pass",
            cls.BAND_PASS: "Band Pass"
        }
        return names.get(filter_type, f"Unknown Filter ({filter_type})")