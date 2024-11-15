# Candide MPE Synthesiser
## CircuitPython MPE driven synthesizer 

Candide is a digital synthesizer built on CircuitPython, featuring MPE (MIDI Polyphonic Expression) compatibility. The system combines a synthesis engine with MPE processing capabilities, allowing for expressive control over multiple dimensions of sound per note.

The synthesizer provides distinct instruments, as of this writing a velocity-sensitive piano, a classic organ with drawbar-like controls, a bass-heavy "womp" synthesizer with aggressive filtering, and a metallic wind chime percussion. Each instrument features parameters for oscillator configuration, filter settings, and envelope characteristics, all accessible through real-time hardware controls.

At its core, Candide implements a complete MPE system with zone management, voice allocation, and per-note control of pitch, pressure, and timbre. The hardware interface combines a rotary encoder for instrument selection with a potentiometer for volume control, while audio output is handled through a PCM5102A DAC for high-quality stereo sound.

## Architecture

### Core Components

- **Synthesizer Engine**: Implements audio synthesis with configurable oscillators, filters, and envelopes
- **MPE (MIDI Polyphonic Expression) System**: Full MPE implementation with zone management and voice allocation
- **Hardware Interface**: Handles rotary encoder and potentiometer input
- **Audio Output**: I2S audio output using PCM5102A DAC
- **UART/MIDI Communication**: Bidirectional MIDI communication with base station

### Key Classes

- `Candide`: Main application class coordinating all subsystems
- `SynthManager`: Manages synthesis engine and instrument configurations
- `MidiLogic`: Handles MIDI parsing and MPE implementation
- `AudioManager`: Controls audio output and mixing
- `HardwareManager`: Manages physical controls

## Features

### Synthesis

- Multiple waveform types (sine, saw, triangle, square)
- Configurable filters (low-pass, high-pass, band-pass)
- ADSR envelope control
- Real-time parameter modulation

### Instruments

- Piano: Realistic piano simulation with velocity sensitivity
- Organ: Classic organ sound with drawbar-like controls
- Womp: Bass-heavy synthesizer with aggressive filtering
- Wind Chime: Metallic percussion with long release

### MPE Capabilities

- Full MPE zone management
- Per-note pitch bend
- Per-note pressure sensitivity
- Timbre control (CC74)
- Configurable pitch bend ranges

### Hardware Interface

- Instrument selection via rotary encoder
- Volume control via potentiometer
- Real-time parameter adjustment
- LED status indication

## Technical Specifications

### Audio

- Sample Rate: 44.1 kHz
- Buffer Size: 8192 samples
- I2S Output
- Stereo output

### MIDI

- Standard MIDI baudrate (31250)
- MPE-compliant
- Support for running status
- Configurable zones

### Hardware Requirements

- CircuitPython-compatible microcontroller
- PCM5102A DAC
- Rotary encoder
- Potentiometer
- I2S interface
- UART interface

## Dependencies

- CircuitPython
- `busio`
- `digitalio`
- `analogio`
- `rotaryio`
- `synthio`
- `audiobusio`
- `audiomixer`

## Implementation Details

### Synthesis Engine

- Real-time waveform generation
- Dynamic filter updates
- Envelope generation
- Voice allocation management

### MPE Implementation

- Zone management (lower/upper)
- Channel allocation
- Voice state tracking
- Controller state management

### Hardware Interface

- Debounced encoder reading
- Analog input filtering
- Update rate management
- Resource cleanup
