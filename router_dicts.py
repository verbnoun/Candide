"""Parameter dictionaries for router module."""

# Parameters that should stay as integers
INTEGER_PARAMS = {
    'note_number',      # MIDI note numbers are integers
    'morph_position',   # Used as MIDI value (0-127) for waveform lookup
    'ring_morph_position'  # Used as MIDI value (0-127) for waveform lookup
}

# Value vocabulary - maps human readable values to types and ranges
VALUES = {
    # Actions
    'press': {
        'type': 'action',
        'action': 'press'
    },
    'release': {
        'type': 'action',
        'action': 'release'
    },
    
    # Special values
    'note_number': {
        'type': 'special',
        'converter': 'note_to_freq'
    },
    'bend': {
        'type': 'special',
        'range': (-1, 1)
    },
    
    # Waveforms
    'sine': {
        'type': 'waveform',
        'waveform': 'sine'
    },
    'triangle': {
        'type': 'waveform',
        'waveform': 'triangle'
    },
    'saw': {
        'type': 'waveform',
        'waveform': 'saw'
    },
    'square': {
        'type': 'waveform',
        'waveform': 'square'
    },
    'noise': {
        'type': 'waveform',
        'waveform': 'noise'
    }
}

# Target vocabulary - maps paths to synth parameters
TARGETS = {
    # Note target for press/release
    'note': {
        'handler': 'press',
        'synth_param': None,
        'synth_property': None,
        'use_channel': True,
        'action': 'press'
    },
    'note/press': {
        'handler': 'press',
        'synth_param': None,
        'synth_property': None,
        'use_channel': True,
        'action': 'press'
    },
    'note/release/note_off': {  # Only need this target for note-off
        'handler': 'release',
        'synth_param': None,
        'synth_property': None,
        'use_channel': True,
        'action': 'release'
    },
    
    # Note-specific targets
    'note/oscillator/frequency': {
        'handler': 'store_value',
        'synth_param': 'frequency',
        'synth_property': 'frequency',
        'use_channel': True  # Note-specific
    },
    'note/amplifier/amplitude': {
        'handler': 'update_parameter',
        'synth_param': 'amplifier_amplitude',
        'synth_property': 'amplitude',
        'use_channel': True  # Note-specific
    },
    
    # Global targets
    'oscillator/frequency': {
        'handler': 'store_value',
        'synth_param': 'frequency',
        'synth_property': 'frequency'
    },
    'oscillator/waveform': {
        'handler': 'update_parameter',
        'synth_param': 'waveform',
        'synth_property': 'waveform'
    },
    'oscillator/ring/frequency': {
        'handler': 'update_parameter',
        'synth_param': 'ring_frequency',
        'synth_property': 'ring_frequency'
    },
    'oscillator/ring/waveform': {
        'handler': 'update_parameter',
        'synth_param': 'ring_waveform',
        'synth_property': 'ring_waveform'
    },
    
    # Filter targets
    'filter/high_pass/frequency': {
        'handler': 'update_parameter',
        'synth_param': 'filter_frequency',
        'synth_property': 'filter_frequency'
    },
    'filter/high_pass/resonance': {
        'handler': 'update_parameter',
        'synth_param': 'filter_resonance',
        'synth_property': 'filter_resonance'
    },
    'filter/low_pass/frequency': {
        'handler': 'update_parameter',
        'synth_param': 'filter_frequency',
        'synth_property': 'filter_frequency'
    },
    'filter/low_pass/resonance': {
        'handler': 'update_parameter',
        'synth_param': 'filter_resonance',
        'synth_property': 'filter_resonance'
    },
    'filter/band_pass/frequency': {
        'handler': 'update_parameter',
        'synth_param': 'filter_frequency',
        'synth_property': 'filter_frequency'
    },
    'filter/band_pass/resonance': {
        'handler': 'update_parameter',
        'synth_param': 'filter_resonance',
        'synth_property': 'filter_resonance'
    },
    'filter/notch/frequency': {
        'handler': 'update_parameter',
        'synth_param': 'filter_frequency',
        'synth_property': 'filter_frequency'
    },
    'filter/notch/resonance': {
        'handler': 'update_parameter',
        'synth_param': 'filter_resonance',
        'synth_property': 'filter_resonance'
    },
    
    # Amplifier targets
    'amplifier/amplitude': {
        'handler': 'update_parameter',
        'synth_param': 'amplifier_amplitude',
        'synth_property': 'amplitude'
    },
    'amplifier/envelope/attack_level': {
        'handler': 'update_envelope_param',
        'synth_param': 'attack_level',
        'synth_property': 'attack_level'
    },
    'amplifier/envelope/attack_time': {
        'handler': 'update_envelope_param',
        'synth_param': 'attack_time',
        'synth_property': 'attack_time'
    },
    'amplifier/envelope/decay_time': {
        'handler': 'update_envelope_param',
        'synth_param': 'decay_time',
        'synth_property': 'decay_time'
    },
    'amplifier/envelope/sustain_level': {
        'handler': 'update_envelope_param',
        'synth_param': 'sustain_level',
        'synth_property': 'sustain_level'
    },
    'amplifier/envelope/release_time': {
        'handler': 'update_envelope_param',
        'synth_param': 'release_time',
        'synth_property': 'release_time'
    }
}

# Source vocabulary - maps triggers to MIDI messages
SOURCES = {
    # Note actions
    'note_on': {
        'midi_type': 'noteon',  # Internal MIDI type
        'trigger': 'note_on',   # External trigger name
        'value_type': 'velocity'
    },
    'note_off': {
        'midi_type': 'noteoff',  # Internal MIDI type
        'trigger': 'note_off',   # External trigger name
        'value_type': 'velocity'
    },
    
    # Continuous controllers
    'pressure': {
        'midi_type': 'channelpressure',
        'trigger': 'pressure',
        'value_type': 'continuous'
    },
    'pitch_bend': {
        'midi_type': 'pitchbend',
        'trigger': 'pitch_bend',
        'value_type': 'continuous_14bit'
    },
    
    # Direct value
    'set': {
        'midi_type': 'set',
        'trigger': 'set',
        'value_type': 'direct'
    }
}

# Add CC sources dynamically
for i in range(128):
    SOURCES[f'cc{i}'] = {
        'midi_type': f'cc{i}',  # Match trigger name
        'trigger': f'cc{i}',
        'cc_number': i,
        'value_type': 'continuous'
    }
