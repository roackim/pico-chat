"""Legacy role inspection and lifecycle slash command."""

from __future__ import annotations

from typing import List

from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol, Command


class RolesCommand(Command):
    def __init__(self):
        super().__init__("roles", "Select and inspect conversation roles")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness import roles

        if not args or args[0].lower() == "list":
            runtime = ui._active_runtime() if hasattr(ui, "_active_runtime") else None
            active = getattr(getattr(runtime, "agent", None), "role", None)
            active_name = active.name if active else "default"
            lines = [f"active: {active_name}"]
            for name in roles.list_roles():
                role = roles.load_role(name)
                lines.append(f"{name.ljust(14)} {role.description}")
            ui.show_popup("roles", "\n".join(lines), content_padding=0)
            return

        action = args[0].lower()
        if action == "show" and len(args) == 2:
            try:
                role = roles.load_role(args[1])
            except (KeyError, OSError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return
            enabled = ", ".join(sorted(role.enabled_tool_names())) or "none"
            content = (
                f"name: {role.name}\n"
                f"description: {role.description or 'none'}\n"
                f"tools: {enabled}\n\n"
                f"{role.prompt or 'No role-specific prompt.'}"
            )
            ui.show_popup(f"role: {role.name}", content)
            return

        if action == "use" and len(args) == 2:
            runtime = ui._active_runtime() if hasattr(ui, "_active_runtime") else None
            if runtime is None:
                ui.chat_history_panel.add_message(
                    "No active conversation.", msg_type=SysMsgError())
                return
            if runtime.is_generating:
                ui.chat_history_panel.add_message(
                    "Role changes apply after the current response finishes.",
                    msg_type=SysMsgError())
                return
            try:
                role = roles.load_role(args[1])
                runtime.ensure_agent().set_role(role)
            except (KeyError, OSError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return
            ui.chat_history_panel.add_message(f"Active role: {role.name}", msg_type=SysMsg())
            return

        if action == "duplicate" and len(args) in {2, 3}:
            try:
                copy = roles.duplicate_role(args[1], args[2] if len(args) == 3 else None)
            except (KeyError, OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return
            ui.chat_history_panel.add_message(f"Duplicated role: {copy.name}", msg_type=SysMsg())
            return

        if action == "rename" and len(args) == 3:
            try:
                roles.rename_role(args[1], args[2])
            except (KeyError, OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return
            ui.chat_history_panel.add_message(
                f"Renamed role: {args[1]} -> {args[2]}", msg_type=SysMsg())
            return

        if action in {"delete", "remove"} and len(args) == 2:
            try:
                roles.delete_role(args[1])
            except (KeyError, OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return
            ui.chat_history_panel.add_message(f"Deleted role: {args[1]}", msg_type=SysMsg())
            return

        ui.chat_history_panel.add_message(
            "Usage: /roles [list|show NAME|use NAME|duplicate NAME [NEW_NAME]|rename OLD NEW|delete NAME]",
            msg_type=SysMsgError())


__all__ = ["RolesCommand"]
