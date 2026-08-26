from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Union
import asyncio
import json
import subprocess
import os

from pico_chat.ui.tui.colors import RGB, theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError
from pico_chat import pico_cfg

import logging

from .base import ChatUIProtocol, Command, Param, server_name_completions
from .roles import RolesCommand
from .models import ModelCommand

logger = logging.getLogger(__name__)

_server_name_completions = server_name_completions


class HelpCommand(Command):
    def __init__(self):
        super().__init__("help", "Show available commands")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        help_lines = []
        for cmd in sorted(COMMANDS.values(), key=lambda x: x.name):
            if not cmd.name.startswith("_"):
                help_lines.append(f"/{cmd.name.ljust(8)} {cmd.description}")
        ui.show_popup("help", "\n".join(help_lines))


class ClearCommand(Command):
    def __init__(self):
        super().__init__("clear", "Clear chat history")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        ui.chat_history_panel.clear()
        if hasattr(ui.agent, "clear_history"):
            ui.agent.clear_history()
        ui.chat_history_panel.add_message("Conversation cleared.", msg_type=SysMsg())
        if hasattr(ui, "refresh_status_bar"):
            ui.refresh_status_bar()


class CompactCommand(Command):
    def __init__(self):
        super().__init__("compact", "Compact context with an LLM summary marker")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if args:
            ui.chat_history_panel.add_message("Usage: /compact", msg_type=SysMsgError())
            return
        if not hasattr(ui.agent, "compact_history"):
            ui.chat_history_panel.add_message(
                "Compaction is not supported by this agent.", msg_type=SysMsgError())
            return

        placeholder = ui.chat_history_panel.add_message(
            "Compacting history...", msg_type=SysMsg(), title="compact")
        try:
            result = await ui.agent.compact_history()
            if not result.get("ok"):
                compact_msg = ui.chat_history_panel.new_message(
                    result.get("message", "Compaction skipped."),
                    msg_type=SysMsg(), title="compact")
                ui.chat_history_panel.replace_message(placeholder, compact_msg)
                return
            compact_msg = ui.chat_history_panel.new_message(
                (
                    f"Compaction complete: {result['compacted_messages']} messages summarized\n"
                    f"Inserted marker: {result['message_id']}\n"
                    f"Summary size: {result['summary_chars']:,} chars"
                ),
                msg_type=SysMsg(), title="compact")
            ui.chat_history_panel.replace_message(placeholder, compact_msg)
        except Exception as exc:
            error_msg = ui.chat_history_panel.new_message(
                f"Compaction failed: {exc}", msg_type=SysMsgError(), title="compact")
            ui.chat_history_panel.replace_message(placeholder, error_msg)


class ExitCommand(Command):
    def __init__(self):
        super().__init__("exit", "Close the application")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if ui.compositor:
            ui.compositor.running = False

class StopCommand(Command):
    def __init__(self):
        super().__init__("stop", "Stop current generation")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        # Check if stop_generation method exists (runtime check)
        if hasattr(ui, 'stop_generation'):
            if ui.stop_generation():
                # Message is already appended by the cancelled task handler
                pass
            else:
                ui.chat_history_panel.add_message("No active generation to stop.", msg_type=SysMsg())
        else:
            ui.chat_history_panel.add_message("Stop command not supported by this UI.", msg_type=SysMsg())


class ResumeCommand(Command):
    def __init__(self):
        super().__init__("resume", "Resume a paused generation")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if hasattr(ui, 'handle_resume_action'):
            ui.handle_resume_action(None)
        else:
            ui.chat_history_panel.add_message("Resume not supported.", msg_type=SysMsg())


