"""Block modulation management for synthesizer."""

import synthio
from logging import log, TAG_MOD, format_value

class ModulationManager:
    """Manages all synthio block creation, routing and lifecycle."""
    
    def __init__(self, synth):
        self.synth = synth
        self.blocks = {}  # name -> synthio.BlockInput
        self.prototypes = {}  # name -> dict of creation parameters
        self.chains = {}  # target_param -> source_block_name
        self.note_blocks = {}  # (note_num, channel) tuple -> dict mapping names to per-note block instances
        self.active_scopes = {}  # name -> bool tracking if block is global or per-note
        self.wave_manager = None  # Set when needed for waveform creation
        
    def determine_block_scope(self, name, path_config):
        """Determine if block should be global or per-note.
        
        Args:
            name: Block identifier
            path_config: Router path configuration
            
        Returns:
            True if block should be global, False if per-note
        """
        # Make one-shot LFOs per-note by default
        if name in self.prototypes:
            proto = self.prototypes[name]
            if proto['type'] == 'lfo' and proto['params'].get('once'):
                log(TAG_MOD, f"Block {name} is one-shot LFO, making per-note")
                return False
        
        # Check if any paths modify this block's parameters per-note
        paths = path_config.get_paths_for_block(name)
        return not any(p.scope == 'channel' for p in paths)
        
    def create_lfo(self, name, **params):
        """Create and register named LFO.
        
        Args:
            name: Unique name for the LFO
            **params: Parameters for synthio.LFO from paths
        """
        try:
            # Check if block already exists
            if name in self.blocks:
                log(TAG_MOD, f"Block {name} already exists", is_error=True)
                return None
                
            # Store prototype for per-note instances
            self.prototypes[name] = {
                'type': 'lfo',
                'params': params.copy()
            }
                
            # Create LFO with params
            try:
                # Handle waveform parameter
                if 'waveform' not in params:
                    if not self.wave_manager:
                        from synth_wave import WaveManager
                        self.wave_manager = WaveManager()
                    params['waveform'] = self.wave_manager.create_waveform('sine')
                elif isinstance(params['waveform'], str):
                    if not self.wave_manager:
                        from synth_wave import WaveManager
                        self.wave_manager = WaveManager()
                    params['waveform'] = self.wave_manager.create_waveform(params['waveform'])
                
                # Create LFO
                lfo = synthio.LFO(**params)
                self.blocks[name] = lfo
                log(TAG_MOD, f"Created LFO {name}:")
                log(TAG_MOD, f"  rate: {params.get('rate', 1.0)} Hz")
                log(TAG_MOD, f"  scale: {params.get('scale', 1.0)}")
                log(TAG_MOD, f"  offset: {params.get('offset', 0.0)}")
                if 'waveform' in params:
                    log(TAG_MOD, "  waveform: set")
                log(TAG_MOD, f"  once: {params.get('once', False)}")
                log(TAG_MOD, f"  interpolate: {params.get('interpolate', True)}")
                return lfo
                
            except Exception as e:
                log(TAG_MOD, f"Error creating LFO {name}: {str(e)}", is_error=True)
                raise
            
        except Exception as e:
            log(TAG_MOD, f"Error creating LFO {name}: {str(e)}", is_error=True)
            raise
            
    def create_math_block(self, name, operation, a, b=0.0, c=1.0):
        """Create a named Math block.
        
        Args:
            name: Unique name for the Math block
            operation: synthio.MathOperation value
            a: First input (value, block name, or block)
            b: Second input (value, block name, or block)
            c: Third input (value, block name, or block)
        """
        try:
            # Check if block already exists
            if name in self.blocks:
                log(TAG_MOD, f"Block {name} already exists", is_error=True)
                return None
                
            # Store prototype for per-note instances
            self.prototypes[name] = {
                'type': 'math',
                'params': {
                    'operation': operation,
                    'a': a,
                    'b': b,
                    'c': c
                }
            }
                
            # Create Math block
            math = synthio.Math(
                operation=operation,
                a=a,
                b=b,
                c=c
            )
            
            self.blocks[name] = math
            log(TAG_MOD, f"Created Math block {name}")
            return math
            
        except Exception as e:
            log(TAG_MOD, f"Error creating Math block: {str(e)}", is_error=True)
            raise
            
    def create_filter(self, name, mode, frequency, Q=0.707):
        """Create a filter block.
        
        Args:
            name: Filter block name
            mode: Filter mode (LOW_PASS, HIGH_PASS, etc)
            frequency: Frequency value or block
            Q: Q value or block
        """
        try:
            # Check if block already exists
            if name in self.blocks:
                log(TAG_MOD, f"Block {name} already exists", is_error=True)
                return None
                
            # Store prototype for per-note instances
            self.prototypes[name] = {
                'type': 'filter',
                'params': {
                    'mode': mode,
                    'frequency': frequency,
                    'Q': Q
                }
            }
                
            # Create filter
            filter = synthio.BlockBiquad(mode=mode, frequency=frequency, Q=Q)
            self.blocks[name] = filter
            log(TAG_MOD, f"Created {mode} filter block {name}")
            return filter
            
        except Exception as e:
            log(TAG_MOD, f"Error creating filter block: {str(e)}", is_error=True)
            raise
            
    def get_block(self, name, note_num=None, channel=None):
        """Get a block by name, creating per-note instance if needed.
        
        Args:
            name: Block identifier
            note_num: Note number for per-note blocks
            channel: MIDI channel for per-note blocks
            
        Returns:
            Block instance
        """
        # Check if parameter is routed to a block
        if name in self.chains:
            log(TAG_MOD, f"Looking up block for parameter: {name}")
            log(TAG_MOD, f"Current routing table: {self.chains}")
            source_name = self.chains[name]
            log(TAG_MOD, f"Found routing: {name} -> {source_name}")
            
            block = self.blocks.get(source_name)
            if block:
                # Add to synth blocks for updates if not already there
                if block not in self.synth.synth.blocks:
                    self.synth.synth.blocks.append(block)
                    log(TAG_MOD, f"Added block {source_name} to synth blocks")
                log(TAG_MOD, f"Found routed block for {name}:")
                log(TAG_MOD, f"  Source: {source_name}")
                log(TAG_MOD, f"  Type: {type(block).__name__}")
                if isinstance(block, synthio.LFO):
                    log(TAG_MOD, f"  LFO rate: {block.rate} Hz")
                    log(TAG_MOD, f"  LFO scale: {block.scale}")
                    log(TAG_MOD, f"  LFO offset: {block.offset}")
                    log(TAG_MOD, f"  Current value: {block.value}")
                return block
            else:
                log(TAG_MOD, f"Warning: Block {source_name} not found for {name}")
                return None
                
        # Return global block if it exists and is global scope
        if name in self.blocks and self.active_scopes.get(name, True):
            block = self.blocks[name]
            # Add to synth blocks for updates if not already there
            if block not in self.synth.synth.blocks:
                self.synth.synth.blocks.append(block)
                log(TAG_MOD, f"Added block {name} to synth blocks")
            log(TAG_MOD, f"Found global block for {name}:")
            log(TAG_MOD, f"  Type: {type(block).__name__}")
            return block
            
        # Handle per-note blocks
        if note_num is not None and channel is not None:
            note_key = (note_num, channel)
            
            # Create note dict if needed
            if note_key not in self.note_blocks:
                self.note_blocks[note_key] = {}
                
            # Return existing note block if it exists
            if name in self.note_blocks[note_key]:
                return self.note_blocks[note_key][name]
                
            # Create new note block from prototype
            if name in self.prototypes:
                proto = self.prototypes[name]
                if proto['type'] == 'lfo':
                    block = self.create_lfo(f"{name}_{note_num}_{channel}", 
                                          **proto['params'])
                elif proto['type'] == 'math':
                    block = self.create_math_block(f"{name}_{note_num}_{channel}",
                                                 **proto['params'])
                elif proto['type'] == 'filter':
                    block = self.create_filter(f"{name}_{note_num}_{channel}",
                                            **proto['params'])
                                            
                if block:
                    # Add to synth blocks for updates if not already there
                    if block not in self.synth.synth.blocks:
                        self.synth.synth.blocks.append(block)
                        log(TAG_MOD, f"Added per-note block {name} to synth blocks")
                    self.note_blocks[note_key][name] = block
                    return block
                
        # No block found - this is expected for non-modulated parameters
        return None
        
    def update_block(self, name, param, value):
        """Update block parameter.
        
        Args:
            name: Block identifier
            param: Parameter name
            value: New value
            
        Returns:
            True if update succeeded
        """
        block = self.blocks.get(name)
        if not block:
            log(TAG_MOD, f"Error: Block {name} not found", is_error=True)
            return False
            
        try:
            # Update block parameter
            setattr(block, param, value)
            log(TAG_MOD, f"Updated block {name} {param}={format_value(value)}")
            
            # Update prototype if exists
            if name in self.prototypes:
                self.prototypes[name]['params'][param] = value
                
            # Update any per-note instances
            for blocks in self.note_blocks.values():
                if name in blocks:
                    setattr(blocks[name], param, value)
                    
            return True
            
        except Exception as e:
            log(TAG_MOD, f"Error updating block parameter: {str(e)}", is_error=True)
            return False
                
    def route_block(self, source_name, target_param):
        """Route block output to parameter.
        
        Args:
            source_name: Name of source block
            target_param: Parameter to route block to
            
        Returns:
            True if routing succeeded, False if block not found
        """
        log(TAG_MOD, f"Attempting to route {source_name} to {target_param}")
        if source_name in self.blocks:
            block = self.blocks[source_name]
            # Set up routing
            self.chains[target_param] = source_name
            # Add to synth blocks for updates if not already there
            if block not in self.synth.synth.blocks:
                self.synth.synth.blocks.append(block)
                log(TAG_MOD, f"Added block {source_name} to synth blocks")
            log(TAG_MOD, f"Set up new routing: {target_param} -> {source_name}")
            log(TAG_MOD, f"Updated routing table: {self.chains}")
            log(TAG_MOD, f"Routed block {source_name} to {target_param}:")
            if isinstance(block, synthio.LFO):
                log(TAG_MOD, f"  LFO rate: {block.rate} Hz")
                log(TAG_MOD, f"  LFO scale: {block.scale}")
                log(TAG_MOD, f"  LFO offset: {block.offset}")
                log(TAG_MOD, f"  Current value: {block.value}")
            return True
        return False
        
    def unroute_param(self, target_param):
        """Remove block routing from parameter."""
        if target_param in self.chains:
            source = self.chains[target_param]
            del self.chains[target_param]
            log(TAG_MOD, f"Unrouted block {source} from {target_param}")
            
    def cleanup_note(self, note_num, channel):
        """Clean up per-note blocks when note is released."""
        note_key = (note_num, channel)
        if note_key in self.note_blocks:
            del self.note_blocks[note_key]
            
    def cleanup(self):
        """Clean up all blocks."""
        self.blocks.clear()
        self.prototypes.clear()
        self.chains.clear()
        self.note_blocks.clear()
        self.active_scopes.clear()
