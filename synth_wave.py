"""Wave and LFO management for synthesizer."""

import synthio
import array
import math
from logging import log, TAG_SYNTH, format_value

# Shared waveform cache
_WAVEFORM_CACHE = {}

class WaveManager:
    """Manages waveform creation and manipulation."""
    
    def __init__(self, store=None):
        self.store = store
        
    @staticmethod
    def midi_to_hz(note):
        """Convert MIDI note to frequency in Hz."""
        return synthio.midi_to_hz(note)
        
    def create_waveform(self, waveform_type, samples=64):
        """Create a waveform buffer.
        
        Args:
            waveform_type: Type of waveform ('sine', 'triangle', 'square', 'saw')
            samples: Number of samples in waveform
            
        Returns:
            array.array of signed 16-bit integers
        """
        cache_key = f"{waveform_type}_{samples}"
        if cache_key in _WAVEFORM_CACHE:
            return _WAVEFORM_CACHE[cache_key]
            
        buffer = array.array('h')
        
        try:
            if waveform_type == 'sine':
                for i in range(samples):
                    value = int(32767 * math.sin(2 * math.pi * i / samples))
                    buffer.append(value)
                    
            elif waveform_type == 'triangle':
                quarter = samples // 4
                for i in range(samples):
                    if i < quarter:  # Rising 0 to 1
                        value = i / quarter
                    elif i < 3 * quarter:  # Falling 1 to -1
                        value = 1 - 2 * (i - quarter) / (quarter * 2)
                    else:  # Rising -1 to 0
                        value = -1 + (i - 3 * quarter) / quarter
                    buffer.append(int(32767 * value))
                    
            elif waveform_type == 'square':
                half = samples // 2
                buffer.extend([32767] * half)
                buffer.extend([-32767] * (samples - half))
                
            elif waveform_type == 'saw':
                for i in range(samples):
                    value = int(32767 * (2 * i / samples - 1))
                    buffer.append(value)
                    
            else:
                raise ValueError(f"Unknown waveform type: {waveform_type}")
                
            _WAVEFORM_CACHE[cache_key] = buffer
            return buffer
            
        except Exception as e:
            log(TAG_SYNTH, f"Error creating waveform: {str(e)}", is_error=True)
            raise
            
    def create_morphed_waveform(self, waveform_sequence, morph_position, samples=64):
        """Create a morphed waveform between sequence of waveforms.
        
        Args:
            waveform_sequence: List of waveform types to morph between
            morph_position: Position in morph sequence (0-1)
            samples: Number of samples in output waveform
            
        Returns:
            array.array of morphed waveform
        """
        try:
            num_transitions = len(waveform_sequence) - 1
            if num_transitions == 0:
                return self.create_waveform(waveform_sequence[0], samples)
                
            scaled_pos = morph_position * num_transitions
            transition_index = int(scaled_pos)
            
            if transition_index >= num_transitions:
                return self.create_waveform(waveform_sequence[-1], samples)
            
            # Get or create source waveforms
            waveform1 = self.create_waveform(waveform_sequence[transition_index], samples)
            waveform2 = self.create_waveform(waveform_sequence[transition_index + 1], samples)
            
            # Calculate interpolation factor
            t = scaled_pos - transition_index
            
            # Create morphed waveform
            morphed = array.array('h')
            for i in range(samples):
                value = int(waveform1[i] * (1-t) + waveform2[i] * t)
                morphed.append(value)
            
            return morphed
            
        except Exception as e:
            log(TAG_SYNTH, f"Error creating morphed waveform: {str(e)}", is_error=True)
            raise


class LFOManager:
    """Manages named LFOs and their routing."""
    
    def __init__(self, store):
        self.store = store
        self.wave_manager = WaveManager()
            
    def update_lfo(self, lfo, param, value):
        """Update LFO parameter at runtime.
        
        Args:
            lfo: synthio.LFO object to update
            param: Parameter name to update
            value: New value (already converted to proper type by router)
        """
        try:
            if hasattr(lfo, param):
                setattr(lfo, param, value)
                log(TAG_SYNTH, f"Updated LFO {param}={format_value(value)}")
            else:
                log(TAG_SYNTH, f"LFO has no parameter {param}", is_error=True)
        except Exception as e:
            log(TAG_SYNTH, f"Error updating LFO parameter {param}: {str(e)}", is_error=True)
            
    def create_lfo(self, name, **params):
        """Create and register named LFO.
        
        Args:
            name: Unique name for the LFO
            **params: Parameters for synthio.LFO from paths
        """
        try:
            # Check if block already exists
            if self.store.get_block(name):
                log(TAG_SYNTH, f"Block {name} already exists", is_error=True)
                return
                
            # Create LFO with params
            try:
                # Create default sine waveform if none provided
                if 'waveform' not in params:
                    params['waveform'] = self.wave_manager.create_waveform('sine')
                # Convert waveform type to buffer if string
                elif isinstance(params['waveform'], str):
                    params['waveform'] = self.wave_manager.create_waveform(params['waveform'])
                
                lfo = synthio.LFO(**params)
                log(TAG_SYNTH, f"Created LFO {name} with params: {params}")
                return lfo
            except Exception as e:
                log(TAG_SYNTH, f"Error creating LFO {name}: {str(e)}", is_error=True)
                raise
            
        except Exception as e:
            log(TAG_SYNTH, f"Error creating LFO {name}: {str(e)}", is_error=True)
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
            if self.store.get_block(name):
                log(TAG_SYNTH, f"Block {name} already exists", is_error=True)
                return
                
            # Create Math block (inputs already converted to blocks by router)
            math = synthio.Math(
                operation=operation,
                a=a,
                b=b,
                c=c
            )
            
            # Store block
            self.store.store_block(name, math)
            log(TAG_SYNTH, f"Created Math block {name}")
            
            return math
            
        except Exception as e:
            log(TAG_SYNTH, f"Error creating Math block: {str(e)}", is_error=True)
            raise
            
    def route_block(self, block_name, target_param):
        """Route block output to parameter.
        
        Args:
            block_name: Name of block to route
            target_param: Parameter to route block to
        """
        try:
            block = self.store.get_block(block_name)
            if not block:
                log(TAG_SYNTH, f"Block {block_name} not found", is_error=True)
                return False
                
            # Update routing
            self.store.lfo_routes[target_param] = block_name  # Using existing route storage
            log(TAG_SYNTH, f"Routed block {block_name} to {target_param}")
            return True
            
        except Exception as e:
            log(TAG_SYNTH, f"Error routing block: {str(e)}", is_error=True)
            return False
            
    def unroute_param(self, target_param):
        """Remove block routing from parameter.
        
        Args:
            target_param: Parameter to unroute
        """
        if target_param in self.store.lfo_routes:
            block_name = self.store.lfo_routes[target_param]
            del self.store.lfo_routes[target_param]
            log(TAG_SYNTH, f"Unrouted block {block_name} from {target_param}")
            
    def remove_block(self, name):
        """Remove block and its routes.
        
        Args:
            name: Name of block to remove
        """
        block = self.store.get_block(name)
        if block:
            # Remove routes using this block
            routes_to_remove = []
            for param, block_name in self.store.lfo_routes.items():
                if block_name == name:
                    routes_to_remove.append(param)
            
            for param in routes_to_remove:
                del self.store.lfo_routes[param]
                
            # Remove block
            if name in self.store.lfos:  # Backward compatibility
                del self.store.lfos[name]
            if name in self.store.blocks:
                del self.store.blocks[name]
                
            log(TAG_SYNTH, f"Removed block {name} and its routes")