class StatusCommand(Command):
    def __init__(self):
        super().__init__("status", "Show system and connection status")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        # Show placeholder popup while checking status
        ui.show_popup("status", "Checking server status...")
        
        # Get actual status (may take time if server is unreachable)
        status = await ui.agent.get_status()
        
        # Update popup with actual status
        ui.show_popup("status", self.format_status(status))
        
        logger = logging.getLogger("tui")
        logger.info(f"Server status online: {status['online']}")
        
    
    @staticmethod
    def format_status(status: Dict[str, Any]) -> str:
        status_color = theme.SUCCESS if status["online"] else theme.ERROR
        status_text = "online" if status["online"] else "offline"
        
        color = str(theme.WARNING)
        reset = theme.reset()
        msg  = color + f"Server           : {reset}{status['server_name']} ({status['server_type']})\n"
        msg += color + f"URL              : {reset}{status['base_url']}\n"
        msg += color + f"Status           : {reset}{status_color}{status_text}{reset}\n"
        
        if status_text == "online":
            msg += color + f"Model            : {reset}{status['model']}\n"
            msg += color + f"Context Window   : {reset}{status['context_window']}\n"

            # Add context pressure info if available
            if status.get('context_used') is not None and status.get('context_max') is not None:
                used = status['context_used']
                max_tokens = status['context_max']
                percentage = status.get('context_percentage', 0.0)
                
                # Color code the percentage based on pressure
                if percentage < 50:
                    pressure_color = theme.SUCCESS
                elif percentage < 75:
                    pressure_color = theme.WARNING
                else:
                    pressure_color = theme.ERROR
                
                msg += color + f"Context Usage    : {reset}{used:,} / {max_tokens:,} tokens "
                msg += f"({pressure_color}{percentage:.1f}%{reset})\n"
        
        return msg


from .server import (
    ServerAddCommand,
    ServerCommand,
    ServerInfoCommand,
    ServerListCommand,
    ServerRemoveCommand,
    ServerUseCommand,
)


class ToolsCommand(Command):
    def __init__(self):
        super().__init__("tools", "Show available tools and their permissions")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.tool_permissions import permissions

        available_tools: List[str] = []
        if hasattr(ui.agent, 'tools_map') and isinstance(ui.agent.tools_map, dict):
            available_tools = sorted(ui.agent.tools_map.keys())

        if not available_tools:
            available_tools = ["read", "write", "patch", "run"]

        def permission_label(tool_name: str) -> str:
            if tool_name == "read":
                return f"inside={permissions.read.inside_repo} outside={permissions.read.outside_repo}"
            if tool_name == "write":
                return f"inside={permissions.write.inside_repo} outside={permissions.write.outside_repo}"
            if tool_name == "patch":
                return f"inside={permissions.patch.inside_repo} outside={permissions.patch.outside_repo}"
            if tool_name == "run":
                return (
                    f"allow={len(permissions.run.allow)} ask={len(permissions.run.ask)} "
                    f"deny={len(permissions.run.deny)} others={permissions.run.others} chain={permissions.run.chain_policy}"
                )
            return "unknown"

        lines = [f"profile: {permissions.name}"]
        for tool_name in available_tools:
            lines.append(f"{tool_name.ljust(10)} - {permission_label(tool_name)}")

        ui.show_popup("tools", "\n".join(lines))

from .debug import (
    DebugCommand,
    DebugGetContextCommand,
    DebugLogCommand,
    DebugPanelCommand,
)


from .permissions import PermissionsCommand

class OpenRouterBalanceCommand(Command):
    def __init__(self):
        super().__init__("balance", "Show OpenRouter account credit balance")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.server_service import ServerService

        # Balance is transient account information, so keep it in a modal
        # rather than adding a permanent chat-history message.
        ui.show_popup("OpenRouter balance", "Fetching balance...")

        svc = ServerService()
        ok, message, balance = await svc.get_openrouter_balance()

        if not ok:
            ui.show_popup("OpenRouter balance", message)
            return

        if balance.remaining > 5:
            status = "healthy"
        elif balance.remaining > 1:
            status = "low"
        else:
            status = "critical"

        content = (
            f"Status           : {status}\n"
            f"Remaining        : ${balance.remaining:.4f}\n"
            f"Total credits    : ${balance.total_credits:.4f}\n"
            f"Total usage      : ${balance.total_usage:.4f}"
        )
        ui.show_popup("OpenRouter balance", content)


