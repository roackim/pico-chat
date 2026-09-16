"""Core chat and application commands.

These are the commands that operate on the conversation itself or the
application lifecycle, independent of any particular subsystem (servers,
models, roles, tabs, …).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError, SysMsgWarning

from .base import ChatUIProtocol, Command, Param

logger = logging.getLogger(__name__)


class HelpCommand(Command):
    """List every registered command.

    The registry is injected as a callable rather than imported, so this
    module never depends on :mod:`pico_chat.ui.commands.registry` (which
    imports this one).
    """

    def __init__(self, registry: Optional[Callable[[], Dict[str, Command]]] = None):
        super().__init__("help", "Show available commands")
        self._registry = registry

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        commands = self._registry() if callable(self._registry) else {}
        help_lines = []
        for cmd in sorted(commands.values(), key=lambda x: x.name):
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
        if hasattr(ui, "stop_generation"):
            if ui.stop_generation():
                # Message is already appended by the cancelled task handler
                pass
            else:
                ui.chat_history_panel.add_message(
                    "No active generation to stop.", msg_type=SysMsg())
        else:
            ui.chat_history_panel.add_message(
                "Stop command not supported by this UI.", msg_type=SysMsg())


class ResumeCommand(Command):
    def __init__(self):
        super().__init__("resume", "Resume a paused generation")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if hasattr(ui, "handle_resume_action"):
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

        logger.info("Server status online: %s", status["online"])

    @staticmethod
    def format_status(status: Dict[str, Any]) -> str:
        status_color = theme.SUCCESS if status["online"] else theme.ERROR
        status_text = "online" if status["online"] else "offline"

        color = str(theme.WARNING)
        reset = theme.reset()
        msg = color + f"Server           : {reset}{status['server_name']} ({status['server_type']})\n"
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
            ui.chat_history_panel.add_message("Usage: /cd <path>", msg_type=SysMsgError())
            return

        path = " ".join(args)

        try:
            warnings = ui.agent.switch_workspace(path)
            workspace = ui.agent.workspace

            ui.chat_history_panel.add_message(workspace, msg_type=SysMsg(), title="cd")

            for warning in warnings:
                ui.chat_history_panel.add_message(warning, msg_type=SysMsgWarning())

        except (ValueError, OSError, PermissionError) as e:
            ui.chat_history_panel.add_message(str(e), msg_type=SysMsgError())


__all__ = [
    "HelpCommand", "ClearCommand", "CompactCommand", "ExitCommand",
    "StopCommand", "ResumeCommand", "StatusCommand", "PwdCommand", "CdCommand",
]
