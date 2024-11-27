"""
config.py - Path Configuration

Contains predefined instrument path configurations.
Each set of paths defines a complete instrument specification.
Paths are authoritative - no defaults or validation needed.
"""

# Basic toy piano configuration with minimum needed paths for synthio
CASIO_PATHS = '''
oscillator/per_key/frequency/20-20000/note_number
oscillator/per_key/waveform/square/note_on
amplifier/per_key/gain/0-1/velocity
amplifier/global/envelope/attack_time/0.001-5/cc73/0.01
amplifier/global/envelope/decay_time/0.001-5/cc75/0.05
amplifier/global/envelope/attack_level/0-1/cc72/1.0
amplifier/global/envelope/sustain_level/0-1/cc70/0.8
amplifier/per_key/envelope/attack/trigger/note_on
amplifier/per_key/envelope/release/trigger/note_off
'''

# Pressure-sensitive organ configuration 
ORGAN_PATHS = '''
oscillator/per_key/frequency/20-20000/note_number/440
oscillator/per_key/trigger/na/note_on
oscillator/per_key/waveform/sine/note_on
oscillator/ring/per_key/frequency/20-20000/na/880
oscillator/ring/per_key/trigger/na/note_on
oscillator/ring/per_key/waveform/sine/note_on

filter/per_key/frequency/20-20000/cc74/1000
filter/per_key/resonance/0.1-2.0/cc71/0.7
filter/global/frequency/20-20000/cc1/1000

amplifier/per_key/gain/0-1/velocity/1
amplifier/per_key/pressure/0-1/channel_pressure/0
amplifier/global/envelope/attack_time/0.001-5/cc73/0.1
amplifier/global/envelope/decay_time/0.001-5/cc75/0.05
amplifier/global/envelope/sustain_level/0-1/cc70/0.8
amplifier/global/envelope/release_time/0.001-5/cc72/0.2
'''

# Full MPE configuration
MPE_PATHS = '''
oscillator/per_key/frequency/20-20000/note_number/440
oscillator/per_key/trigger/na/note_on
oscillator/per_key/bend/-48-48/pitch_bend/0
oscillator/global/bend/-2-2/pitch_bend/0
oscillator/per_key/waveform/sine/note_on
oscillator/global/envelope/frequency/attack_time/0.001-5/cc73/0.1
oscillator/per_key/envelope/frequency/attack_level/0-1/velocity/1

oscillator/ring/per_key/frequency/20-20000/cc74/440
oscillator/ring/per_key/trigger/na/note_on
oscillator/ring/per_key/waveform/sine/note_on
oscillator/ring/per_key/bend/-48-48/pitch_bend/0
oscillator/ring/global/envelope/frequency/attack_time/0.001-5/cc76/0.1

filter/global/per_key/20-20000/cc74/1000
filter/global/frequency/20-20000/cc1/1000
filter/global/resonance/0.1-2.0/cc71/0.7
filter/global/resonance/0.1-2.0/cc2/0.7
filter/global/envelope/frequency/attack_time/0.001-5/cc77/0.1
filter/global/envelope/frequency/decay_time/0.001-5/cc78/0.2
filter/global/envelope/frequency/sustain_level/0-1/cc79/0.5

amplifier/per_key/gain/0-1/velocity/1
amplifier/per_key/pressure/0-1/channel_pressure/0

amplifier/global/envelope/amplitude/attack_time/0.001-5/cc73/0.1
amplifier/global/envelope/amplitude/attack_level/0-1/velocity/1
amplifier/global/envelope/amplitude/decay_time/0.001-5/cc75/0.05
amplifier/global/envelope/amplitude/decay_level/0-1/cc76/0.8
amplifier/global/envelope/amplitude/sustain_time/0.001-5/cc85/0.2
amplifier/global/envelope/amplitude/sustain_level/0-1/cc70/0.8
amplifier/global/envelope/amplitude/release_time/0.001-5/cc72/0.2

oscillator/global/lfo/rate/0.1-20/cc20/5
oscillator/global/lfo/depth/0-1/cc21/0.5
filter/global/lfo/rate/0.1-20/cc22/2
filter/global/lfo/depth/0-1/cc23/0.3

oscillator/per_key/timbre/0-1/cc74/0.5
filter/per_key/expression/0-1/cc11/1
amplifier/global/expression/0-1/cc7/1
'''

# Signal chain processing order 
SIGNAL_CHAIN_ORDER = ('oscillator', 'filter', 'amplifier')