"""Conversation tab commands."""

from __future__ import annotations

from typing import List

from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol, Command, Param


class TabNewCommand(Command):
    def __init__(self):
        super().__init__("new", "Create a new conversation tab", params=[Param("NAME")])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if hasattr(ui, "_new_tab"):
            ui._new_tab(" ".join(args) if args else None)
            ui.chat_history_panel.add_message(
                f"New tab created ({len(ui._tabs)} tabs open)", msg_type=SysMsg(), title="tab")
        else:
            ui.chat_history_panel.add_message("Tab management not available.", msg_type=SysMsgError())


class TabCloseCommand(Command):
    def __init__(self):
        super().__init__("close", "Close the current conversation tab")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if hasattr(ui, "_close_tab"):
            ui._close_tab(ui._active_tab_index)
        else:
            ui.chat_history_panel.add_message("Tab management not available.", msg_type=SysMsgError())


class TabSwitchCommand(Command):
    def __init__(self):
        super().__init__("switch", "Switch to a tab by number", params=[Param("INDEX", required=True)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /tab switch <number>", msg_type=SysMsgError())
            return
        try:
            index = int(args[0]) - 1
            if not hasattr(ui, "_on_tab_select"):
                ui.chat_history_panel.add_message("Tab management not available.", msg_type=SysMsgError())
            elif 0 <= index < len(ui._tabs):
                ui._on_tab_select(index)
            else:
                ui.chat_history_panel.add_message(
                    f"Tab {args[0]} does not exist. Use /tab list to see tabs.", msg_type=SysMsgError())
        except ValueError:
            ui.chat_history_panel.add_message(f"Invalid tab number: {args[0]}", msg_type=SysMsgError())


class TabListCommand(Command):
    def __init__(self):
        super().__init__("list", "List all open tabs")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not getattr(ui, "_tabs", None):
            ui.chat_history_panel.add_message("No tabs open.", msg_type=SysMsg())
            return
        lines = ["Open tabs:\n"]
        for index, tab in enumerate(ui._tabs):
            marker = "→ " if index == ui._active_tab_index else "  "
            lines.append(f"{marker}{index + 1}. {tab.name} ({len(tab.messages)} messages, {len(tab.harness_history)} history entries)")
        lines.append("\nUse /tab switch <n> to switch, /tab close to close current")
        ui.chat_history_panel.add_message("\n".join(lines), msg_type=SysMsg(), title="tab")


class TabCommand(Command):
    def __init__(self):
        close = TabCloseCommand()
        super().__init__("tab", "Conversation tab management", subcommands={
            "new": TabNewCommand(), "close": close, "switch": TabSwitchCommand(), "list": TabListCommand(),
        })

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            help_text = "Usage: /tab <subcommand>\n\nSubcommands:\n"
            for name, command in sorted(self.subcommands.items()):
                help_text += f"  {name.ljust(10)} - {command.description}\n"
            ui.chat_history_panel.add_message(help_text.rstrip(), msg_type=SysMsgError())
        elif args[0].lower() in self.subcommands:
            await self.subcommands[args[0].lower()].execute(ui, args[1:])
        else:
            ui.chat_history_panel.add_message(
                f"Unknown subcommand: {args[0].lower()}\nAvailable: {', '.join(sorted(self.subcommands))}",
                msg_type=SysMsgError())

__all__ = [
    "TabCommand", "TabNewCommand", "TabCloseCommand", "TabSwitchCommand",
    "TabListCommand",
]
