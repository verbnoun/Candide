"""Note management and parameter handling for synthesizer."""

import synthio
from logging import log, TAG_NOTE, format_value

class NoteManager:
    """Manages active notes and their parameters."""
    
    # Note parameters that are BlockInputs
    NOTE_PARAMS = {'amplitude', 'bend', 'panning'}
    
    # Filter parameters that are BlockInputs
    FILTER_PARAMS = {'filter_frequency', 'filter_q'}
    
    # All block parameters (for retrigger)
    BLOCK_PARAMS = NOTE_PARAMS | FILTER_PARAMS
    
    # Parameters that are values
    VALUE_PARAMS = {
        'waveform', 'waveform_loop_start', 'waveform_loop_end',
        'ring_frequency', 'ring_bend', 'ring_waveform',
        'ring_waveform_loop_start', 'ring_waveform_loop_end'
    }
    
    def __init__(self, synth, store, modulation_manager):
        self.synth = synth
        self.store = store
        self.modulation = modulation_manager
        self.notes = {}  # "note_number.channel" -> Note
        self.channel_map = {}  # channel -> note_number
        
    def _build_note_params(self, note_number, frequency, channel, **params):
        """Build parameters for synthio.Note creation.
        
        Args:
            note_number: MIDI note number for block lookup
            frequency: Note frequency in Hz
            channel: MIDI channel for parameter lookup
            **params: Additional parameters to override stored values
            
        Returns:
            Dict of parameters for synthio.Note
        """
        note_params = {'frequency': frequency}
        
        # Get blocks for note parameters
        for param in self.NOTE_PARAMS:
            log(TAG_NOTE, f"Getting block for {param}")
            block = self.modulation.get_block(param, note_number, channel)
            if block:
                if isinstance(block, synthio.LFO):
                    log(TAG_NOTE, f"  {param} controlled by LFO:")
                    log(TAG_NOTE, f"    rate: {block.rate} Hz")
                    log(TAG_NOTE, f"    scale: {block.scale}")
                    log(TAG_NOTE, f"    offset: {block.offset}")
                    log(TAG_NOTE, f"    current value: {block.value}")
                log(TAG_NOTE, f"  Using block for {param}: {type(block).__name__}")
                note_params[param] = block
                
        # Get values for value parameters
        for param in self.VALUE_PARAMS:
            value = self.store.get(param, channel)
            if value is not None:
                if param == 'waveform':
                    log(TAG_NOTE, "Using waveform value")
                else:
                    log(TAG_NOTE, f"Using value for {param}: {format_value(value)}")
                note_params[param] = value
                
        # Add envelope if stored
        envelope_params = {}
        log(TAG_NOTE, f"Building envelope parameters for channel {channel}:")
        for param in ['attack_time', 'decay_time', 'release_time', 
                     'attack_level', 'sustain_level']:
            value = self.store.get(param, channel)
            log(TAG_NOTE, f"  {param}: {value} (from store)")
            if value is not None:
                envelope_params[param] = value
                
        if envelope_params:
            try:
                log(TAG_NOTE, f"Creating envelope with params: {envelope_params}")
                note_params['envelope'] = synthio.Envelope(**envelope_params)
                log(TAG_NOTE, f"Created envelope for channel {channel}")
            except Exception as e:
                log(TAG_NOTE, f"Error creating envelope: {str(e)}", is_error=True)
                
        # Create filter with blocks if type is set
        filter_type = self.store.get('filter_type', channel)
        if filter_type:
            try:
                # Convert string filter type to synthio.FilterMode
                filter_mode_name = filter_type.replace(' ', '_').upper()
                filter_mode = getattr(synthio.FilterMode, filter_mode_name)
                
                # Get blocks for filter parameters
                freq_block = self.modulation.get_block('filter_frequency', note_number, channel)
                if freq_block:
                    if isinstance(freq_block, synthio.LFO):
                        log(TAG_NOTE, f"  filter frequency controlled by LFO:")
                        log(TAG_NOTE, f"    rate: {freq_block.rate} Hz")
                        log(TAG_NOTE, f"    scale: {freq_block.scale}")
                        log(TAG_NOTE, f"    offset: {freq_block.offset}")
                        log(TAG_NOTE, f"    current value: {freq_block.value}")
                else:
                    # Use stored value if no block
                    freq_block = self.store.get('filter_frequency', channel, 500)
                
                q_block = self.modulation.get_block('filter_q', note_number, channel)
                if q_block:
                    if isinstance(q_block, synthio.LFO):
                        log(TAG_NOTE, f"  filter Q controlled by LFO:")
                        log(TAG_NOTE, f"    rate: {q_block.rate} Hz")
                        log(TAG_NOTE, f"    scale: {q_block.scale}")
                        log(TAG_NOTE, f"    offset: {q_block.offset}")
                        log(TAG_NOTE, f"    current value: {q_block.value}")
                else:
                    # Use stored value if no block
                    q_block = self.store.get('filter_q', channel, 0.707)
                
                # Create filter with blocks
                filter_obj = synthio.BlockBiquad(
                    mode=filter_mode,
                    frequency=freq_block,  # Block or value
                    Q=q_block  # Block or value
                )
                note_params['filter'] = filter_obj
                log(TAG_NOTE, f"Created {filter_type} filter with blocks")
                
            except AttributeError:
                log(TAG_NOTE, f"Unknown filter type: {filter_type}, skipping filter")
            except Exception as e:
                log(TAG_NOTE, f"Error creating filter: {str(e)}", is_error=True)
                
        # Override with provided params
        note_params.update(params)
        
        return note_params
        
    def press_note(self, note_number, frequency, channel, **params):
        """Create and press note with current parameters.
        
        Args:
            note_number: MIDI note number or unique identifier
            frequency: Note frequency in Hz
            channel: MIDI channel for parameter lookup
            **params: Additional parameters to override stored values
        """
        try:
            # Get existing note on this channel if any
            old_note = None
            if channel in self.channel_map:
                old_number = self.channel_map[channel]
                old_address = f"{old_number}.{channel}"
                old_note = self.notes.get(old_address)
                log(TAG_NOTE, f"Channel {channel} has existing note {old_number}")
                
            # Build note parameters
            note_params = self._build_note_params(note_number, frequency, channel, **params)
            
            # Log note creation
            log(TAG_NOTE, f"Creating note with frequency={format_value(frequency)}Hz")
            if 'filter' in note_params:
                filt = note_params['filter']
                log(TAG_NOTE, f"  filter: {filt.mode} freq={format_value(filt.frequency)} Q={format_value(filt.Q)}")
            if 'envelope' in note_params:
                env = note_params['envelope']
                log(TAG_NOTE, f"  envelope: attack={env.attack_time}s decay={env.decay_time}s release={env.release_time}s")
            if 'waveform' in note_params:
                log(TAG_NOTE, "Using waveform")
            
            # Create new note
            new_note = synthio.Note(**note_params)
            
            # Get blocks to retrigger
            retrigger_blocks = []
            for param in self.BLOCK_PARAMS:
                block = self.modulation.get_block(param, note_number, channel)
                if block and hasattr(block, 'retrigger'):
                    if isinstance(block, synthio.LFO) and block.once:
                        log(TAG_NOTE, f"Will retrigger one-shot LFO for {param}")
                        retrigger_blocks.append(block)
            
            # Perform atomic note change with retrigger
            self.synth.change(
                release=[old_note] if old_note else [],
                press=[new_note],
                retrigger=retrigger_blocks
            )
            
            # Update tracking after successful change
            if old_note:
                old_address = f"{old_number}.{channel}"
                del self.notes[old_address]
                # Clean up old note's blocks
                self.modulation.cleanup_note(old_number, channel)
                
            # Store new note
            address = f"{note_number}.{channel}"
            self.notes[address] = new_note
            self.channel_map[channel] = note_number
            
            log(TAG_NOTE, f"Pressed note {note_number} at {format_value(frequency)}Hz on channel {channel}")
            return True
            
        except Exception as e:
            log(TAG_NOTE, f"Error pressing note {note_number}: {str(e)}", is_error=True)
            return False
            
    def release_note(self, note_number, channel):
        """Release note and cleanup.
        
        Args:
            note_number: MIDI note number or unique identifier
            channel: MIDI channel
        """
        address = f"{note_number}.{channel}"
        if address in self.notes:
            try:
                note = self.notes[address]
                
                # Atomic release (change with no press)
                self.synth.change(release=[note])
                
                # Remove from tracking
                del self.notes[address]
                if channel in self.channel_map:
                    del self.channel_map[channel]
                    
                # Clean up note's blocks
                self.modulation.cleanup_note(note_number, channel)
                
                log(TAG_NOTE, f"Released note {note_number} on channel {channel}")
                return True
                
            except Exception as e:
                log(TAG_NOTE, f"Error releasing note {note_number}: {str(e)}", is_error=True)
                return False
        return False
        
    def update_note(self, note_number, channel, param_name=None, value=None):
        """Update note parameter.
        
        Args:
            note_number: MIDI note number or unique identifier
            channel: MIDI channel
            param_name: Optional param to update (None to update all)
            value: New value (None to get from store)
        """
        address = f"{note_number}.{channel}"
        if address not in self.notes:
            log(TAG_NOTE, f"Note {note_number} not found on channel {channel}", is_error=True)
            return False
            
        # Get note instance
        note = self.notes[address]
        
        # Update all parameters if none specified
        if param_name is None:
            # Update block parameters
            for param in self.BLOCK_PARAMS:
                log(TAG_NOTE, f"Getting block for {param}")
                block = self.modulation.get_block(param, note_number, channel)
                if block:
                    if isinstance(block, synthio.LFO):
                        log(TAG_NOTE, f"  {param} controlled by LFO:")
                        log(TAG_NOTE, f"    rate: {block.rate} Hz")
                        log(TAG_NOTE, f"    scale: {block.scale}")
                        log(TAG_NOTE, f"    offset: {block.offset}")
                        log(TAG_NOTE, f"    current value: {block.value}")
                    log(TAG_NOTE, f"  Using block for {param}: {type(block).__name__}")
                    setattr(note, param, block)
                    
            # Update value parameters
            for param in self.VALUE_PARAMS:
                value = self.store.get(param, channel)
                if value is not None:
                    if param == 'waveform':
                        log(TAG_NOTE, "Using waveform value")
                    else:
                        log(TAG_NOTE, f"Using value for {param}: {format_value(value)}")
                    setattr(note, param, value)
            return True
            
        # Handle single parameter update
        try:
            # Skip LFO parameter updates - handled by ModulationManager
            if param_name.startswith('lfo_'):
                return True
                
            # Handle block parameters
            if param_name in self.BLOCK_PARAMS:
                log(TAG_NOTE, f"Getting block for {param_name}")
                block = self.modulation.get_block(param_name, note_number, channel)
                if block:
                    if isinstance(block, synthio.LFO):
                        log(TAG_NOTE, f"  {param_name} controlled by LFO:")
                        log(TAG_NOTE, f"    rate: {block.rate} Hz")
                        log(TAG_NOTE, f"    scale: {block.scale}")
                        log(TAG_NOTE, f"    offset: {block.offset}")
                        log(TAG_NOTE, f"    current value: {block.value}")
                    log(TAG_NOTE, f"  Using block for {param_name}: {type(block).__name__}")
                    setattr(note, param_name, block)
                    log(TAG_NOTE, f"Updated {param_name} with block")
                    return True
                return False
            
            # Handle value parameters
            elif param_name in self.VALUE_PARAMS:
                if value is None:
                    value = self.store.get(param_name, channel)
                if value is not None:
                    if param_name == 'waveform':
                        log(TAG_NOTE, "Using waveform value")
                        setattr(note, param_name, value)
                        log(TAG_NOTE, f"Updated waveform for note {note_number}")
                    else:
                        log(TAG_NOTE, f"Using value for {param_name}: {format_value(value)}")
                        setattr(note, param_name, value)
                        log(TAG_NOTE, f"Updated {param_name}={format_value(value)} for note {note_number}")
                    return True
                return False
            
            log(TAG_NOTE, f"Parameter {param_name} cannot be updated", is_error=True)
            return False
            
        except Exception as e:
            log(TAG_NOTE, f"Error updating note {note_number}: {str(e)}", is_error=True)
            return False
            
    def release_all(self):
        """Release all active notes."""
        # Convert to list to avoid modifying dict during iteration
        for address in list(self.notes.keys()):
            note_number, channel = map(int, address.split("."))
            self.release_note(note_number, channel)
