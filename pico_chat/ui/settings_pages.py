"""Reusable builders for settings pages.

Each builder wires an editor model to form fields and returns the field list
plus a save callback.  They are shared by the ``/permissions`` and ``/roles``
popup commands and the settings tab, so both surfaces stay behaviorally
identical.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError


Notify = Callable[[str, object], None]


def _noop_notify(message: str, msg_type=SysMsg()):
    pass


def build_permission_fields(notify: Notify = _noop_notify
                            ) -> Tuple[list, Callable[[], None]]:
    """Build the permission-profile fields plus their save callback.

    Re-exported from the commands package so hosts have one import site for
    settings page builders.
    """
    from pico_chat.ui.commands.permissions import build_permission_fields
    return build_permission_fields(notify=notify)


def build_roles_fields(runtime, agent, notify: Notify = _noop_notify,
                       on_role_change: Optional[Callable[[], None]] = None,
                       history_panel=None,
                       ) -> Tuple[list, Callable[[], None]]:
    """Build the role-editor fields plus their save callback.

    ``runtime``/``agent`` provide the live conversation context (either may be
    ``None``; the editor then operates on the agent only).  ``on_role_change``
    is invoked whenever the active role changes so hosts can refresh derived
    UI such as the status bar.
    """
    from pico_chat.ui.role_editor_form import RoleEditorForm
    from pico_chat.ui.role_editor_model import RoleEditorModel
    from pico_chat.ui.conversation_runtime import _show_role_change

    role_panel = history_panel if history_panel is not None else _HistoryShim(notify)

    active_role = getattr(agent, "role", None)
    editor = RoleEditorModel(active_role.name if active_role else "default")
    role_form = RoleEditorForm(editor)
    fields = role_form.fields
    role_options = fields[0].options

    def field(label: str):
        return role_form.field(label)

    def sync_fields(role):
        role_form.sync(role)

    def save_role(*_args):
        updated = role_form.apply()
        if runtime is not None:
            try:
                runtime.switch_role(updated)
            except RuntimeError as exc:
                notify(str(exc), SysMsgError())
                return
        elif agent is not None:
            previous_name = getattr(getattr(agent, "role", None), "name", "default")
            agent.set_role(updated)
            _show_role_change(role_panel, previous_name, updated.name)
        if on_role_change is not None:
            on_role_change()
        if updated.name not in role_options:
            role_options.append(updated.name)
            field("available_roles").options = role_options
        field("available_roles").set_value(role_options.index(updated.name))

    def select_role(name: str):
        try:
            selected = editor.select(name)
            if runtime is not None:
                runtime.switch_role(selected)
            elif agent is not None:
                previous_name = getattr(getattr(agent, "role", None), "name", "default")
                agent.set_role(selected)
                _show_role_change(role_panel, previous_name, selected.name)
            if on_role_change is not None:
                on_role_change()
            sync_fields(selected)
        except (KeyError, OSError, TypeError) as exc:
            notify(str(exc), SysMsgError())
        except RuntimeError as exc:
            notify(str(exc), SysMsgError())

    def create_role():
        try:
            created = editor.create()
            role_options.append(created.name)
            field("available_roles").options = role_options
            field("available_roles").set_value(role_options.index(created.name))
            sync_fields(created)
        except (KeyError, OSError, ValueError, TypeError) as exc:
            notify(str(exc), SysMsgError())

    def duplicate_role(name: str):
        try:
            copied = editor.duplicate(name)
            role_options.append(copied.name)
            field("available_roles").options = role_options
            field("available_roles").set_value(role_options.index(copied.name))
            sync_fields(copied)
        except (KeyError, OSError, ValueError, TypeError) as exc:
            notify(str(exc), SysMsgError())

    def rename_role(old_name: str, new_name: str) -> bool:
        try:
            renamed = editor.rename(new_name, old_name)
            index = role_options.index(old_name)
            role_options[index] = renamed.name
            field("available_roles").options = role_options
            field("available_roles").set_value(index)
            sync_fields(renamed)
            return True
        except (KeyError, OSError, ValueError, TypeError) as exc:
            notify(str(exc), SysMsgError())
            return False

    def remove_role(name: str):
        if len(role_options) <= 1:
            notify("At least one role must remain.", SysMsgError())
            return
        # Deletion is immediate in the settings tab; the popup command wraps
        # this with a confirmation dialog.
        remove_role_now(name)

    def remove_role_now(name: str):
        try:
            replacement = editor.remove(name)
            active_runtime_role = getattr(agent, "role", None)
            if active_runtime_role is not None and active_runtime_role.name == name:
                if runtime is not None:
                    try:
                        runtime.switch_role(replacement)
                    except RuntimeError as exc:
                        notify(str(exc), SysMsgError())
                        return
                elif agent is not None:
                    previous_name = getattr(getattr(agent, "role", None), "name", "default")
                    agent.set_role(replacement)
                    _show_role_change(role_panel, previous_name, replacement.name)
                if on_role_change is not None:
                    on_role_change()
            role_options.remove(name)
            field("available_roles").options = role_options
            field("available_roles").set_value(role_options.index(replacement.name))
            sync_fields(replacement)
        except (KeyError, OSError, ValueError, TypeError) as exc:
            notify(str(exc), SysMsgError())

    fields[0]._on_select = select_role
    fields[0]._on_create = create_role
    fields[0]._on_duplicate = duplicate_role
    fields[0]._on_rename = rename_role
    fields[0]._on_remove = remove_role
    role_form.set_on_change(save_role)

    # Role prompt: plain Enter commits (saves) the role; Alt+Enter inserts a
    # newline.  Only wired here (settings tab), not in the popup command.
    prompt_field = role_form.field("role_prompt")
    if hasattr(prompt_field, "_editor"):
        prompt_field._editor.on_submit = save_role

    return fields, save_role


class _HistoryShim:
    """Minimal chat-history stand-in for ``_show_role_change``."""

    def __init__(self, notify: Notify):
        self._notify = notify

    def add_message(self, text: str, **kwargs):
        self._notify(text, kwargs.get("msg_type", SysMsg()))


def settings_pages(runtime=None, agent=None, notify: Notify = _noop_notify,
                   on_role_change: Optional[Callable[[], None]] = None,
                   history_panel=None) -> list:
    """Assemble the default settings pages (permissions, roles)."""
def settings_pages(runtime=None, agent=None, notify: Notify = _noop_notify,
                   on_role_change: Optional[Callable[[], None]] = None,
                   history_panel=None) -> list:
    """Assemble the default settings pages.

    A single **roles** page is the settings surface: a role already carries
    every policy the old standalone permissions page offered (read/write/patch
    inside + outside, unknown commands, command chains, container flags) plus
    the role itself.  The permissions popup command is unchanged and still
    delegates to its own builder.
    """
    from pico_chat.ui.tui.components.settings_panel import SettingsPage

    return [
        SettingsPage(
            "roles",
            lambda: build_roles_fields(runtime, agent, notify=notify,
                                       on_role_change=on_role_change,
                                       history_panel=history_panel)[0],
            title="Roles",
            description="Conversation roles and their tool policies. "
                        "Switching a role applies it to the active conversation.",
        ),
    ]


__all__ = ["build_permission_fields", "build_roles_fields", "settings_pages"]
