"""Role and permission management command.

There is a single policy surface: the role editor.  The settings tab and this
``/permissions`` popup both build it from
:func:`pico_chat.ui.settings_pages.build_roles_fields`, so they cannot drift.
"""
from __future__ import annotations

from typing import List

from pico_chat.ui.tui.msg_types import SysMsg

from .base import ChatUIProtocol, Command


class PermissionsCommand(Command):
    def __init__(self):
        super().__init__("permissions", "Edit the active conversation role and its tool policies")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.ui.settings_pages import build_roles_fields

        runtime = ui._active_runtime() if hasattr(ui, "_active_runtime") else None
        agent = getattr(runtime, "agent", None) if runtime is not None else getattr(ui, "agent", None)
        if agent is None and runtime is not None:
            agent = runtime.ensure_agent()

        def notify(message: str, msg_type=SysMsg()):
            ui.chat_history_panel.add_message(message, msg_type=msg_type)

        fields, save_role = build_roles_fields(
            runtime,
            agent,
            notify=notify,
            on_role_change=getattr(ui, "refresh_status_bar", None),
            history_panel=ui.chat_history_panel,
        )

        ui.show_form_popup("Permissions", fields, lambda _values: save_role(), field_spacing=0)


__all__ = ["PermissionsCommand"]
