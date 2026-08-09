"""Debug and tool-inspection commands."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import List

from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol, Command


class DebugPanelCommand(Command):
    def __init__(self):
        super().__init__("panel", "Toggle debug console visibility")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if hasattr(ui, "toggle_debug_console"):
            ui.toggle_debug_console()
        else:
            ui.chat_history_panel.add_message("Debug console not supported.", msg_type=SysMsg())


class DebugGetContextCommand(Command):
    def __init__(self):
        super().__init__("get_context", "Display and copy current LLM context")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        try:
            context = await ui.agent.get_current_context()
            context_json = json.dumps(context, indent=2, ensure_ascii=False)
            lines = ["=" * 80, "CURRENT LLM CONTEXT", "=" * 80, ""]
            for index, message in enumerate(context, 1):
                lines.extend([f"[{index}/{len(context)}] {message.get('role', 'unknown').upper()}",
                              "-" * 80, message.get("content", ""), ""])
            lines.extend(["=" * 80, f"Total messages: {len(context)}",
                          f"Total characters: {len(context_json):,}", "=" * 80])
            ui.chat_history_panel.add_message("\n".join(lines), msg_type=SysMsg())
            for command in (("xclip", "-selection", "clipboard"),
                            ("xsel", "--clipboard", "--input"), ("wl-copy",)):
                try:
                    subprocess.run(command, input=context_json.encode(), check=True,
                                   stderr=subprocess.DEVNULL)
                    ui.chat_history_panel.add_message("JSON also copied to clipboard", msg_type=SysMsg())
                    break
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
        except Exception as exc:
            logging.getLogger("tui").error("Error getting context: %s", exc, exc_info=True)
            ui.chat_history_panel.add_message(f"Failed to get context: {exc}", msg_type=SysMsgError())


class DebugLogCommand(Command):
    def __init__(self):
        super().__init__("log", "Show recent log messages (default: 50, max: 200)")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        try:
            count = max(1, min(200, int(args[0]))) if args else 50
        except ValueError:
            ui.chat_history_panel.add_message(
                f"Invalid number: {args[0]}. Usage: /debug log [lines]", msg_type=SysMsgError())
            return
        lines = list(getattr(getattr(ui, "debug_panel", None), "lines", []))
        if not lines:
            ui.chat_history_panel.add_message("No log messages available.", msg_type=SysMsg())
            return
        recent = lines[-count:]
        ui.chat_history_panel.add_message(
            f"Last {len(recent)} log messages:\n{'-' * 80}\n" + "\n".join(recent),
            msg_type=SysMsg(), title="logs")


class DebugCommand(Command):
    def __init__(self):
        super().__init__("debug", "Debug utilities", subcommands={
            "panel": DebugPanelCommand(), "get_context": DebugGetContextCommand(),
            "log": DebugLogCommand(),
        })

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.show_popup("debug", "Missing subcommand. Available subcommands:\n" +
                          "\n".join(f"  {name.ljust(15)} - {command.description}"
                                    for name, command in sorted(self.subcommands.items())))
        elif args[0].lower() in self.subcommands:
            await self.subcommands[args[0].lower()].execute(ui, args[1:])
        else:
            ui.chat_history_panel.add_message(f"Unknown subcommand: {args[0]}", msg_type=SysMsgError())


from .builtins import ToolsCommand

__all__ = [
    "ToolsCommand", "DebugCommand", "DebugPanelCommand",
    "DebugGetContextCommand", "DebugLogCommand",
]
