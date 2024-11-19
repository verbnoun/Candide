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
- Constants:
  * Global audio and synthesis configuration
  * Hardware pin definitions
  * Performance and resource allocation settings
  * Debug and development flags

- ModSource:
  * Defines modulation source types
  * Provides enumeration of possible modulation inputs
  * Supports complex modulation routing

- ModTarget:
  * Defines modulation destination types
  * Provides enumeration of possible modulation targets
  * Enables flexible sound design capabilities

- FilterType:
  * Defines standard filter types
  * Supports multiple filter configurations
  * Enables advanced sound shaping

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
    DEBUG = False
    
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

class ModSource:
    """Enumeration of modulation source types"""
    NONE = 0
    PRESSURE = 1
    PITCH_BEND = 2
    TIMBRE = 3
    LFO1 = 4
    VELOCITY = 5
    NOTE = 6

class ModTarget:
    """Enumeration of modulation destination types"""
    NONE = 0
    FILTER_CUTOFF = 1
    FILTER_RESONANCE = 2
    OSC_PITCH = 3
    AMPLITUDE = 4
    RING_FREQUENCY = 5

class FilterType:
    """Standard filter type definitions"""
    LOW_PASS = "low_pass"
    HIGH_PASS = "high_pass"
    BAND_PASS = "band_pass"
