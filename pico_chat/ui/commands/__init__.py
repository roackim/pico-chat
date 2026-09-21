"""Command package public API.

Concrete commands live in per-domain modules (``core``, ``server``,
``models``, ``roles``, ``debug``, ``conversation``, ``tabs``, ``tools``,
``openrouter``). The registry in
:mod:`pico_chat.ui.commands.registry` assembles them; this module is the
public import path.
"""

from .base import ChatUIProtocol, Command, Param
from .core import StatusCommand
from .registry import (
    COMMANDS,
    get_command_list,
    get_subcommand_list,
    handle_command,
)

__all__ = [
    "COMMANDS",
    "ChatUIProtocol",
    "Command",
    "Param",
    "StatusCommand",
    "get_command_list",
    "get_subcommand_list",
    "handle_command",
]
