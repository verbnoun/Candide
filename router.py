"""
Module-specific routing system for synthesizer parameters with advanced validation
and value processing capabilities.
"""

import sys
from fixed_point_math import FixedPoint
from constants import ROUTER_DEBUG

def _format_log_message(message):
    """Format a dictionary message for console logging with specific indentation rules."""
    if not isinstance(message, (dict, list)):
        return str(message)
        
    # Handle non-recursive cases first
    if isinstance(message, dict) and not message:
        return '{}'
    if isinstance(message, list) and not message:
        return '[]'
        
    # Convert to simple string representation for complex objects
    try:
        if isinstance(message, dict):
            items = []
            for k, v in message.items():
                if isinstance(v, (dict, list)):
                    items.append(f"'{k}': {...}")
                else:
                    items.append(f"'{k}': {v}")
            return '{' + ', '.join(items) + '}'
        elif isinstance(message, list):
            return '[...]'
    except Exception:
        return str(message)
    
    return str(message)

def _log(message, module="ROUTER"):
    """Conditional logging function that respects ROUTER_DEBUG flag."""
    if not ROUTER_DEBUG:
        return
        
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    RESET = "\033[0m"
    
    if isinstance(message, dict):
        formatted = _format_log_message(message)
        print(f"{BLUE}[{module}] {formatted}{RESET}", file=sys.stderr)
    else:
        if "[ERROR]" in str(message):
            color = RED
        elif "[SUCCESS]" in str(message):
            color = GREEN
        elif "[WARNING]" in str(message):
            color = YELLOW
        else:
            color = BLUE
        print(f"{color}[{module}] {message}{RESET}", file=sys.stderr)

class ModuleRouter:
    """Base class for module routing with advanced processing capabilities"""
    def __init__(self, config=None):
        self.config = config
        self.module_name = "BASE"
        
    def set_config(self, config):
        """Update module configuration"""
        self.config = config
        _log(f"Configuration updated", self.module_name)
        # Don't log full config, just indicate it was set
        _log(f"Config size: {len(str(config))}", self.module_name)
        
    def get_module_config(self):
        """Get module-specific configuration"""
        return self.config.get(self.module_name) if self.config else None
        
    def transform_value(self, value, transform_config):
        """Advanced value transformation with curves and ranges"""
        if not transform_config:
            return value
            
        # Convert to FixedPoint if needed
        if not isinstance(value, FixedPoint):
            value = FixedPoint.from_float(float(value))
        
        # Range mapping
        if 'range' in transform_config:
            r = transform_config['range']
            in_min = r.get('in_min', 0)
            in_max = r.get('in_max', 127)
            out_min = FixedPoint.from_float(r.get('out_min', 0.0))
            out_max = FixedPoint.from_float(r.get('out_max', 1.0))
            
            # Normalize to 0-1
            if in_max != in_min:
                value = FixedPoint.from_float(
                    (float(value) - in_min) / (in_max - in_min)
                )
                
            # Scale to output range
            range_size = out_max - out_min
            value = out_min + FixedPoint.multiply(value, range_size)
        
        # Apply curve
        curve = transform_config.get('curve', 'linear')
        if curve == 'exponential':
            value = FixedPoint.multiply(value, value)
        elif curve == 'logarithmic':
            value = FixedPoint.ONE - FixedPoint.multiply(
                FixedPoint.ONE - value,
                FixedPoint.ONE - value
            )
        elif curve == 's_curve':
            x2 = FixedPoint.multiply(value, value)
            x3 = FixedPoint.multiply(x2, value)
            value = FixedPoint.multiply(x2, FixedPoint.from_float(3.0)) - \
                   FixedPoint.multiply(x3, FixedPoint.from_float(2.0))
        
        # Apply amount if specified
        if 'amount' in transform_config:
            amount = FixedPoint.from_float(transform_config['amount'])
            value = FixedPoint.multiply(value, amount)
            
        return value
        
    def extract_source_value(self, message, source_config):
        """Extract and validate source values from messages"""
        msg_type = message.get('type')
        data = message.get('data', {})
        
        source_type = source_config.get('type')
        attribute = source_config.get('attribute')
        
        if source_type == 'per_key':
            if msg_type == 'note_on':
                if attribute == 'velocity':
                    return data.get('velocity', 0)
                elif attribute == 'note':
                    if source_config.get('transform') == 'midi_to_frequency':
                        return FixedPoint.midi_note_to_fixed(data.get('note', 0))
                    return data.get('note', 0)
            elif msg_type == 'note_off':
                if attribute == 'trigger':
                    return 0
                    
        elif source_type == 'cc':
            if (msg_type == 'cc' and 
                data.get('number') == source_config.get('number')):
                return data.get('value', 0)
                
        return None
        
    def validate_message(self, message):
        """Base message validation with detailed checking"""
        module_config = self.get_module_config()
        if not module_config:
            return False
            
        msg_type = message.get('type')
        data = message.get('data', {})
        
        # Check parameters and their sources
        parameters = module_config.get('parameters', {})
        for param_name, param_config in parameters.items():
            sources = param_config.get('sources', [])
            for source in sources:
                if self._matches_source(message, source):
                    return True
                    
        return False
        
    def _matches_source(self, message, source_config):
        """Detailed source matching logic"""
        msg_type = message.get('type')
        data = message.get('data', {})
        
        source_type = source_config.get('type')
        
        if source_type == 'per_key':
            if msg_type in ['note_on', 'note_off']:
                attribute = source_config.get('attribute')
                if msg_type == 'note_on':
                    if attribute in ['velocity', 'note']:
                        return True
                elif msg_type == 'note_off':
                    if attribute == 'trigger':
                        return True
                        
        elif source_type == 'cc':
            if msg_type == 'cc':
                if data.get('number') == source_config.get('number'):
                    return True
                    
        return False
        
    def process_message(self, message, voice_nav):
        """Process message through module's routing rules"""
        if not self.validate_message(message):
            return False
            
        module_config = self.get_module_config()
        parameters = module_config.get('parameters', {})
        
        processed = False
        for param_name, param_config in parameters.items():
            sources = param_config.get('sources', [])
            for source in sources:
                value = self.extract_source_value(message, source)
                if value is not None:
                    transformed = self.transform_value(value, source)
                    voice_nav.route_to_destination(
                        {'id': self.module_name, 'attribute': param_name},
                        transformed,
                        message
                    )
                    processed = True
                    
        return processed

