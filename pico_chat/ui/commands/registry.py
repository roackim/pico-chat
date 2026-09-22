"""Command registry: the single assembly point for all slash commands.

Handlers live in per-domain modules (``core``, ``server``, ``models``,
``roles``, ``debug``, ``conversation``, ``tools``, ``openrouter``). Those
modules depend only on :mod:`pico_chat.ui.commands.base`; this module is the
only place that knows about all of them, which keeps the import graph acyclic.

Most commands are plain handler functions with metadata. ``Command`` classes
are reserved for commands that own a subcommand tree (server/model/debug/
openrouter/conversation).
"""

from __future__ import annotations

from typing import Dict, List

from .base import ChatUIProtocol, Command, Param, config_section_completions
from .conversation import ConversationCommand
from .core import (
    cmd_activity,
    cmd_cd,
    cmd_clear,
    cmd_compact,
    cmd_config,
    cmd_edit,
    cmd_exit,
    cmd_help,
    cmd_pwd,
    cmd_reload,
    cmd_status,
    cmd_stop,
)
from .debug import DebugCommand
from .models import ModelCommand
from .openrouter import OpenRouterCommand
from .roles import cmd_roles
from .server import ServerCommand
from .tools import cmd_tools

# Help needs the whole registry, so its handler is assembled here.
async def _help(ui: ChatUIProtocol, args: List[str]):
    await cmd_help(ui, args, COMMANDS)


# Command Registry
COMMANDS: Dict[str, Command] = {
    "help":         Command("help", "Show available commands", handler=_help),
    "clear":        Command("clear", "Clear chat history", handler=cmd_clear),
    "reload":       Command("reload", "Reload config files and the roles directory from disk",
                            handler=cmd_reload),
    "config":       Command("config", "Edit a config file in $EDITOR and reload it",
                            handler=cmd_config,
                            params=[Param("SECTION", completions=config_section_completions)]),
    "edit":         Command("edit", "Open a file in $EDITOR", handler=cmd_edit,
                            params=[Param("FILE", path=True)]),
    "compact":      Command("compact", "Compact context with an LLM summary marker",
                            handler=cmd_compact),
    "exit":         Command("exit", "Close the application", handler=cmd_exit),
    "stop":         Command("stop", "Stop current generation", handler=cmd_stop),
    "status":       Command("status", "Show system and connection status", handler=cmd_status),
    "activity":     Command("activity", "Toggle the activity overlay (shell/status output)",
                            handler=cmd_activity),
    "server":       ServerCommand(),
    "model":        ModelCommand(),
    "tools":        Command("tools", "Show available tools and their permissions",
                            handler=cmd_tools),
    "debug":        DebugCommand(),
    "roles":        Command("roles", "Select and inspect conversation roles", handler=cmd_roles),
    "openrouter":   OpenRouterCommand(),
    "cd":           Command("cd", "Change workspace directory and rebuild context",
                            handler=cmd_cd, params=[Param("DIR", path=True)]),
    "pwd":          Command("pwd", "Show current workspace directory", handler=cmd_pwd),
    "conversation": ConversationCommand(),
}


async def handle_command(ui: ChatUIProtocol, text: str):
    parts = text.strip().split()
    if not parts:
        return

    cmd_name = parts[0][1:].lower()  # Remove '/'
    args = parts[1:]

    if cmd_name in COMMANDS:
        await COMMANDS[cmd_name].execute(ui, args)
    else:
        from pico_chat.ui.tui.msg_types import SysMsgError
        ui.chat_history_panel.add_message(
            f"Unknown command: /{cmd_name}",
            msg_type=SysMsgError(),
        )


def get_command_list() -> List[str]:
    """Get list of top-level commands."""
    return list(COMMANDS.keys())


def get_subcommand_list(command: str) -> List[str]:
    """Get list of subcommands for a given command."""
    if command in COMMANDS:
        cmd = COMMANDS[command]
        if cmd.has_subcommands():
            return list(cmd.subcommands.keys())
    return []


__all__ = [
    "COMMANDS",
    "Command",
    "Param",
    "ChatUIProtocol",
    "handle_command",
    "get_command_list",
    "get_subcommand_list",
]
