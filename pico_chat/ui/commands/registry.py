"""Public command registry and dispatch helpers."""

from .builtins import (
    COMMANDS,
    get_command_list,
    get_subcommand_list,
    handle_command,
)

__all__ = ["COMMANDS", "get_command_list", "get_subcommand_list", "handle_command"]
