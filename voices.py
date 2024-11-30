"""
voices.py - Voice and Note Management

Processes routes and applies values to synthio notes.
All calculations done by synthesizer.py.
No defaults, no assumptions, fail verbosely.
"""

import time
import sys
import synthio
from synthesizer import Synthesizer 
from constants import VOICES_DEBUG, SAMPLE_RATE, AUDIO_CHANNEL_COUNT

def _log(message, module="VOICES"):
    """Strategic logging for voice state changes"""
    if not VOICES_DEBUG:
        return
        
    RED = "\033[31m"
    YELLOW = "\033[33m"
    LIGHT_YELLOW = "\033[93m"
    RESET = "\033[0m"
    
    # Determine color based on message content
    message_str = str(message)
    if "[ERROR]" in message_str:
        color = RED
    elif "[REJECTED]" in message_str:
        color = YELLOW
    else:
        color = LIGHT_YELLOW
    
    if isinstance(message, str) and '/' in message:
        print("{}[{}] Route: {}{}".format(color, module, message, RESET), file=sys.stderr)
    elif isinstance(message, dict):
        print("{}[{}] Voice {}: {} - {}{}".format(
            color, module,
            message.get('identifier', 'unknown'),
            message.get('action', 'unknown'),
            message.get('detail', ''),
            RESET
        ), file=sys.stderr)
    else:
        print("{}[{}] {}{}".format(color, module, message, RESET), file=sys.stderr)

class RouteProcessor:
    """Base class for processing routes for a signal chain section"""
    def __init__(self):
        # Single source of truth for global values
        self.global_values = {}
        # Per-key values only store key-specific overrides
        self.per_key_values = {}
        
    def process_global(self, param, value):
        """Process global parameter - the single source of truth"""
        self.global_values[param] = value
        _log({
            'action': 'global_store',
            'identifier': 'global',
            'detail': "{}={}".format(param, value)
        })
        
    def process_per_key(self, identifier, param, value):
        """Process per-key parameter - only for key-specific overrides"""
        if identifier not in self.per_key_values:
            self.per_key_values[identifier] = {}
        # Only store if different from global value
        if param not in self.global_values or value != self.global_values[param]:
            self.per_key_values[identifier][param] = value
            _log({
                'action': 'per_key_store',
                'identifier': identifier,
                'detail': "{}={}".format(param, value)
            })
        
    def get_values(self, identifier):
        """Get values with globals as the base, only overridden by per-key values"""
        # Start with a copy of global values
        values = self.global_values.copy()
        # Only override with per-key values if they exist
        if identifier in self.per_key_values:
            values.update(self.per_key_values[identifier])
        return values
        
    def clear_per_key(self, identifier):
        """Clear per-key values when voice is cleaned up"""
        if identifier in self.per_key_values:
            del self.per_key_values[identifier]

class OscillatorRoutes(RouteProcessor):
    def __init__(self):
        super().__init__()
        self.synth_tools = Synthesizer()
        
    def process_per_key(self, identifier, param, value):
        if param == 'frequency':
            # Always convert note number to frequency when storing
            freq = self.synth_tools.note_to_frequency(float(value))
            super().process_per_key(identifier, param, freq)
        else:
            super().process_per_key(identifier, param, value)
            
    def has_minimum_requirements(self, identifier):
        values = self.get_values(identifier)
        return 'frequency' in values and 'waveform' in values

