"""Command registry: the single assembly point for all slash commands.

Each command lives in a module named after its domain (``core``, ``server``,
``models``, ``roles``, ``debug``, ``conversation``, ``tabs``, ``tools``,
``openrouter``). Those modules depend only on
:mod:`pico_chat.ui.commands.base`; this module is the only place that knows
about all of them, which keeps the import graph acyclic.
"""

from __future__ import annotations

from typing import Dict, List

from .base import ChatUIProtocol, Command, Param
from .conversation import (
    ConversationCommand,
    ConversationExportCommand,
    ConversationImportCommand,
)
from .core import (
    ActivityCommand,
    CdCommand,
    ClearCommand,
    CompactCommand,
    ConfigCommand,
    EditCommand,
    ExitCommand,
    HelpCommand,
    PwdCommand,
    ReloadCommand,
    ResumeCommand,
    StatusCommand,
    StopCommand,
)
from .debug import (
    DebugCommand,
    DebugGetContextCommand,
    DebugLogCommand,
    DebugPanelCommand,
    DebugSystemPromptCommand,
)
from .models import ModelCommand, ModelListCommand, ModelUseCommand
from .openrouter import OpenRouterBalanceCommand, OpenRouterCommand
from .roles import RolesCommand
from .server import (
    ServerCommand,
    ServerEditCommand,
    ServerInfoCommand,
    ServerListCommand,
    ServerRemoveCommand,
    ServerUseCommand,
)
from .tools import ToolsCommand

# Command Registry
COMMANDS: Dict[str, Command] = {
    "help":         HelpCommand(lambda: COMMANDS),
    "clear":        ClearCommand(),
    "reload":       ReloadCommand(),
    "config":       ConfigCommand(),
    "edit":         EditCommand(),
    "compact":      CompactCommand(),
    "exit":         ExitCommand(),
    "stop":         StopCommand(),
    "resume":       ResumeCommand(),
    "status":       StatusCommand(),
    "activity":     ActivityCommand(),
    "server":       ServerCommand(),
    "model":        ModelCommand(),
    "tools":        ToolsCommand(),
    "debug":        DebugCommand(),
    "roles":        RolesCommand(),
    "openrouter":   OpenRouterCommand(),
    "cd":           CdCommand(),
    "pwd":          PwdCommand(),
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
    # Re-exported for tests and hosts that import concrete commands.
    "HelpCommand", "ClearCommand", "ReloadCommand", "ConfigCommand", "EditCommand",
    "CompactCommand", "ExitCommand",
    "StopCommand", "ResumeCommand", "StatusCommand", "PwdCommand", "CdCommand",
    "ActivityCommand",
    "ServerCommand", "ServerListCommand", "ServerUseCommand", "ServerEditCommand",
    "ServerRemoveCommand", "ServerInfoCommand",
    "ModelCommand", "ModelListCommand", "ModelUseCommand",
    "RolesCommand",
    "ToolsCommand", "OpenRouterCommand", "OpenRouterBalanceCommand",
    "DebugCommand", "DebugPanelCommand", "DebugGetContextCommand",
    "DebugLogCommand", "DebugSystemPromptCommand",
    "ConversationCommand", "ConversationExportCommand", "ConversationImportCommand",
]

