"""State management for synth parameters."""

from logging import log, TAG_STORE, format_value

class SynthStore:
    """State management for synth parameters."""
    def __init__(self, synth=None):
        self._synth = synth
        # Initialize storage for each channel (1-15)
        self.values = {}
        self.previous_values = {}
        for channel in range(1, 16):
            self.values[channel] = {}
            self.previous_values[channel] = {}
            
        # Batch operations
        self._batch_store = False
        self._batch_channels = set()
        self._store_update_callback = None
        
    def begin_batch(self):
        """Start batch parameter storage."""
        self._batch_store = True
        self._batch_channels.clear()
        log(TAG_STORE, "Beginning batch parameter store")
        
    def end_batch(self, param_name=None):
        """End batch parameter storage."""
        self._batch_store = False
        if self._batch_channels:
            min_ch = min(self._batch_channels)
            max_ch = max(self._batch_channels)
            log(TAG_STORE, f"Stored {param_name} for channels {min_ch}-{max_ch}")
        self._batch_channels.clear()
        
        # Notify if callback registered
        if param_name and self._store_update_callback:
            self._store_update_callback(param_name)
            
    def set_update_callback(self, callback):
        """Set callback for parameter updates."""
        self._store_update_callback = callback
        
    def store(self, name, value, channel):
        """Store parameter value.
        
        Args:
            name: Parameter name
            value: Parameter value
            channel: MIDI channel (1-15)
        """
        if not 0 <= channel <= 15:
            log(TAG_STORE, f"Invalid channel {channel}", is_error=True)
            return
            
        # Channel 0 means write to all channels
        if channel == 0:
            for ch in range(1, 16):
                self.store(name, value, ch)
            return
            
        # Store previous value if it exists
        if name in self.values[channel]:
            self.previous_values[channel][name] = self.values[channel][name]
                
        # Store new value
        self.values[channel][name] = value
        
        # Track batch operations
        if self._batch_store:
            self._batch_channels.add(channel)
        else:
            # Log all envelope parameter storage
            if name.startswith('attack_') or name.startswith('decay_') or name.startswith('release_') or name.startswith('sustain_'):
                log(TAG_STORE, f"Stored envelope param {name}={format_value(value)} for channel {channel}")
            # Log other storage (only for channel 1 to avoid spam)
            elif channel == 1:
                if isinstance(value, (list, bytearray, memoryview)):
                    log(TAG_STORE, f"Stored {name} (waveform data)")
                else:
                    log(TAG_STORE, f"Stored {name}={format_value(value)}")
                
            # Notify if callback registered
            if self._store_update_callback:
                self._store_update_callback(name)
                
    def get(self, name, channel, default=None):
        """Get parameter value.
        
        Args:
            name: Parameter name
            channel: MIDI channel (1-15)
            default: Default value if parameter not found
            
        Returns:
            Parameter value
        """
        if not 0 <= channel <= 15:
            log(TAG_STORE, f"Invalid channel {channel}", is_error=True)
            return default
            
        # Channel 0 means read from channel 1 (global scope)
        if channel == 0:
            channel = 1
            
        value = self.values[channel].get(name, default)
        # Log envelope parameter retrieval
        if name.startswith('attack_') or name.startswith('decay_') or name.startswith('release_') or name.startswith('sustain_'):
            log(TAG_STORE, f"Retrieved envelope param {name}={format_value(value)} for channel {channel}")
        return value
        
    def get_previous(self, name, channel, default=None):
        """Get previous parameter value.
        
        Args:
            name: Parameter name
            channel: MIDI channel (1-15)
            default: Default value if no previous value
            
        Returns:
            Previous parameter value if it exists
        """
        if not 0 <= channel <= 15:
            log(TAG_STORE, f"Invalid channel {channel}", is_error=True)
            return default
            
        # Channel 0 means read from channel 1 (global scope)
        if channel == 0:
            channel = 1
            
        return self.previous_values[channel].get(name, default)
        
    def clear(self):
        """Clear all stored values."""
        for channel in range(1, 16):
            self.values[channel].clear()
            self.previous_values[channel].clear()
        self._store_update_callback = None
        log(TAG_STORE, "Cleared all stored values")