class FilterRoutes(RouteProcessor):
    """Handles filter routing with no defaults"""
    def __init__(self):
        super().__init__()
        self.valid_types = {'high_pass', 'low_pass', 'band_pass', 'notch'}
        
    def process_global(self, param, value, route_parts):
        """Process global filter parameter from route parts"""
        filter_type = None
        for part in route_parts:
            if part in self.valid_types:
                filter_type = part.replace('_', '')
                break
                
        if not filter_type:
            _log("[ERROR] No valid filter type found in route")
            return
            
        if param not in {'frequency', 'resonance'}:
            _log("[ERROR] Invalid filter parameter: {}".format(param))
            return
            
        try:
            float_value = float(value)
            # Store filter type in global values
            if 'filter_type' not in self.global_values:
                self.global_values['filter_type'] = filter_type
            self.global_values[param] = float_value
            
            _log({
                'action': 'global_store',
                'identifier': 'global',
                'detail': f"{param}={float_value} (type={filter_type})"
            })
        except ValueError:
            _log("[ERROR] Invalid value for {}: {} - must be a number".format(param, value))
        
    def process_per_key(self, identifier, param, value, route_parts):
        """Process per-key filter parameter from route parts"""
        filter_type = None
        for part in route_parts:
            if part in self.valid_types:
                filter_type = part.replace('_', '')
                break
                
        if not filter_type:
            _log("[ERROR] No valid filter type found in route")
            return
            
        if param not in {'frequency', 'resonance'}:
            _log("[ERROR] Invalid filter parameter: {}".format(param))
            return
            
        try:
            float_value = float(value)
            if identifier not in self.per_key_values:
                self.per_key_values[identifier] = {}
            # Only store if different from global
            if param not in self.global_values or float_value != self.global_values[param]:
                self.per_key_values[identifier][param] = float_value
            # Store filter type if different from global
            if ('filter_type' not in self.global_values or 
                filter_type != self.global_values['filter_type']):
                self.per_key_values[identifier]['filter_type'] = filter_type
                
            _log({
                'action': 'per_key_store',
                'identifier': identifier,
                'detail': f"{param}={float_value} (type={filter_type})"
            })
        except ValueError:
            _log("[ERROR] Invalid value for {}: {} - must be a number".format(param, value))
        
    def has_minimum_requirements(self, values):
        """Check if minimum filter requirements are met"""
        return ('frequency' in values and 
                'resonance' in values and 
                'filter_type' in values)

class AmplifierRoutes(RouteProcessor):
    def __init__(self):
        super().__init__()
        self.triggers = {}
        
    def add_trigger(self, identifier, trigger_type):
        self.triggers[identifier] = trigger_type
        
    def get_trigger(self, identifier):
        if identifier in self.triggers:
            trigger = self.triggers[identifier]
            del self.triggers[identifier]
            return trigger
        return None

