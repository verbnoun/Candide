"""
Modulation System Management Module

This module provides advanced modulation capabilities for 
synthesizer parameters, enabling complex sound shaping and 
dynamic parameter manipulation.

Key Responsibilities:
- Implement sophisticated modulation algorithms
- Manage diverse modulation sources and destinations
- Apply time-varying transformations to synthesizer parameters
- Support multiple modulation types (LFO, envelope, etc.)
- Enable runtime configuration of modulation behavior

Primary Classes:
- ModulationSource: Base class for modulation sources
  * Defines common modulation source behavior
  * Supports configurable output ranges

- LFO (Low-Frequency Oscillator): 
  * Generates periodic waveform-based modulation
  * Supports multiple waveform shapes
  * Configurable rate, scale, and offset

- Envelope: 
  * Generates multi-stage dynamic parameter changes
  * Supports attack, decay, sustain, release stages
  * Handles gate-based triggering

- ModulationManager:
  * Creates and manages multiple modulation sources
  * Provides centralized configuration and update mechanism

Key Features:
- Dynamic waveform generation
- Flexible modulation routing
- Precise fixed-point value handling
- Configurable modulation sources
- Support for complex sound design techniques
"""
import array
import math
import synthio
from fixed_point_math import FixedPoint
from constants import Constants

class ModulationSource:
    """Base class for any config-defined modulation source"""
    def __init__(self, config):
        self.source_id = config.get('id')
        self.output_range = {
            'min': FixedPoint.from_float(config.get('range', {}).get('min', 0.0)),
            'max': FixedPoint.from_float(config.get('range', {}).get('max', 1.0))
        }
        self.current_value = FixedPoint.ZERO
        
    def get_value(self):
        """Get current output value"""
        return self.current_value
        
    def update(self):
        """Update state - override in subclasses"""
        pass

class LFO(ModulationSource):
    """Config-driven LFO"""
    def __init__(self, config, synth):
        super().__init__(config)
        
        # Create waveform
        if 'waveform' in config:
            self.waveform = self._create_waveform(config['waveform'])
        else:
            self.waveform = None  # Use synthio default
            
        # Create synthio LFO
        self.lfo = synthio.LFO(
            waveform=self.waveform,
            rate=config.get('rate', 1.0),
            scale=config.get('scale', 1.0),
            offset=config.get('offset', 0.0),
            phase_offset=config.get('phase_offset', 0.0),
            once=config.get('once', False),
            interpolate=config.get('interpolate', True)
        )
        
        # Add to synth blocks
        synth.blocks.append(self.lfo)
        
        if Constants.MOD_LFO_DEBUG:
            print(f"[LFO] Created: {self.source_id}")
            print(f"      Rate: {config.get('rate', 1.0)}Hz")
            print(f"      Scale: {config.get('scale', 1.0)}")
            print(f"      Offset: {config.get('offset', 0.0)}")
            
    def _create_waveform(self, config):
        """Create LFO waveform from config"""
        size = config.get('size', 32)  # Small size for LFOs
        shape = config.get('shape', 'sine')
        amp = 32767  # Full range for maximum resolution
        
        samples = array.array('h', [0] * size)
        
        if shape == 'sine':
            for i in range(size):
                angle = 2 * math.pi * i / size
                samples[i] = int(math.sin(angle) * amp)
                
        elif shape == 'triangle':
            half = size // 2
            for i in range(size):
                if i < half:
                    value = (i / half) * 2 - 1
                else:
                    value = 1 - ((i - half) / half) * 2
                samples[i] = int(value * amp)
                
        elif shape == 'ramp':
            for i in range(size):
                value = (i / size) * 2 - 1
                samples[i] = int(value * amp)
                
        elif shape == 'square':
            half = size // 2
            for i in range(size):
                samples[i] = amp if i < half else -amp
                
        return samples
        
    def update(self):
        """Get current LFO value"""
        if self.lfo:
            self.current_value = FixedPoint.from_float(self.lfo.value)
            
    def retrigger(self):
        """Reset LFO phase"""
        if self.lfo:
            self.lfo.retrigger()

