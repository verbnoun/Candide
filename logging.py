"""Centralized logging system for Candide synthesizer."""

import sys
import array

# ANSI Colors - Using bright variants for dark mode visibility, avoiding reds
COLOR_WHITE = '\033[97m'        # Bright White for code.py
COLOR_ORANGE = '\033[38;5;215m' # Bright Orange
COLOR_YELLOW = '\033[93m'       # Bright Yellow
COLOR_CHARTREUSE = '\033[38;5;226m' # Bright Chartreuse
COLOR_LIME = '\033[38;5;118m'   # Bright Lime
COLOR_GREEN = '\033[92m'        # Bright Green
COLOR_SPRING = '\033[38;5;121m' # Bright Spring Green
COLOR_CYAN = '\033[96m'         # Bright Cyan
COLOR_AZURE = '\033[38;5;117m'  # Bright Azure
COLOR_BLUE = '\033[94m'         # Bright Blue
COLOR_INDIGO = '\033[38;5;147m' # Bright Indigo
COLOR_VIOLET = '\033[95m'       # Bright Violet
COLOR_MAGENTA = '\033[38;5;213m' # Bright Magenta
COLOR_ERROR = '\033[30;41m'     # Black text on red background for errors
COLOR_RESET = '\033[0m'

# Module Tags (7 chars) - Alphabetically ordered
TAG_CANDIDE = 'CANDIDE'  # code.py
TAG_CONNECT = 'CONECT '  # connection.py
TAG_CONST = 'CONST  '    # constants.py
TAG_HARD = 'HARD   '     # hardware.py
TAG_INST = 'INST   '     # instruments.py
TAG_IFACE = 'IFACE  '    # interfaces.py
TAG_MIDI = 'MIDI   '     # midi.py
TAG_MOD = 'MOD    '     # modulation.py
TAG_NOTE = 'NOTE   '     # synth_note.py
TAG_PARSER = 'PARSER '   # path_parser.py
TAG_PATCH = 'PATCH  '    # patcher.py
TAG_ROUTE = 'ROUTE  '    # router.py
TAG_STORE = 'STORE  '    # synth_store.py
TAG_SYNTH = 'SYNTH  '    # synthesizer.py
TAG_UART = 'UART   '     # uart.py
TAG_WAVE = 'WAVE   '     # synth_wave.py

# Map tags to colors - Alphabetically ordered by file name tag
TAG_COLORS = {
    TAG_CANDIDE: COLOR_WHITE,     # code.py
    TAG_CONNECT: COLOR_ORANGE,    # connection.py
    TAG_CONST: COLOR_YELLOW,      # constants.py
    TAG_HARD: COLOR_CHARTREUSE,   # hardware.py
    TAG_INST: COLOR_VIOLET,       # instruments.py
    TAG_IFACE: COLOR_AZURE,       # interfaces.py
    TAG_MIDI: COLOR_GREEN,        # midi.py
    TAG_MOD: COLOR_LIME,         # modulation.py
    TAG_NOTE: COLOR_SPRING,      # synth_note.py
    TAG_PARSER: COLOR_MAGENTA,    # path_parser.py
    TAG_PATCH: COLOR_CYAN,        # patcher.py
    TAG_ROUTE: COLOR_BLUE,        # router.py
    TAG_STORE: COLOR_CHARTREUSE,  # synth_store.py
    TAG_SYNTH: COLOR_INDIGO,      # synthesizer.py
    TAG_UART: COLOR_VIOLET,       # uart.py
    TAG_WAVE: COLOR_AZURE,        # synth_wave.py
}

# Enable flags for each module's logging - Alphabetically ordered
LOG_ENABLE = {
    TAG_CANDIDE: True,
    TAG_CONNECT: True,
    TAG_CONST: False,
    TAG_HARD: False,
    TAG_INST: True,
    TAG_IFACE: False,
    TAG_MIDI: False,
    TAG_MOD: True,
    TAG_NOTE: True,
    TAG_PARSER: True,
    TAG_PATCH: True,
    TAG_ROUTE: True,
    TAG_STORE: True,
    TAG_SYNTH: True,
    TAG_UART: False,
    TAG_WAVE: True,
}

# Special debug flags
HEARTBEAT_DEBUG = False

def format_value(value):
    """Format values for logging, with special handling for arrays."""
    try:
        # Handle CircuitPython array.array objects
        if isinstance(value, array.array):
            return "waveform"
        # Handle list-like objects    
        elif hasattr(value, '__len__') and hasattr(value, '__getitem__'):
            return '[...]'
        # Handle dictionaries
        elif isinstance(value, dict):
            return {k: format_value(v) for k, v in value.items()}
        return str(value)
    except Exception:
        return str(value)

def log(tag, message, is_error=False, is_heartbeat=False):
    """
    Log a message with the specified tag and optional error status.
    
    Args:
        tag: Module tag (must be 7 chars, spaces ok)
        message: Message to log
        is_error: Whether this is an error message
        is_heartbeat: Whether this is a heartbeat message (special case)
    """
    # Skip heartbeat messages unless HEARTBEAT_DEBUG is True
    if is_heartbeat and not HEARTBEAT_DEBUG:
        return
        
    # Check if logging is enabled for this tag
    if not LOG_ENABLE.get(tag, True):
        return
        
    if len(tag) != 7:
        raise ValueError("Tag must be exactly 7 characters (spaces ok)")
        
    # Get module's color or default to white
    color = TAG_COLORS.get(tag, COLOR_WHITE)
    
    # Format the message
    if is_error:
        print("{}[{}] [ERROR] {}{}".format(COLOR_ERROR, tag, message, COLOR_RESET), file=sys.stderr)
    else:
        print("{}[{}] {}{}".format(color, tag, message, COLOR_RESET), file=sys.stderr)

# Example usage:
# from logging import log, TAG_CANDIDE
# log(TAG_CANDIDE, 'Starting system')
# log(TAG_CANDIDE, 'Failed to initialize', is_error=True)
# log(TAG_CONNECT, '♡', is_heartbeat=True)  # Only logs if HEARTBEAT_DEBUG is True