class Voice:
    def __init__(self, identifier, osc, filter_proc, amp, synth_tools, synth):
        self.identifier = identifier
        self.state = "COLLECTING"
        self.note = None
        self.active = True
        self.synth = synth
        self.osc = osc
        self.filter = filter_proc
        self.amp = amp
        self.synth_tools = synth_tools
        
        _log({
            'identifier': identifier,
            'action': 'create',
            'detail': "state={}".format(self.state)
        })
        
    def process_route(self, route_parts, value):
        """Process incoming routes to modify voice parameters"""
        signal_chain = route_parts[0]
        
        # Extract the actual parameter and any modifiers from the route
        param = None
        value_type = None
        
        # Search for known parameters in the route
        for i, part in enumerate(route_parts):
            if part in ('frequency', 'waveform'):  # Oscillator params
                param = part
                # Look ahead for trigger
                if i + 1 < len(route_parts) and route_parts[i + 1] == 'trigger':
                    value_type = 'trigger'
                break
            elif part in ('attack', 'release'):  # Amplifier params
                param = part
                # Look ahead for trigger
                if i + 1 < len(route_parts) and route_parts[i + 1] == 'trigger':
                    value_type = 'trigger'
                break
            elif part in ('attack_time', 'decay_time', 'release_time', 'attack_level', 'sustain_level'):  # Envelope params
                param = part
                break
            elif part in ('frequency', 'resonance'):  # Filter params
                param = part
                break
                
        if signal_chain == 'oscillator':
            if not param:
                _log("[ERROR] No route for '{}' in oscillator".format(route_parts[-2]))
                return
                
            if param == 'frequency' and value_type == 'trigger':
                # Extract the actual note number from the value
                try:
                    note_number = float(value)
                    self.osc.process_per_key(self.identifier, param, note_number)
                    self._try_update_note(param, note_number)
                except ValueError:
                    _log("[ERROR] Invalid note number value: {}".format(value))
                    return
            elif param == 'waveform':
                self.osc.process_per_key(self.identifier, param, value)
                self._try_update_note(param, value)
            else:
                _log("[ERROR] No route for '{}' in oscillator".format(param))
                return
                
        elif signal_chain == 'filter':
            if param in ('frequency', 'resonance'):
                self.filter.process_per_key(self.identifier, param, value, route_parts)
                self._update_filter()
            else:
                _log("[ERROR] No route for '{}' in filter".format(param or route_parts[-2]))
                return
                
        elif signal_chain == 'amplifier':
            if param in ('attack', 'release') and value_type == 'trigger':
                self.amp.add_trigger(self.identifier, param)
            elif param in ('attack_time', 'decay_time', 'release_time', 'attack_level', 'sustain_level'):
                try:
                    float_value = float(value)
                    self.amp.process_per_key(self.identifier, param, float_value)
                    # Update envelope parameters if note exists
                    if self.note and hasattr(self.note, 'envelope'):
                        setattr(self.note.envelope, param, float_value)
                except ValueError:
                    _log("[ERROR] Invalid value for {}: {} - must be a number".format(param, value))
                    return
            else:
                _log("[ERROR] No route for '{}' in amplifier".format(param or route_parts[-2]))
                return
                    
        self._handle_pending_trigger()
        
    def _try_update_note(self, param, value):
        """Update note parameter if note exists and is playing"""
        if self.note and self.state == "PLAYING":
            try:
                if param == 'frequency':
                    self.note.frequency = self.synth_tools.note_to_frequency(float(value))
                else:
                    setattr(self.note, param, value)
                
                _log({
                    'identifier': self.identifier,
                    'action': 'note_update',
                    'detail': "{}={}".format(param, value)
                })
            except Exception as e:
                _log("[ERROR] Failed to update note {}: {}".format(param, str(e)))
                
    def _update_filter(self):
        """Update filter parameters with no defaults"""
        if not self.note or self.state != "PLAYING":
            return
            
        filter_values = self.filter.get_values(self.identifier)
        if not self.filter.has_minimum_requirements(filter_values):
            return
            
        try:
            self.note.filter = self.synth_tools.calculate_filter(
                filter_values['frequency'],
                filter_values['resonance'],
                filter_values['filter_type']
            )
            
            _log({
                'identifier': self.identifier,
                'action': 'filter_update',
                'detail': f"freq={filter_values['frequency']}, res={filter_values['resonance']}, type={filter_values['filter_type']}"
            })
            
        except Exception as e:
            _log("[ERROR] Filter update failed: {}".format(str(e)))
            
    def _handle_pending_trigger(self):
        """Process any pending envelope triggers"""
        trigger = self.amp.get_trigger(self.identifier)
        if not trigger:
            return
            
        if trigger == 'attack':
            if self.state != "COLLECTING":
                _log("[ERROR] Attack trigger in wrong state: {}".format(self.state))
                return
                
            if not self.osc.has_minimum_requirements(self.identifier):
                _log("[ERROR] Attack without minimum requirements")
                return
                
            self._create_note()
            self.state = "PLAYING"
            _log({
                'identifier': self.identifier,
                'action': 'state_change',
                'detail': 'COLLECTING -> PLAYING'
            })
            
        elif trigger == 'release':
            if self.state != "PLAYING":
                _log("[ERROR] Release trigger in wrong state: {}".format(self.state))
                return
            self.state = "FINISHING"
            self.active = False
            if self.note:
                try:
                    _log("Pressing release:")
                    self.synth.release(self.note)
                except Exception as e:
                    _log("[ERROR] Failed to release note: {}".format(str(e)))
            _log({
                'identifier': self.identifier,
                'action': 'state_change',
                'detail': 'PLAYING -> FINISHING'
            })
            
    def _create_note(self):
        try:
            osc_values = self.osc.get_values(self.identifier)
            amp_values = self.amp.get_values(self.identifier)

            note_params = {
                'frequency': osc_values['frequency'],
                'waveform': self.synth_tools.get_waveform(osc_values['waveform'])
            }

            env_params = {}
            for param in ['attack_time', 'decay_time', 'release_time', 'attack_level', 'sustain_level']:
                if param in amp_values:
                    try:
                        env_params[param] = float(amp_values[param])
                    except ValueError:
                        _log(
                            "[ERROR] Note creation failed: {}: {} must be of type float, not {}".format(
                                param, amp_values[param], type(amp_values[param]).__name__
                            )
                        )
                        return

            if env_params:
                try:
                    note_params['envelope'] = synthio.Envelope(**env_params)
                except TypeError as te:
                    message = str(te)
                    for key, value in env_params.items():
                        if key in message:
                            _log(
                                "[ERROR] Note creation failed: {}: {} must be of type float, not {}".format(
                                    key, value, type(value).__name__
                                )
                            )
                            break
                    else:
                        _log("[ERROR] Note creation failed: {}".format(message))
                    return

            self.note = synthio.Note(**note_params)
            
            # Apply filter if all parameters are available
            filter_values = self.filter.get_values(self.identifier)
            if self.filter.has_minimum_requirements(filter_values):
                self.note.filter = self.synth_tools.calculate_filter(
                    filter_values['frequency'],
                    filter_values['resonance'],
                    filter_values['filter_type']
                )
            
            _log({
                'identifier': self.identifier,
                'action': 'note_create',
                'detail': "params={}".format(note_params)
            })

        except Exception as e:
            _log("[ERROR] Note creation failed: {}".format(str(e)))
            self.note = None
            
    def is_active(self):
        return self.active
        
    def cleanup(self):
        """Clean up voice state"""
        self.osc.clear_per_key(self.identifier)
        self.filter.clear_per_key(self.identifier)
        self.amp.clear_per_key(self.identifier)
        self.note = None
        self.active = False