class OpenRouterCommand(Command):
    def __init__(self):
        subcommands = {
            "balance": OpenRouterBalanceCommand(),
        }
        super().__init__("openrouter", "OpenRouter account utilities", subcommands=subcommands)

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            help_text = "Usage: /openrouter <subcommand>\n\nSubcommands:\n"
            for name, cmd in sorted(self.subcommands.items()):
                help_text += f"  {name.ljust(10)} - {cmd.description}\n"
            ui.chat_history_panel.add_message(help_text.rstrip(), msg_type=SysMsgError())
        else:
            subcmd_name = args[0].lower()
            if subcmd_name in self.subcommands:
                await self.subcommands[subcmd_name].execute(ui, args[1:])
            else:
                ui.chat_history_panel.add_message(
                    f"Unknown subcommand: {subcmd_name}\n"
                    f"Available: {', '.join(sorted(self.subcommands.keys()))}",
                    msg_type=SysMsgError(),
                )


class PwdCommand(Command):
    def __init__(self):
        super().__init__("pwd", "Show current workspace directory")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        workspace = ui.agent.workspace if hasattr(ui.agent, 'workspace') else "unknown"
        ui.chat_history_panel.add_message(workspace, msg_type=SysMsg(), title="pwd")


class CdCommand(Command):
    def __init__(self):
        super().__init__("cd", "Change workspace directory and rebuild context", params=[
            Param("DIR", path=True),
        ])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /cd <path>",
                msg_type=SysMsgError()
            )
            return

        path = " ".join(args)

        try:
            warnings = ui.agent.switch_workspace(path)
            workspace = ui.agent.workspace

            ui.chat_history_panel.add_message(
                workspace,
                msg_type=SysMsg(),
                title="cd"
            )

            from pico_chat.ui.tui.msg_types import SysMsgWarning
            for w in warnings:
                ui.chat_history_panel.add_message(w, msg_type=SysMsgWarning())

        except (ValueError, OSError, PermissionError) as e:
            ui.chat_history_panel.add_message(str(e), msg_type=SysMsgError())


from .conversation import (
    ConversationCommand,
    ConversationExportCommand,
    ConversationImportCommand,
)


from .tabs import (
    TabCloseCommand,
    TabCommand,
    TabListCommand,
    TabNewCommand,
    TabSwitchCommand,
)


# Command Registry
COMMANDS: Dict[str, Command] = {
    "help":        HelpCommand(),
    "clear":       ClearCommand(),
    "compact":     CompactCommand(),
    "exit":        ExitCommand(),
    "stop":        StopCommand(),
    "resume":      ResumeCommand(),
    "status":      StatusCommand(),
    "server":      ServerCommand(),
    "model":       ModelCommand(),
    "tools":       ToolsCommand(),
    "debug":       DebugCommand(),
    "permissions": PermissionsCommand(),
    "roles":       RolesCommand(),
    "openrouter":  OpenRouterCommand(),
    "cd":          CdCommand(),
    "pwd":         PwdCommand(),
    "conversation": ConversationCommand(),
    "tab":         TabCommand(),
}

async def handle_command(ui: ChatUIProtocol, text: str):
    parts = text.strip().split()
    if not parts:
        return
    
    cmd_name = parts[0][1:].lower() # Remove '/'
    args = parts[1:]
    
    if cmd_name in COMMANDS:
        await COMMANDS[cmd_name].execute(ui, args)
    else:
        ui.chat_history_panel.add_message(
            f"Unknown command: /{cmd_name}",
            msg_type=SysMsgError(),
        )
        

def get_command_list() -> List[str]:
    """Get list of top-level commands."""
    return [cmd for cmd in COMMANDS.keys()]

def get_subcommand_list(command: str) -> List[str]:
    """Get list of subcommands for a given command."""
    if command in COMMANDS:
        cmd = COMMANDS[command]
        if cmd.has_subcommands():
            return list(cmd.subcommands.keys())
    return []
