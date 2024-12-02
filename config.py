"""
config.py - Path Configuration

Contains predefined instrument path configurations.
Each set of paths defines a complete instrument specification.
Paths are authoritative - no defaults or validation needed.
Paths are read right (Inlet) to left (Target)
Path:
    Stage/Module/SubModule/Scope/value/Midi
Route:
    Stage/Module/SubModule/Scope/Value
"""

# Minimum for synthio note
# without an explicit envelope, what does synthio do with a release?
# If Note waveform or envelope are None the synthesizer object’s default waveform or envelope are used. if defaults not set, 50% square and no envelope.
MINIMUM_PATHS = '''
note/per_key/note_number.channel/press_note/note_on  
note/per_key/note_number.channel/release_note/note_off
'''

OSCILLATOR_PATHS = '''
oscillator/global/frequency/note_number/note_on
oscillator/global/waveform/saw/note_on
oscillator/ring/global/frequency/20-2000/cc74
oscillator/ring/global/waveform/triangle/note_on
'''

# Filter
FILTER_PATHS = '''
filter/band_pass/global/resonance/0.1-2.0/cc71
filter/band_pass/global/frequency/20-20000/cc70
'''

# Amplifier
AMP_PATHS = '''
amplifier/global/envelope/attack_level/0-1/cc74/1
amplifier/global/envelope/attack_time/0.001-0.5/cc73/0.5
amplifier/global/envelope/decay_time/0.001-0.25/cc75/0.25
amplifier/global/envelope/sustain_level/0-1/cc85/0.8
amplifier/global/envelope/release_time/0.001-3/cc72/0.2
'''

# Oscillator > Filter > Amplifier
CASIO_PATHS = '''
oscillator/per_key/frequency/trigger/note_number
oscillator/per_key/waveform/saw/note_on

filter/band_pass/global/resonance/0.1-2.0/cc71/0.7
filter/band_pass/global/frequency/20-20000/cc70/1000

amplifier/per_key/envelope/attack/trigger/note_on
amplifier/per_key/envelope/release/trigger/note_off

amplifier/global/envelope/attack_level/0-1/cc74/1
amplifier/global/envelope/attack_time/0.001-0.5/cc73/0.5
amplifier/global/envelope/decay_time/0.001-0.25/cc75/0.25
amplifier/global/envelope/sustain_level/0-1/cc85/0.8
amplifier/global/envelope/release_time/0.001-3/cc72/0.2
'''

# Ring modulation instrument configuration
RING_MOD_PATHS = '''
oscillator/per_key/press_note/trigger/note_on  
oscillator/per_key/release_note/trigger/note_off

oscillator/per_key/frequency/trigger/note_number
oscillator/per_key/waveform/triangle/note_on

oscillator/ring/global/frequency/20-2000/cc74/440
oscillator/ring/global/waveform/saw/note_on
'''


# Pressure-sensitive configuration 
PPRESSURE_PATHS = '''

'''
