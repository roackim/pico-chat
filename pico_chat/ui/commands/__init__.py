"""Command package public API.

Concrete command implementations live in :mod:`pico_chat.ui.commands.builtins`.
This module preserves the historical ``pico_chat.ui.commands`` import path.
"""

from .builtins import Command, Param, StatusCommand
from .registry import (
    COMMANDS,
    get_command_list,
    get_subcommand_list,
    handle_command,
)

__all__ = [
    "COMMANDS",
    "Command",
    "Param",
    "StatusCommand",
    "get_command_list",
    "get_subcommand_list",
    "handle_command",
]