class Envelope(ModulationSource):
    """Config-driven envelope generator"""
    def __init__(self, config):
        super().__init__(config)
        
        self.stages = config.get('stages', {})
        self.current_stage = None
        self.stage_start_time = 0
        self.stage_start_level = FixedPoint.ZERO
        self.stage_target_level = FixedPoint.ZERO
        self.gate_active = False
        
        if Constants.MOD_ENV_DEBUG:
            print(f"[ENV] Created: {self.source_id}")
            print(f"      Stages: {list(self.stages.keys())}")
            
    def _get_stage_duration(self, stage):
        """Get stage duration with any modulation"""
        if stage not in self.stages:
            return 0.0
            
        return self.stages[stage].get('time', 0.0)
        
    def _get_stage_level(self, stage):
        """Get stage target level with any modulation"""
        if stage not in self.stages:
            return FixedPoint.ZERO
            
        return FixedPoint.from_float(self.stages[stage].get('level', 0.0))
        
    def gate_on(self):
        """Start envelope"""
        self.gate_active = True
        self.current_stage = 'attack'
        self.stage_start_time = time.monotonic()
        self.stage_start_level = FixedPoint.ZERO
        self.stage_target_level = self._get_stage_level('attack')
        
        if Constants.MOD_ENV_DEBUG:
            print(f"[ENV] Gate on: {self.source_id}")
        
    def gate_off(self):
        """Start release"""
        if self.gate_active:
            self.gate_active = False
            self.current_stage = 'release'
            self.stage_start_time = time.monotonic()
            self.stage_start_level = self.current_value
            self.stage_target_level = FixedPoint.ZERO
            
            if Constants.MOD_ENV_DEBUG:
                print(f"[ENV] Gate off: {self.source_id}")
        
    def update(self):
        """Update envelope state"""
        if not self.current_stage:
            return
            
        current_time = time.monotonic()
        stage_time = current_time - self.stage_start_time
        stage_duration = self._get_stage_duration(self.current_stage)
        
        if stage_duration <= 0:
            # Instant change
            self.current_value = self.stage_target_level
            self._advance_stage()
            return
            
        # Calculate current level
        if stage_time >= stage_duration:
            self.current_value = self.stage_target_level
            self._advance_stage()
        else:
            # Linear interpolation
            progress = stage_time / stage_duration
            delta = self.stage_target_level - self.stage_start_level
            self.current_value = self.stage_start_level + FixedPoint.multiply(
                delta,
                FixedPoint.from_float(progress)
            )
        
    def _advance_stage(self):
        """Move to next stage if available"""
        if not self.current_stage:
            return
            
        if self.current_stage == 'attack':
            self._start_stage('decay')
        elif self.current_stage == 'decay':
            self._start_stage('sustain')
        elif self.current_stage == 'sustain' and not self.gate_active:
            self._start_stage('release')
        elif self.current_stage == 'release':
            self.current_stage = None
            
    def _start_stage(self, stage):
        """Start a new envelope stage"""
        if stage not in self.stages:
            return
            
        self.current_stage = stage
        self.stage_start_time = time.monotonic()
        self.stage_start_level = self.current_value
        self.stage_target_level = self._get_stage_level(stage)
        
        if Constants.MOD_ENV_DEBUG:
            print(f"[ENV] Stage change: {self.source_id}")
            print(f"      Stage: {stage}")
            print(f"      Target: {FixedPoint.to_float(self.stage_target_level):.3f}")

class ModulationManager:
    """Creates and manages modulation sources based on config"""
    def __init__(self, synth):
        self.synth = synth
        self.sources = {}  # source_id: ModulationSource
        
    def configure(self, config):
        """Create modulation sources from config"""
        if not config or 'modulation_sources' not in config:
            return
            
        # Clear existing
        self.sources.clear()
        
        # Create new sources
        for source_config in config['modulation_sources']:
            if 'type' not in source_config or 'id' not in source_config:
                continue
                
            try:
                if source_config['type'] == 'lfo':
                    source = LFO(source_config, self.synth)
                elif source_config['type'] == 'envelope':
                    source = Envelope(source_config)
                else:
                    continue
                    
                self.sources[source.source_id] = source
                
                if Constants.MOD_DEBUG:
                    print(f"[MOD] Created source: {source.source_id}")
                    print(f"      Type: {source_config['type']}")
                    
            except Exception as e:
                print(f"[ERROR] Failed to create source: {str(e)}")
                
    def get_source(self, source_id):
        """Get modulation source by ID"""
        return self.sources.get(source_id)
        
    def handle_gate(self, note_id, state):
        """Handle note gate events"""
        for source in self.sources.values():
            if isinstance(source, Envelope):
                if state:
                    source.gate_on()
                else:
                    source.gate_off()
                    
    def update(self):
        """Update all modulation sources"""
        for source in self.sources.values():
            source.update()
