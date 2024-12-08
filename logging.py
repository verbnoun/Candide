"""Centralized logging system for Candide synthesizer."""

import sys

# ANSI Colors
COLOR_WHITE = '\033[37m'
COLOR_CYAN = '\033[96m'
COLOR_MAGENTA = '\033[95m'
COLOR_YELLOW = '\033[93m'
COLOR_GREEN = '\033[92m'
COLOR_BLUE = '\033[94m'
COLOR_ORANGE = '\033[38;5;215m'
COLOR_LIGHT_CYAN = '\033[36m'
COLOR_LIGHT_GREEN = '\033[32m'
COLOR_PURPLE = '\033[35m'
COLOR_RED = '\033[31m'
COLOR_RESET = '\033[0m'

# Module Tags (7 chars)
TAG_CANDIDE = 'CANDIDE'
TAG_CONNECT = 'CONECT '
TAG_HARD = 'HARD   '
TAG_INST = 'INST   '
TAG_SYNTH = 'SYNTH  '
TAG_UART = 'UART   '
TAG_MIDI = 'MIDI   '
TAG_MODU = 'MODU   '
TAG_ROUTE = 'ROUTE  '
TAG_VOICE = 'VOICE  '
TAG_POOL = 'POOL   '
TAG_PATCH = 'PATCH  '

# Map tags to colors
TAG_COLORS = {
    TAG_CANDIDE: COLOR_WHITE,
    TAG_CONNECT: COLOR_CYAN,
    TAG_HARD: COLOR_MAGENTA,
    TAG_INST: COLOR_YELLOW,
    TAG_SYNTH: COLOR_GREEN,
    TAG_UART: COLOR_BLUE,
    TAG_MIDI: COLOR_ORANGE,
    TAG_MODU: COLOR_LIGHT_CYAN,
    TAG_ROUTE: COLOR_LIGHT_GREEN,
    TAG_VOICE: COLOR_PURPLE,
    TAG_POOL: COLOR_YELLOW,
    TAG_PATCH: COLOR_BLUE,
}

# Enable flags for each module's logging
LOG_ENABLE = {
    TAG_CANDIDE: True,
    TAG_CONNECT: False,
    TAG_HARD: False,
    TAG_INST: False,
    TAG_SYNTH: True,
    TAG_UART: False,
    TAG_MIDI: True,
    TAG_MODU: True,
    TAG_ROUTE: True,
    TAG_VOICE: True,
    TAG_POOL: True,
    TAG_PATCH: True,
}

# Special debug flags
HEARTBEAT_DEBUG = False

def log(tag, message, is_error=False, is_heartbeat=False):
    """
    Log a message with the specified tag and optional error status.
    
    Args:
        tag: Module tag (must be 7 chars, spaces ok)
        message: Message to log
        is_error: Whether this is an error message
        is_heartbeat: Whether this is a heartbeat message (special case)
    """
    # Check if logging is enabled for this tag, with special case for heartbeat
    if not LOG_ENABLE.get(tag, True) and not (is_heartbeat and HEARTBEAT_DEBUG):
        return
        
    if len(tag) != 7:
        raise ValueError(f"Tag must be exactly 7 characters (spaces ok), got '{tag}' ({len(tag)})")
        
    # Get module's color or default to white
    color = TAG_COLORS.get(tag, COLOR_WHITE)
    
    # Format the message
    if is_error:
        print(f"{COLOR_RED}[{tag}] [ERROR] {message}{COLOR_RESET}", file=sys.stderr)
    else:
        print(f"{color}[{tag}] {message}{COLOR_RESET}", file=sys.stderr)

# Example usage:
# from logging import log, TAG_CANDIDE
# log(TAG_CANDIDE, 'Starting system')
# log(TAG_CANDIDE, 'Failed to initialize', is_error=True)
# log(TAG_CONNECT, '♡', is_heartbeat=True)  # Only logs if HEARTBEAT_DEBUG is True
