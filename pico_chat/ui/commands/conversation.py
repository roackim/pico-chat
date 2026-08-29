"""Conversation import and export commands."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from .base import ChatUIProtocol, Command, Param
from pico_chat.ui.tui.msg_types import (
    PicoMsg,
    SysMsg,
    SysMsgError,
    SysMsgWarning,
    ThinkingMsg,
    ToolCallMsg,
    UserMsg,
)


def json_file_completions() -> List[str]:
    """List ``.json`` files in the current directory for fuzzy autocomplete."""
    try:
        return sorted(
            entry.name for entry in os.scandir(".")
            if entry.is_file() and entry.name.endswith(".json")
        )
    except OSError:
        return []


class ConversationExportCommand(Command):
    def __init__(self):
        super().__init__("export", "Export conversation history to a JSON file", params=[
            Param("FILENAME", required=True),
        ])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /conversation export <filename>", msg_type=SysMsgError())
            return

        filename = args[0]
        if not filename.endswith(".json"):
            filename += ".json"

        try:
            history = ui.agent.history
            if not history:
                ui.chat_history_panel.add_message(
                    "No conversation history to export.", msg_type=SysMsgError())
                return

            active_role = getattr(getattr(ui.agent, "role", None), "name", "default")
            with open(filename, "w", encoding="utf-8") as stream:
                json.dump({"role": active_role, "history": history}, stream,
                          indent=2, ensure_ascii=False)
            ui.chat_history_panel.add_message(
                f"Conversation exported to {filename}\n({len(history)} messages)",
                msg_type=SysMsg(), title="conversation")
        except Exception as exc:
            ui.chat_history_panel.add_message(
                f"Export failed: {exc}", msg_type=SysMsgError(), title="conversation")


class ConversationImportCommand(Command):
    def __init__(self):
        super().__init__("import", "Import conversation history from a JSON file", params=[
            Param("FILENAME", required=True, completions=json_file_completions),
        ])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /conversation import <filename>", msg_type=SysMsgError())
            return

        filename = args[0]
        if not filename.endswith(".json"):
            filename += ".json"

        try:
            with open(filename, "r", encoding="utf-8") as stream:
                data = json.load(stream)

            role_name = data.get("role") if isinstance(data, dict) else None
            history = data.get("history") if isinstance(data, dict) else data
            if not isinstance(history, list):
                ui.chat_history_panel.add_message(
                    "Invalid conversation file: expected a history array or conversation object",
                    msg_type=SysMsgError(), title="conversation")
                return
            if role_name is not None and not isinstance(role_name, str):
                ui.chat_history_panel.add_message(
                    "Invalid conversation file: role must be a string",
                    msg_type=SysMsgError(), title="conversation")
                return
            for index, message in enumerate(history):
                if not isinstance(message, dict):
                    ui.chat_history_panel.add_message(
                        f"Invalid message at index {index}: expected an object",
                        msg_type=SysMsgError(), title="conversation")
                    return
                if "role" not in message:
                    ui.chat_history_panel.add_message(
                        f"Invalid message at index {index}: missing 'role' field",
                        msg_type=SysMsgError(), title="conversation")
                    return

            # Apply the saved role, warning if it no longer exists.
            role_warning = None
            if role_name:
                from pico_chat.harness import roles
                runtime = ui._active_runtime() if hasattr(ui, "_active_runtime") else None
                try:
                    role = roles.load_role(role_name)
                    if runtime is not None:
                        runtime.switch_role(role)
                    else:
                        ui.agent.set_role(role)
                except KeyError:
                    default_role = roles.load_role("default")
                    if runtime is not None:
                        runtime.switch_role(default_role)
                    else:
                        ui.agent.set_role(default_role)
                    role_warning = (
                        f"Role '{role_name}' no longer exists — defaulted to 'default'."
                    )

            ui.agent.history = history
            ui.chat_history_panel.clear()
            self._rebuild_ui_from_history(ui, history)
            if hasattr(ui, "refresh_status_bar"):
                ui.refresh_status_bar()
            if role_warning:
                ui.chat_history_panel.add_message(
                    role_warning, msg_type=SysMsgWarning(), title="conversation")
            ui.chat_history_panel.add_message(
                f"Conversation imported from {filename}\n({len(history)} messages)",
                msg_type=SysMsg(), title="conversation")
        except FileNotFoundError:
            ui.chat_history_panel.add_message(
                f"File not found: {filename}", msg_type=SysMsgError(), title="conversation")
        except json.JSONDecodeError as exc:
            ui.chat_history_panel.add_message(
                f"Invalid JSON file: {exc}", msg_type=SysMsgError(), title="conversation")
        except Exception as exc:
            ui.chat_history_panel.add_message(
                f"Import failed: {exc}", msg_type=SysMsgError(), title="conversation")

    def _rebuild_ui_from_history(self, ui: ChatUIProtocol, history: List[Dict[str, Any]]):
        """Reconstruct visible messages from imported harness history."""
        from pico_chat.harness.thinking_parser import ThinkingTagParser

        for message in history:
            role = message.get("role", "")
            content = message.get("content", "")
            message_id = message.get("id", "")
            ids = [message_id] if message_id else None

            if role == "user":
                ui.chat_history_panel.add_message(content or "", msg_type=UserMsg(),
                                                  harness_message_ids=ids)
            elif role == "assistant":
                # Split thinking/content using the same tag parser the harness
                # uses, so imported reasoning renders as a ThinkingMsg.
                # content may be None for tool-call-only assistant messages.
                content = content or ""
                parser = ThinkingTagParser()
                segments = parser.feed(content) + parser.flush()
                for segment in segments:
                    if not segment.text:
                        continue
                    if segment.is_thinking:
                        ui.chat_history_panel.add_message(
                            segment.text, msg_type=ThinkingMsg(), harness_message_ids=ids)
                    else:
                        ui.chat_history_panel.add_message(
                            segment.text, msg_type=PicoMsg(), harness_message_ids=ids)
                if not segments and content:
                    ui.chat_history_panel.add_message(
                        content, msg_type=PicoMsg(), harness_message_ids=ids)
                for tool_call in message.get("tool_calls", []):
                    if not isinstance(tool_call, dict) or "function" not in tool_call:
                        continue
                    function = tool_call["function"]
                    tool_call_id = tool_call.get("id", "")
                    tool_message = ui.chat_history_panel.add_message(
                        "", msg_type=ToolCallMsg(),
                        harness_message_ids=[tool_call_id] if tool_call_id else None)
                    tool_message.tool_name = function.get("name", "unknown")
                    tool_message.tool_args = function.get("arguments", "{}")
                    tool_message.tool_status = "completed"
                    tool_message.show_output = False
                    tool_message.rebuild_tool_display()
                    tool_message.finalize()
            elif role == "tool" and content:
                tool_call_id = message.get("tool_call_id", "")
                found = False
                for existing in reversed(ui.chat_history_panel.messages):
                    if (isinstance(existing.type, ToolCallMsg)
                            and tool_call_id
                            and tool_call_id in existing.harness_message_ids):
                        existing.tool_output = content
                        existing.tool_status = "completed"
                        existing.show_output = False
                        existing.rebuild_tool_display()
                        found = True
                        break
                if not found:
                    ui.chat_history_panel.add_message(
                        f"Tool result: {content[:200]}{'...' if len(content) > 200 else ''}",
                        msg_type=SysMsg())


class ConversationCommand(Command):
    def __init__(self):
        super().__init__(
            "conversation",
            "Conversation management (export/import)",
            subcommands={
                "export": ConversationExportCommand(),
                "import": ConversationImportCommand(),
            },
        )

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            help_text = "Usage: /conversation <subcommand>\n\nSubcommands:\n"
            for name, command in sorted(self.subcommands.items()):
                help_text += f"  {name.ljust(10)} - {command.description}\n"
            ui.chat_history_panel.add_message(help_text.rstrip(), msg_type=SysMsgError())
            return

        subcommand = args[0].lower()
        if subcommand in self.subcommands:
            await self.subcommands[subcommand].execute(ui, args[1:])
            return
        ui.chat_history_panel.add_message(
            f"Unknown subcommand: {subcommand}\n"
            f"Available: {', '.join(sorted(self.subcommands.keys()))}",
            msg_type=SysMsgError(),
        )

__all__ = [
    "ConversationCommand", "ConversationExportCommand", "ConversationImportCommand",
]
