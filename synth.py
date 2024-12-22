"""Main synthesizer coordinator using direct synthio integration."""

import synthio
from constants import SAMPLE_RATE, AUDIO_CHANNEL_COUNT, MAX_NOTES
from logging import log, TAG_SYNTH, format_value

from synth_store import SynthStore
from synth_wave import WaveManager
from synth_note import NoteManager
from modulation import ModulationManager

class Synthesizer:
    """Main synthesizer coordinator using direct synthio integration."""
    def __init__(self, audio_system=None, waveform=None, envelope=None):
        try:
            self.synth = synthio.Synthesizer(
                sample_rate=SAMPLE_RATE,
                channel_count=AUDIO_CHANNEL_COUNT,
                waveform=waveform,
                envelope=envelope
            )
            log(TAG_SYNTH, f"Created synthio synthesizer: {SAMPLE_RATE}Hz, {AUDIO_CHANNEL_COUNT} channels")
            
            if audio_system and hasattr(audio_system, 'mixer'):
                audio_system.mixer.voice[0].play(self.synth)
                log(TAG_SYNTH, "Connected synthesizer to audio mixer")
            
            self.store = SynthStore(self)
            self.wave_manager = WaveManager(self.store)
            self.modulation = ModulationManager(self)
            self.note_manager = NoteManager(self.synth, self.store, self.modulation)
            self._active = True
            
            # Track blocks that run even without notes
            self.blocks = self.synth.blocks
            
            # Set up block update callback
            self.modulation.on_update = self.handle_block_update
            
            # Add update timer
            self.update_timer = 0
            self.UPDATE_INTERVAL = 256  # Update every 256 samples
            
            log(TAG_SYNTH, "Synthesizer initialization complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Failed to initialize synthesizer: {str(e)}", is_error=True)
            self._active = False
            raise

    def get_note_state(self, note):
        """Get note's envelope state and value.
        
        Args:
            note: Note to check state for
            
        Returns:
            Tuple of (EnvelopeState, float) or (None, 0.0) if not playing
        """
        return self.synth.note_info(note)

    @property
    def pressed_notes(self):
        """Get currently pressed notes (not including release phase)."""
        return self.synth.pressed

    def low_pass(self, frequency, Q=0.707):
        """Create low-pass filter."""
        return self.synth.low_pass_filter(frequency, Q)
        
    def high_pass(self, frequency, Q=0.707):
        """Create high-pass filter."""
        return self.synth.high_pass_filter(frequency, Q)
        
    def band_pass(self, frequency, Q=0.707):
        """Create band-pass filter."""
        return self.synth.band_pass_filter(frequency, Q)
        
    def notch(self, frequency, Q=0.707):
        """Create notch filter."""
        return self.synth.notch_filter(frequency, Q)

    def create_waveform(self, waveform_type, samples=64):
        """Create a waveform buffer.
        
        Args:
            waveform_type: Type of waveform ('sine', 'triangle', 'square', 'saw')
            samples: Number of samples in waveform
        """
        return self.wave_manager.create_waveform(waveform_type, samples)
        
    def create_morphed_waveform(self, waveform_sequence, morph_position, samples=64):
        """Create a morphed waveform between sequence of waveforms.
        
        Args:
            waveform_sequence: List of waveform types to morph between
            morph_position: Position in morph sequence (0-1)
            samples: Number of samples in output waveform
        """
        return self.wave_manager.create_morphed_waveform(waveform_sequence, morph_position, samples)
        
    def midi_to_hz(self, note):
        """Convert MIDI note to frequency in Hz."""
        return self.wave_manager.midi_to_hz(note)

    def create_lfo(self, name, waveform_type='sine', **params):
        """Create a named LFO block.
        
        Args:
            name: Unique name for the block
            waveform_type: Type of waveform to use
            **params: LFO parameters including:
                rate: Oscillation rate in Hz
                scale: Output scale factor
                offset: Output offset
                phase_offset: Phase offset 0-1
                once: Run once then stop
                interpolate: Interpolate between samples
        """
        return self.modulation.create_lfo(name, waveform_type=waveform_type, **params)

    def press_note(self, note_number, frequency, channel):
        if not self._active:
            return False
        return self.note_manager.press_note(note_number, frequency, channel)
        
    def release_note(self, note_number, channel):
        if not self._active:
            return False
        return self.note_manager.release_note(note_number, channel)

    def create_math(self, name, operation, a, b=0.0, c=1.0):
        return self.modulation.create_math_block(name, operation, a, b, c)

    def create_filter(self, name, mode, frequency, Q=0.707):
        """Create a filter block.
        
        Args:
            name: Filter block name
            mode: Filter mode (LOW_PASS, HIGH_PASS, etc)
            frequency: Frequency value or block (already converted by router)
            Q: Q value or block (already converted by router)
        """
        return self.modulation.create_filter(name, mode, frequency, Q)

    def route_block(self, block_name, target_param):
        return self.modulation.route_block(block_name, target_param)

    def unroute_param(self, target_param):
        self.modulation.unroute_param(target_param)

    def add_free_block(self, block_name):
        block = self.modulation.get_block(block_name)
        if block and block not in self.blocks:
            self.blocks.append(block)
            log(TAG_SYNTH, f"Added {block_name} to free-running blocks")
            # Force initial update
            self.modulation.update_blocks()

    def remove_free_block(self, block_name):
        block = self.modulation.get_block(block_name)
        if block in self.blocks:
            self.blocks.remove(block)
            log(TAG_SYNTH, f"Removed {block_name} from free-running blocks")

    def retrigger_blocks(self, block_names):
        if isinstance(block_names, str):
            block_names = [block_names]
            
        blocks = []
        for name in block_names:
            block = self.modulation.get_block(name)
            if block and hasattr(block, 'retrigger'):
                blocks.append(block)
                
        if blocks:
            self.atomic_change(retrigger=blocks)

    def atomic_change(self, release=None, press=None, retrigger=None):
        try:
            self.synth.change(
                release=[] if release is None else release,
                press=[] if press is None else press,
                retrigger=[] if retrigger is None else retrigger
            )
            log(TAG_SYNTH, "Performed atomic change")
        except Exception as e:
            log(TAG_SYNTH, f"Error in atomic change: {str(e)}", is_error=True)
            
    def update(self):
        """Update blocks and notes."""
        # Update store with current block values
        self.modulation.update_blocks()
        # Update all active notes with new values
        for ch, note_number in self.note_manager.channel_map.items():
            self.note_manager.update_note(note_number, ch)
                
    def handle_block_update(self):
        """Called when blocks need updating."""
        # Update store with current block values
        self.modulation.update_blocks()
        # Update all active notes with new values
        for ch, note_number in self.note_manager.channel_map.items():
            self.note_manager.update_note(note_number, ch)
            
    def handle_value(self, name, value, channel):
        if not self._active:
            log(TAG_SYNTH, "Synthesizer not active", is_error=True)
            return
            
        try:
            # Store value first (unless it's an LFO target or parameter since those are handled differently)
            if not (name.startswith('lfo_target_') or name.startswith('lfo_')):
                self.store.store(name, value, channel)
            
            # Handle LFO parameter updates
            if name.startswith('lfo_'):
                # Extract LFO name and parameter
                parts = name.split('_', 2)  # lfo_param_name
                if len(parts) == 3:
                    param = parts[1]  # rate, scale, offset etc
                    lfo_name = parts[2]  # tremolo etc
                    # Update LFO parameter (this triggers update_blocks via callback)
                    if not self.modulation.update_block(lfo_name, param, value):
                        log(TAG_SYNTH, f"Failed to update LFO {lfo_name} {param}", is_error=True)
                        return
                    log(TAG_SYNTH, f"Updated LFO {lfo_name} {param}={format_value(value)}")
            
            # Handle block-related operations
            if name.startswith('lfo_setup_'):
                # Handle LFO setup info
                lfo_setup = value
                lfo_name = lfo_setup['name']
                
                # Convert string representation back to tuple list
                steps_str = lfo_setup['steps'].strip('[]')  # Remove outer brackets
                steps = []
                # Basic string parsing - expects format like: ('create', {...}), ('route', ...)
                for step_str in steps_str.split('),'):
                    if not step_str.strip(): 
                        continue
                    # Clean up string and evaluate as tuple
                    step_str = step_str.strip('() ')
                    step_type, params_str = step_str.split(',', 1)
                    step_type = step_type.strip("' ")
                    
                    # Parse parameters
                    if step_type == 'create':
                        # Convert string dict to actual dict and convert numeric values
                        params_dict = eval(params_str)  # Safe here since we control input
                        for k, v in params_dict.items():
                            try:
                                params_dict[k] = float(v)
                            except (ValueError, TypeError):
                                pass  # Keep non-numeric values as is
                        params = params_dict
                    else:
                        params = params_str.strip("' ")
                        
                    steps.append((step_type, params))
                
                # Now process the parsed steps
                for step, params in steps:
                    if step == 'create':
                        # Create LFO with params
                        waveform_type = 'sine'  # Default waveform
                        if 'waveform' in params:
                            waveform_info = params['waveform']['value']
                            if isinstance(waveform_info, dict) and waveform_info['type'] == 'waveform':
                                waveform_type = waveform_info['name']
                            del params['waveform']
                            
                        # Create LFO with params
                        lfo = self.modulation.create_lfo(lfo_name, waveform_type=waveform_type, **params)
                        if lfo:
                            # Add to free-running blocks
                            self.add_free_block(lfo_name)
                            # Force initial update
                            self.modulation.update_blocks()
                            log(TAG_SYNTH, f"Created and started LFO {lfo_name}")
                            
                    elif step == 'route':
                        # Route LFO to target
                        target = params
                        if ':' in target:  # Handle filter targets
                            param, filter_type = target.split(':')
                            # Create filter if needed
                            filter_name = f"filter_{lfo_name}"
                            if filter_name not in self.modulation.blocks:
                                self.modulation.create_filter(filter_name, filter_type, 0)
                            # Route LFO to filter frequency
                            if not self.modulation.route_block(lfo_name, param):
                                log(TAG_SYNTH, f"Failed to route LFO {lfo_name} to {param}", is_error=True)
                                return
                        else:
                            # Direct parameter routing
                            if not self.modulation.route_block(lfo_name, target):
                                log(TAG_SYNTH, f"Failed to route LFO {lfo_name} to {target}", is_error=True)
                                return
                        log(TAG_SYNTH, f"Routed LFO {lfo_name} to {target}")
                        
            elif name.startswith('route_'):
                parts = name.split('_', 1)
                if len(parts) == 2:
                    target_param = parts[1]
                    if value:
                        self.route_block(value, target_param)
                    else:
                        self.unroute_param(target_param)
                        
            elif name.startswith('block_'):
                parts = name.split('_', 1)
                if len(parts) == 2:
                    block_name = parts[1]
                    if value:
                        self.add_free_block(block_name)
                    else:
                        self.remove_free_block(block_name)
                        
            # Update notes if needed
            if channel == 0:
                # Update all active notes
                for ch, note_number in self.note_manager.channel_map.items():
                    self.note_manager.update_note(note_number, ch, name, value)
            elif channel in self.note_manager.channel_map:
                # Update specific channel note
                note_number = self.note_manager.channel_map[channel]
                self.note_manager.update_note(note_number, channel, name, value)
                        
        except Exception as e:
            log(TAG_SYNTH, f"Error handling value {name}: {str(e)}", is_error=True)
            
    def cleanup(self):
        if not self._active:
            return
            
        try:
            if hasattr(self, 'note_manager'):
                self.note_manager.release_all()
            
            if hasattr(self, 'store'):
                self.store.clear()
                self.store = None
                
            if hasattr(self, 'modulation'):
                self.modulation.cleanup()
                self.modulation = None
                
            self.blocks.clear()
                
            if hasattr(self, 'synth'):
                self.synth.deinit()
                self.synth = None
                
            self._active = False
            log(TAG_SYNTH, "Synthesizer cleanup complete")
            
        except Exception as e:
            log(TAG_SYNTH, f"Error during cleanup: {str(e)}", is_error=True)
            
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        
    @property
    def max_polyphony(self):
        return MAX_NOTES if self._active else 0
        
    @property
    def sample_rate(self):
        return SAMPLE_RATE if self._active else 0
        
    @property
    def channel_count(self):
        return AUDIO_CHANNEL_COUNT if self._active else 0