class VoiceManager:
    def __init__(self):
        _log("Starting VoiceManager initialization...")
        
        self.osc = OscillatorRoutes()
        self.filter = FilterRoutes()
        self.amp = AmplifierRoutes()
        
        self.voices = {}
        self.synth_tools = Synthesizer()
        
        self.synth = synthio.Synthesizer(
            sample_rate=SAMPLE_RATE,
            channel_count=AUDIO_CHANNEL_COUNT
        )
        
        _log("VoiceManager initialization complete")

    def get_synth(self):
        return self.synth

    def test_audio_hardware(self):
        try:
            _log("Testing synthesizer audio output...")
            self.synth.press(64)
            time.sleep(0.1)
            self.synth.release(64)
            time.sleep(0.05)
            _log("Synthio and Audio System BEEP!")
        except Exception as e:
            _log("[ERROR] Synthesizer audio test failed: {}".format(str(e)))

    def handle_route(self, route):
        """Process routes with proper state handling"""
        _log("Processing route: {}".format(route))
        
        parts = route.split('/')
        if len(parts) < 4:
            _log("[ERROR] Invalid route format: {}".format(route))
            return
            
        signal_chain = parts[0]
        value = parts[-1]
        param = parts[-2]
        identifier = None
        
        for part in parts:
            if '.' in part:
                identifier = part
                break
                
        if 'global' in parts:
            processor = self.osc if signal_chain == 'oscillator' else \
                       self.filter if signal_chain == 'filter' else \
                       self.amp if signal_chain == 'amplifier' else None
                       
            if processor:
                if signal_chain == 'filter':
                    processor.process_global(param, value, parts)
                else:
                    processor.process_global(param, value)
                    
                # Update all active voices with the new global value
                for voice in self.voices.values():
                    if voice.is_active() and voice.state == "PLAYING":
                        voice.process_route(parts, value)
            return
            
        if identifier:
            if identifier not in self.voices:
                self.voices[identifier] = Voice(
                    identifier, self.osc, self.filter, self.amp, self.synth_tools, self.synth
                )
            
            voice = self.voices[identifier]
            voice.process_route(parts, value)
            
            if voice.note and voice.state == "PLAYING" and voice.is_active():
                try:
                    self.synth.press(voice.note)
                except Exception as e:
                    _log("[ERROR] Failed to press note: {}".format(str(e)))

    def cleanup_voices(self):
        """Clean up inactive voices and their state"""
        for identifier in list(self.voices.keys()):
            if not self.voices[identifier].is_active():
                _log("Cleaning up voice: {}".format(identifier))
                self.voices[identifier].cleanup()
                del self.voices[identifier]

    def cleanup(self):
        if self.synth:
            self.synth.deinit()
            _log("Synthesizer cleaned up")