class OscillatorRouter(ModuleRouter):
    """Oscillator-specific routing implementation"""
    def __init__(self, config=None):
        super().__init__(config)
        self.module_name = "oscillator"
        
    def process_message(self, message, voice_nav):
        """Handle oscillator-specific routing with frequency transformation"""
        if not self.validate_message(message):
            return False
            
        module_config = self.get_module_config()
        parameters = module_config.get('parameters', {})
        
        # Special handling for frequency parameter
        if 'frequency' in parameters:
            freq_config = parameters['frequency']
            for source in freq_config.get('sources', []):
                value = self.extract_source_value(message, source)
                if value is not None:
                    if source.get('transform') == 'midi_to_frequency':
                        # Let voice manager handle frequency conversion
                        voice_nav.route_to_destination(
                            {'id': 'oscillator', 'attribute': 'frequency'},
                            value,
                            message
                        )
                        return True
                    else:
                        transformed = self.transform_value(value, source)
                        voice_nav.route_to_destination(
                            {'id': 'oscillator', 'attribute': 'frequency'},
                            transformed,
                            message
                        )
                        return True
                        
        # Handle other oscillator parameters
        return super().process_message(message, voice_nav)

class FilterRouter(ModuleRouter):
    """Filter-specific routing implementation"""
    def __init__(self, config=None):
        super().__init__(config)
        self.module_name = "filter"
        
    def process_message(self, message, voice_nav):
        """Handle filter parameter routing"""
        if not self.validate_message(message):
            return False
            
        module_config = self.get_module_config()
        parameters = module_config.get('parameters', {})
        
        processed = False
        for param_name in ['frequency', 'resonance', 'type']:
            if param_name in parameters:
                param_config = parameters[param_name]
                for source in param_config.get('sources', []):
                    value = self.extract_source_value(message, source)
                    if value is not None:
                        transformed = self.transform_value(value, source)
                        voice_nav.route_to_destination(
                            {'id': 'filter', 'attribute': param_name},
                            transformed,
                            message
                        )
                        processed = True
                        
        return processed

class AmplifierRouter(ModuleRouter):
    """Amplifier and envelope routing implementation"""
    def __init__(self, config=None):
        super().__init__(config)
        self.module_name = "amplifier"
        
    def process_message(self, message, voice_nav):
        """Handle amplifier and envelope routing"""
        if not self.validate_message(message):
            return False
            
        module_config = self.get_module_config()
        parameters = module_config.get('parameters', {})
        
        processed = False
        
        # Handle gain parameter
        if 'gain' in parameters:
            gain_config = parameters['gain']
            for source in gain_config.get('sources', []):
                value = self.extract_source_value(message, source)
                if value is not None:
                    transformed = self.transform_value(value, source)
                    voice_nav.route_to_destination(
                        {'id': 'amplifier', 'attribute': 'gain'},
                        transformed,
                        message
                    )
                    processed = True
        
        # Handle envelope parameters
        if 'envelope' in parameters:
            env_config = parameters['envelope']
            for stage in ['attack', 'decay', 'sustain', 'release']:
                if stage in env_config:
                    stage_config = env_config[stage]
                    for param_type in ['time', 'level']:
                        if param_type in stage_config:
                            param_config = stage_config[param_type]
                            for source in param_config.get('sources', []):
                                value = self.extract_source_value(message, source)
                                if value is not None:
                                    transformed = self.transform_value(value, source)
                                    voice_nav.route_to_destination(
                                        {'id': 'amplifier',
                                         'attribute': f'envelope.{stage}.{param_type}'},
                                        transformed,
                                        message
                                    )
                                    processed = True
                                    
        return processed
