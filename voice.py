"""Voice module for synthesizer system."""


import synthio
from logging import log, TAG_VOICE

class Voice:
    """A voice that can be targeted by MIDI address."""
    def __init__(self):
        self.channel = None
        self.note_number = None
        self.active_note = None
        self.timestamp = 0
        
    def get_address(self):
        """Get voice's current address (note_number.channel)."""
        if self.note_number is not None and self.channel is not None:
            return "{}.{}".format(self.note_number, self.channel)
        return None
        
    def _log_state(self, synth, action=""):
        """Log voice state showing note counts by state."""
        addr = self.get_address()
        if not addr:
            log(TAG_VOICE, "Voice has no address")
            return
            
        # Get note states from synth
        active_count = 1 if self.active_note else 0
        releasing_count = 0
        
        if self.active_note:
            state, _ = synth.note_info(self.active_note)
            if state == synthio.EnvelopeState.RELEASE:
                active_count = 0
                releasing_count = 1
            
        if action:
            action = " " + action
            
        state = []
        if active_count > 0:
            state.append("{} active".format(active_count))
        if releasing_count > 0:
            state.append("{} releasing".format(releasing_count))
            
        log(TAG_VOICE, "Voice {}{}: has {}".format(
            addr,
            action,
            ", ".join(state) if state else "no notes"
        ))

    def _create_filter(self, synth, filter_type, frequency, resonance):
        """Create a filter based on type with current parameters."""
        if filter_type == 'low_pass':
            return synth.low_pass_filter(frequency, resonance)
        elif filter_type == 'high_pass':
            return synth.high_pass_filter(frequency, resonance)
        elif filter_type == 'band_pass':
            return synth.band_pass_filter(frequency, resonance)
        elif filter_type == 'notch':
            return synth.notch_filter(frequency, resonance)
        return None
        
    def press_note(self, note_number, channel, synth, **note_params):
        """Target this voice with a note-on."""
        if self.active_note:
            synth.release(self.active_note)
            
        # Set new address
        self.note_number = note_number
        self.channel = channel
        
        # Create filter if parameters provided
        if 'filter_type' in note_params and 'filter_frequency' in note_params and 'filter_resonance' in note_params:
            filter = self._create_filter(
                synth,
                note_params.pop('filter_type'),
                note_params.pop('filter_frequency'),
                note_params.pop('filter_resonance')
            )
            if filter:
                note_params['filter'] = filter
        
        # Ensure amplitude is set
        if 'amplitude' not in note_params:
            note_params['amplitude'] = 1.0
            
        # Create new active note - will use synth's global envelope
        self.active_note = synthio.Note(**note_params)
        synth.press(self.active_note)
        self._log_state(synth, "pressed")
        
    def release_note(self, synth, forced=False):
        """Target this voice with a note-off."""
        if self.active_note:
            addr = self.get_address()
            synth.release(self.active_note)
            action = "forced release" if forced else "released"
            self._log_state(synth, action)
            self.active_note = None
            self.note_number = None
            self.channel = None
            
    def steal_voice(self, synth):
        """Release voice during stealing."""
        if self.active_note:
            addr = self.get_address()
            synth.release(self.active_note)
            self._log_state(synth, "forced release")
            self.active_note = None
            self.note_number = None
            self.channel = None
            
    def update_active_note(self, synth, **params):
        """Update parameters of active note."""
        if self.active_note:
            # Handle filter updates
            if ('filter_type' in params and 'filter_frequency' in params and 
                'filter_resonance' in params):
                filter = self._create_filter(
                    synth,
                    params.pop('filter_type'),
                    params.pop('filter_frequency'),
                    params.pop('filter_resonance')
                )
                if filter:
                    params['filter'] = filter
            
            # Update note parameters including ring modulation
            for param, value in params.items():
                if hasattr(self.active_note, param):
                    setattr(self.active_note, param, value)
            self._log_state(synth, "changed")
            
    def is_active(self):
        """Check if voice has active note."""
        return self.active_note is not None
