"""
config.py - Path Configuration

Contains predefined instrument path configurations.
Each set of paths defines a complete instrument specification.
Paths are authoritative - no defaults or validation needed.
"""

# Basic toy piano configuration
CASIO_PATHS = '''
oscillator/per_key/frequency/20-20000/note_number/440
oscillator/per_key/waveform/na/na/square
amplifier/per_key/gain/0-1/velocity/1
amplifier/per_key/envelope/attack_time/0.001-5/na/0.01
amplifier/per_key/envelope/release_time/0.001-5/na/0.1
amplifier/per_key/envelope/sustain_level/0-1/na/0.8
'''

# Pressure-sensitive organ configuration 
ORGAN_PATHS = '''
oscillator/per_key/frequency/20-20000/note_number/440
oscillator/per_key/waveform/na/cc70/sine
oscillator/ring/per_key/frequency/20-20000/na/880
oscillator/ring/per_key/waveform/na/na/sine

filter/per_key/frequency/20-20000/cc74/1000
filter/per_key/resonance/0.1-2.0/cc71/0.7
filter/global/frequency/20-20000/cc1/1000

amplifier/per_key/gain/0-1/velocity/1
amplifier/per_key/pressure/0-1/channel_pressure/0
amplifier/per_key/envelope/attack_time/0.001-5/cc73/0.1
amplifier/per_key/envelope/decay_time/0.001-5/cc75/0.05
amplifier/per_key/envelope/sustain_level/0-1/cc70/0.8
amplifier/per_key/envelope/release_time/0.001-5/cc72/0.2
'''

# Full MPE configuration
MPE_PATHS = '''
oscillator/per_key/frequency/20-20000/note_number/440
oscillator/per_key/bend/-48-48/pitch_bend/0
oscillator/global/bend/-2-2/pitch_bend/0
oscillator/per_key/waveform/na/cc70/sine
oscillator/per_key/envelope/frequency/attack_time/0.001-5/cc73/0.1
oscillator/per_key/envelope/frequency/attack_level/0-1/velocity/1

oscillator/ring/per_key/frequency/20-20000/cc74/440
oscillator/ring/per_key/waveform/na/cc75/sine
oscillator/ring/per_key/bend/-48-48/pitch_bend/0
oscillator/ring/per_key/envelope/frequency/attack_time/0.001-5/cc76/0.1

filter/per_key/frequency/20-20000/cc74/1000
filter/global/frequency/20-20000/cc1/1000
filter/per_key/resonance/0.1-2.0/cc71/0.7
filter/global/resonance/0.1-2.0/cc2/0.7
filter/per_key/envelope/frequency/attack_time/0.001-5/cc77/0.1
filter/per_key/envelope/frequency/decay_time/0.001-5/cc78/0.2
filter/per_key/envelope/frequency/sustain_level/0-1/cc79/0.5

amplifier/per_key/gain/0-1/velocity/1
amplifier/per_key/pressure/0-1/channel_pressure/0
amplifier/global/pressure/0-1/channel_pressure/0

amplifier/per_key/envelope/amplitude/attack_time/0.001-5/cc73/0.1
amplifier/per_key/envelope/amplitude/attack_level/0-1/velocity/1
amplifier/per_key/envelope/amplitude/decay_time/0.001-5/cc75/0.05
amplifier/per_key/envelope/amplitude/decay_level/0-1/cc76/0.8
amplifier/per_key/envelope/amplitude/sustain_time/0.001-5/cc85/0.2
amplifier/per_key/envelope/amplitude/sustain_level/0-1/cc70/0.8
amplifier/per_key/envelope/amplitude/release_time/0.001-5/cc72/0.2

oscillator/per_key/lfo/rate/0.1-20/cc20/5
oscillator/per_key/lfo/depth/0-1/cc21/0.5
filter/per_key/lfo/rate/0.1-20/cc22/2
filter/per_key/lfo/depth/0-1/cc23/0.3

oscillator/per_key/timbre/0-1/cc74/0.5
filter/per_key/expression/0-1/cc11/1
amplifier/global/expression/0-1/cc7/1
'''

# Signal chain processing order 
SIGNAL_CHAIN_ORDER = ('oscillator', 'filter', 'amplifier')
