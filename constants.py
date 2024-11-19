"""
Global Constants and Configuration Module

This module provides comprehensive configuration parameters 
and constant definitions for the Candide Synthesizer, 
enabling centralized management of system-wide settings.

Key Responsibilities:
- Define global configuration parameters
- Provide centralized constant management
- Support system-wide audio and synthesis configurations
- Enable flexible modulation and synthesis settings

Primary Classes:
- Constants: Global audio and synthesis configuration
- ModSource: Modulation source types
- ModTarget: Modulation destination types
- FilterType: Standard filter types
- CCMapping: MIDI Control Change mappings

Key Features:
- Comprehensive audio configuration
- Flexible modulation routing
- Configurable synthesis parameters
- Support for multiple synthesis techniques
- Easy parameter tuning and modification
"""

import board

class Constants:
    """Global configuration parameters for Candide Synthesizer"""
    # Debug Flags
    DEBUG = True
    MOD_DEBUG = False
    MOD_LFO_DEBUG = False
    MOD_ENV_DEBUG = False
    MPE_ROUTE_DEBUG = False
    MPE_NOTE_DEBUG = False
    MPE_VOICE_DEBUG = False
    MPE_ROUTER_DEBUG = False
    OUTPUT_PERF_DEBUG = False
    OUTPUT_AUDIO_DEBUG = False
    SYNTH_WAVE_DEBUG = False
    SYNTH_DEBUG = False
    SYNTH_IO_DEBUG = False
    SYNTH_CO_DEBUG = False
    
    # Audio Hardware (PCM5102A DAC)
    I2S_BIT_CLOCK = board.GP1
    I2S_WORD_SELECT = board.GP2
    I2S_DATA = board.GP0
    
    # Audio Configuration
    SAMPLE_RATE = 44100
    AUDIO_BUFFER_SIZE = 4096  # Reduced for lower latency
    MAX_BUFFER_FULLNESS = 0.8  # Target maximum buffer fullness
    MIN_BUFFER_FULLNESS = 0.2  # Target minimum buffer fullness
    
    # Voice Management
    MAX_VOICES = 12  # Maximum concurrent voices
    VOICE_TIMEOUT_MS = 2000  # Time before inactive voice cleanup
    VOICE_STEAL_THRESHOLD = 0.9  # Load threshold for voice stealing
    DEFAULT_MPE_PITCH_BEND_RANGE = 48  # semitones
    DEFAULT_PRESSURE_SENSITIVITY = 0.7
    
    # Performance Monitoring
    MPE_LOAD_CHECK_INTERVAL = 50  # ms between load checks
    PERFORMANCE_LOG_INTERVAL = 1000  # ms between detailed logs
    
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



class ModSource:
    """Enumeration of modulation source types"""
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
    """Enumeration of modulation destination types"""
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
    """Standard filter type definitions"""
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

class CCMapping:
    """Standard MIDI CC number definitions"""
    # Standard MIDI CCs
    MODULATION_WHEEL = 1
    BREATH = 2
    FOOT = 4
    PORTAMENTO_TIME = 5
    VOLUME = 7
    BALANCE = 8
    PAN = 10
    EXPRESSION = 11
    EFFECT1 = 12
    EFFECT2 = 13
    
    # Sound Controllers
    SOUND_VARIATION = 70
    RESONANCE = 71
    RELEASE_TIME = 72
    ATTACK_TIME = 73
    BRIGHTNESS = 74
    SOUND_CTRL6 = 75
    SOUND_CTRL7 = 76
    SOUND_CTRL8 = 77
    SOUND_CTRL9 = 78
    SOUND_CTRL10 = 79
    
    # Effect Depths
    REVERB = 91
    TREMOLO = 92
    CHORUS = 93
    DETUNE = 94
    PHASER = 95
    
    # Undefined CCs available for custom use
    UNDEFINED1 = 3
    UNDEFINED2 = 9
    UNDEFINED3 = 14
    UNDEFINED4 = 15
    UNDEFINED5 = 20  # 20-31 range available
