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
    
    if isinstance(message, str) and '/' in message:
        print("{}[{}] Route: {}{}".format(LIGHT_YELLOW, module, message, RESET), file=sys.stderr)
    elif isinstance(message, dict):
        print("{}[{}] Voice {}: {} - {}{}".format(
            LIGHT_YELLOW, module,
            message.get('identifier', 'unknown'),
            message.get('action', 'unknown'),
            message.get('detail', ''),
            RESET
        ), file=sys.stderr)
    else:
        color = RED if "[ERROR]" in str(message) else YELLOW if "[REJECTED]" in str(message) else LIGHT_YELLOW
        print("{}[{}] {}{}".format(color, module, message, RESET), file=sys.stderr)

class RouteProcessor:
    """Base class for processing routes for a signal chain section"""
    def __init__(self):
        self.global_values = {}
        self.per_key_values = {}
        
    def process_global(self, param, value):
        self.global_values[param] = value
        _log({
            'action': 'global_store',
            'identifier': 'global',
            'detail': "{}={}".format(param, value)
        })
        
    def process_per_key(self, identifier, param, value):
        if identifier not in self.per_key_values:
            self.per_key_values[identifier] = {}
        self.per_key_values[identifier][param] = value
        _log({
            'action': 'per_key_store',
            'identifier': identifier,
            'detail': "{}={}".format(param, value)
        })
        
    def get_values(self, identifier):
        values = self.global_values.copy()
        if identifier in self.per_key_values:
            values.update(self.per_key_values[identifier])
        return values

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
    pass
        
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
    def __init__(self, identifier, osc, filter_proc, amp, synth_tools):
        self.identifier = identifier
        self.state = "COLLECTING"
        self.note = None
        self.active = True
        
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
        """Process incoming routes to modify voice parameters
        
        Examples:
        - oscillator/per_key/frequency/trigger/79    # when triggered, set freq to note 79 
        - oscillator/per_key/waveform/square        # set waveform type
        - amplifier/per_key/envelope/attack/trigger # trigger start of attack phase
        - amplifier/per_key/envelope/sustain_level/0.5 # set sustain level value
        """
        signal_chain = route_parts[0]
        
        # Extract param and value type if present from route parts
        param = None
        value_type = None
        for i, part in enumerate(route_parts):
            if part in ('frequency', 'waveform', 'attack', 'release', 'sustain_level'):
                param = part
                value_type = route_parts[i+1] if i+1 < len(route_parts) else None
                break
                
        if not param:
            _log("[ERROR] No valid parameter in route: {}".format('/'.join(route_parts)))
            return
                
        if signal_chain == 'oscillator':
            if param == 'frequency' and value_type == 'trigger':
                self.osc.process_per_key(self.identifier, param, value)
                self._try_update_note(param, value)
            elif param == 'waveform':  # waveform has no value_type, just store directly
                self.osc.process_per_key(self.identifier, param, value)
                self._try_update_note(param, value)
                
        elif signal_chain == 'amplifier':
            if value_type == 'trigger':
                # param will be 'attack' or 'release'
                self.amp.add_trigger(self.identifier, param)
            else:  # handle non-trigger params (like sustain_level)
                self.amp.process_per_key(self.identifier, param, value)
                    
        self._handle_pending_trigger()

        
    def _try_update_note(self, param, value):
        if self.note and self.state == "PLAYING":
            try:
                setattr(self.note, param, value)
                _log({
                    'identifier': self.identifier,
                    'action': 'note_update',
                    'detail': "{}={}".format(param, value)
                })
            except Exception as e:
                _log("[ERROR] Failed to update note {}: {}".format(param, str(e)))
                
    def _update_filter(self):
        if not self.note or self.state != "PLAYING":
            return
            
        filter_values = self.filter.get_values(self.identifier)
        if not filter_values:
            return
            
        try:
            freq = filter_values.get('frequency', 1000)
            res = filter_values.get('resonance', 0.7)
            self.note.filter = self.synth_tools.calculate_filter(freq, res)
        except Exception as e:
            _log("[ERROR] Filter update failed: {}".format(str(e)))
            
    def _handle_pending_trigger(self):
        """Process any pending envelope triggers
        A trigger means "execute this action now" - for envelopes this means
        start attack phase or start release phase.
        """
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
                    # Attempt to convert to float
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
        _log("Processing route: {}".format(route))
        
        parts = route.split('/')
        if len(parts) < 4:
            _log("[ERROR] Invalid route format: {}".format(route))
            return
            
        signal_chain = parts[0]
        value = parts[-1]
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
                param = parts[-2]
                processor.process_global(param, value)
                for voice in self.voices.values():
                    if voice.is_active():
                        voice.process_route(parts, value)
            return
            
        if identifier:
            if identifier not in self.voices:
                self.voices[identifier] = Voice(
                    identifier, self.osc, self.filter, self.amp, self.synth_tools
                )
            
            voice = self.voices[identifier]
            voice.process_route(parts, value)
            
            if voice.note and voice.state == "PLAYING" and voice.is_active():
                try:
                    self.synth.press(voice.note)
                except Exception as e:
                    _log("[ERROR] Failed to press note: {}".format(str(e)))

    def cleanup_voices(self):
        for identifier in list(self.voices.keys()):
            if not self.voices[identifier].is_active():
                _log("Cleaning up voice: {}".format(identifier))
                del self.voices[identifier]

    def cleanup(self):
        if self.synth:
            self.synth.deinit()
            _log("Synthesizer cleaned up")