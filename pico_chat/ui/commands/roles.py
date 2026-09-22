"""Role inspection and lifecycle slash command."""

from __future__ import annotations

from typing import List

from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol


async def cmd_roles(ui: ChatUIProtocol, args: List[str]):
    from pico_chat.harness import roles

    if not args or args[0].lower() == "list":
        active = getattr(getattr(ui, "agent", None), "role", None)
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
        try:
            role = roles.load_role(args[1])
            ui.switch_role(role)
        except (KeyError, OSError, TypeError, RuntimeError) as exc:
            ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
            return
        ui.chat_history_panel.add_message(f"Active role: {role.name}", msg_type=SysMsg())
        if hasattr(ui, "refresh_status_bar"):
            ui.refresh_status_bar()
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

    if action == "edit" and len(args) in {1, 2}:
        from pico_chat import pico_cfg
        from pico_chat.ui.external_editor import open_editor, resolve_editor

        if not resolve_editor():
            ui.chat_history_panel.add_message(
                "No editor found. Set $VISUAL or $EDITOR.", msg_type=SysMsgError())
            return
        directory = pico_cfg.ensure_roles_dir()
        if len(args) == 1:
            # No name: open the shipped example to copy from.
            open_editor(ui, directory / pico_cfg.ROLE_EXAMPLE_FILENAME)
            return
        name = args[1]
        try:
            path = pico_cfg.get_role_path(roles._validate_name(name))
        except ValueError as exc:
            ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
            return
        if not path.exists():
            # Materialize the current (built-in or default) policy so the
            # file starts from the effective role, not a blank template.
            try:
                roles.save_role(roles.load_role(name))
            except KeyError:
                path.write_text(
                    pico_cfg.DEFAULT_ROLE_TOML.replace("disabled = true\n", ""),
                    encoding="utf-8",
                )
        open_editor(ui, path)
        ui.chat_history_panel.add_message(
            f"Edited role '{name}'.", msg_type=SysMsg())
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
        "Usage: /roles [list|show NAME|use NAME|edit|duplicate NAME [NEW_NAME]|rename OLD NEW|delete NAME]",
        msg_type=SysMsgError())


__all__ = ["cmd_roles"]
