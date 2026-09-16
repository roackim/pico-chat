"""Command registry: the single assembly point for all slash commands.

Each command lives in a module named after its domain (``core``, ``server``,
``models``, ``roles``, ``debug``, ``permissions``, ``settings``,
``conversation``, ``tabs``, ``tools``, ``openrouter``). Those modules depend
only on :mod:`pico_chat.ui.commands.base`; this module is the only place that
knows about all of them, which keeps the import graph acyclic.
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
    CdCommand,
    ClearCommand,
    CompactCommand,
    ExitCommand,
    HelpCommand,
    PwdCommand,
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
from .permissions import PermissionsCommand
from .roles import RolesCommand
from .server import (
    ServerAddCommand,
    ServerCommand,
    ServerInfoCommand,
    ServerListCommand,
    ServerRemoveCommand,
)
from .settings import SettingsCommand
from .tabs import (
    TabCloseCommand,
    TabCommand,
    TabListCommand,
    TabNewCommand,
    TabSwitchCommand,
)
from .tools import ToolsCommand

# Command Registry
COMMANDS: Dict[str, Command] = {
    "help":         HelpCommand(lambda: COMMANDS),
    "clear":        ClearCommand(),
    "compact":      CompactCommand(),
    "exit":         ExitCommand(),
    "stop":         StopCommand(),
    "resume":       ResumeCommand(),
    "status":       StatusCommand(),
    "server":       ServerCommand(),
    "model":        ModelCommand(),
    "tools":        ToolsCommand(),
    "debug":        DebugCommand(),
    "permissions":  PermissionsCommand(),
    "settings":     SettingsCommand(),
    "roles":        RolesCommand(),
    "openrouter":   OpenRouterCommand(),
    "cd":           CdCommand(),
    "pwd":          PwdCommand(),
    "conversation": ConversationCommand(),
    "tab":          TabCommand(),
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
    "HelpCommand", "ClearCommand", "CompactCommand", "ExitCommand",
    "StopCommand", "ResumeCommand", "StatusCommand", "PwdCommand", "CdCommand",
    "ServerCommand", "ServerAddCommand", "ServerListCommand",
    "ServerRemoveCommand", "ServerInfoCommand",
    "ModelCommand", "ModelListCommand", "ModelUseCommand",
    "RolesCommand", "PermissionsCommand", "SettingsCommand",
    "ToolsCommand", "OpenRouterCommand", "OpenRouterBalanceCommand",
    "DebugCommand", "DebugPanelCommand", "DebugGetContextCommand",
    "DebugLogCommand", "DebugSystemPromptCommand",
    "ConversationCommand", "ConversationExportCommand", "ConversationImportCommand",
    "TabCommand", "TabNewCommand", "TabCloseCommand", "TabListCommand",
    "TabSwitchCommand",
]

