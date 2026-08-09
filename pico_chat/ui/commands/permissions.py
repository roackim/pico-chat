"""Permission and role management commands."""
from __future__ import annotations
from typing import List
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError
from .base import ChatUIProtocol, Command

class PermissionsCommand(Command):
    def __init__(self):
        super().__init__("permissions", "Edit the active conversation role and its tool policies")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness import tool_permissions

        if not args:
            await self._execute_role_editor(ui)
            return

        if args:
            action = args[0].lower()
            if action == "list":
                names = tool_permissions.list_profiles()
                ui.show_popup("permission profiles", "\n".join(names) if names else "No saved profiles.",
                              content_padding=0)
                return
            if action == "rename":
                if len(args) != 3:
                    ui.chat_history_panel.add_message(
                        "Usage: /permissions rename OLD_NAME NEW_NAME", msg_type=SysMsgError())
                    return
                try:
                    tool_permissions.rename_profile(args[1], args[2])
                    ui.chat_history_panel.add_message(
                        f"Renamed permission profile: {args[1]} → {args[2]}", msg_type=SysMsg())
                except (KeyError, OSError, ValueError, TypeError) as exc:
                    ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return
            if action in {"load", "save"}:
                if len(args) != 2:
                    ui.chat_history_panel.add_message(
                        f"Usage: /permissions {action} NAME", msg_type=SysMsgError())
                    return
                try:
                    if action == "load":
                        tool_permissions.apply_profile(tool_permissions.load_profile(args[1]))
                        message = f"Loaded permission profile: {args[1]}"
                    else:
                        tool_permissions.save_profile(args[1])
                        message = f"Saved permission profile: {args[1]}"
                    ui.chat_history_panel.add_message(message, msg_type=SysMsg())
                except (KeyError, OSError, ValueError, TypeError) as exc:
                    ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return

        perm = tool_permissions.permissions
        from pico_chat.ui.tui.components.form import (
            FormSectionTitle, InlineChoiceField, ProfileList, ToggleField,
        )
        from pico_chat.ui.profile_editor_model import ProfileEditorModel

        policies = ["allow", "ask", "deny"]
        policy_colors = {"allow": theme.SUCCESS, "deny": theme.ERROR}
        labels = {
            "read_inside_repo": "Read inside repo",
            "read_outside_repo": "Read outside repo",
            "write_inside_repo": "Write inside repo",
            "write_outside_repo": "Write outside repo",
            "patch_inside_repo": "Patch inside repo",
            "patch_outside_repo": "Patch outside repo",
            "search": "Search",
            "unknown_commands": "Unknown commands",
            "command_chains": "Command chains",
            "use_container": "Use container",
            "container_network": "Container network",
        }
        editor = ProfileEditorModel()
        profile_options = editor.profile_names()
        def selected(value: str) -> int:
            return policies.index(value)

        fields = [
            ProfileList("Available profiles", options=profile_options, value=0),
            FormSectionTitle("Settings:"),
            InlineChoiceField(labels["read_inside_repo"], options=policies, option_colors=policy_colors, value=selected(perm.read.inside_repo)),
            InlineChoiceField(labels["read_outside_repo"], options=policies, option_colors=policy_colors, value=selected(perm.read.outside_repo)),
            InlineChoiceField(labels["write_inside_repo"], options=policies, option_colors=policy_colors, value=selected(perm.write.inside_repo)),
            InlineChoiceField(labels["write_outside_repo"], options=policies, option_colors=policy_colors, value=selected(perm.write.outside_repo)),
            InlineChoiceField(labels["patch_inside_repo"], options=policies, option_colors=policy_colors, value=selected(perm.patch.inside_repo)),
            InlineChoiceField(labels["patch_outside_repo"], options=policies, option_colors=policy_colors, value=selected(perm.patch.outside_repo)),
            InlineChoiceField(labels["search"], options=policies, option_colors=policy_colors, value=selected(perm.search)),
            InlineChoiceField(labels["unknown_commands"], options=policies, option_colors=policy_colors, value=selected(perm.run.others)),
            InlineChoiceField(labels["command_chains"], options=["ask", "deny"], option_colors=policy_colors, value=["ask", "deny"].index(perm.run.chain_policy)),
            ToggleField(labels["use_container"], value=perm.run.use_container),
            ToggleField(labels["container_network"], value=perm.run.container_network),
        ]
        fields_by_label = {field.label: field for field in fields[2:]}

        def policy(label: str) -> str:
            return fields_by_label[label].get_value()

        def sync_profile(profile) -> None:
            values = {
                labels["read_inside_repo"]: policies.index(profile.read.inside_repo),
                labels["read_outside_repo"]: policies.index(profile.read.outside_repo),
                labels["write_inside_repo"]: policies.index(profile.write.inside_repo),
                labels["write_outside_repo"]: policies.index(profile.write.outside_repo),
                labels["patch_inside_repo"]: policies.index(profile.patch.inside_repo),
                labels["patch_outside_repo"]: policies.index(profile.patch.outside_repo),
                labels["search"]: policies.index(profile.search),
                labels["unknown_commands"]: policies.index(profile.run.others),
                labels["command_chains"]: ["ask", "deny"].index(profile.run.chain_policy),
                labels["use_container"]: profile.run.use_container,
                labels["container_network"]: profile.run.container_network,
            }
            for label, value in values.items():
                fields_by_label[label].set_value(value)

        def save_current_profile(*_args) -> None:
            """Apply and persist every permission edit immediately."""
            name = fields[0].get_value()
            if not name:
                return
            draft = editor.draft
            unknown_commands = policy(labels["unknown_commands"])
            updated = tool_permissions.ToolPermissionsProfile(
                name=name,
                read=tool_permissions.FilePermissions(policy(labels["read_inside_repo"]), policy(labels["read_outside_repo"])),
                write=tool_permissions.FilePermissions(policy(labels["write_inside_repo"]), policy(labels["write_outside_repo"])),
                patch=tool_permissions.FilePermissions(policy(labels["patch_inside_repo"]), policy(labels["patch_outside_repo"])),
                search=policy(labels["search"]),
                run=tool_permissions.RunPermissions(
                    allow=set() if unknown_commands == "ask" else set(draft.run.allow),
                    ask=set(draft.run.ask), deny=set(draft.run.deny),
                    others=unknown_commands,
                    chain_policy=policy(labels["command_chains"]),
                    use_container=policy(labels["use_container"]),
                    container_network=policy(labels["container_network"]),
                ),
            )
            editor.update_permissions(updated)

        for field in fields[2:]:
            field.indent = 2
            if isinstance(field, InlineChoiceField):
                field.value_column = 24
                field._on_change = save_current_profile
            elif isinstance(field, ToggleField):
                field._on_change = save_current_profile

        def load_selected_profile(profile_name: str):
            try:
                loaded = editor.select(profile_name)
            except (KeyError, OSError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return

            sync_profile(loaded)

        fields[0]._on_select = load_selected_profile

        def new_profile():
            try:
                created = editor.create()
                new_name = created.name
                profile_options.append(new_name)
                fields[0].options = profile_options
                fields[0].set_value(len(profile_options) - 1)
                loaded = editor.draft
            except (OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return
            sync_profile(loaded)
            if fields[0].parent:
                fields[0].parent.mark_changed()

        def duplicate_profile(name: str):
            try:
                copy = editor.duplicate(name)
                profile_options.append(copy.name)
                fields[0].options = profile_options
                fields[0].set_value(len(profile_options) - 1)
                ui.chat_history_panel.add_message(f"Duplicated profile as: {copy.name}", msg_type=SysMsg())
            except (KeyError, OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())

        def rename_profile(old_name: str, new_name: str) -> bool:
            try:
                editor.rename(new_name, old_name)
                index = profile_options.index(old_name)
                profile_options[index] = new_name
                fields[0].options = profile_options
                fields[0].set_value(index)
                if fields[0].parent:
                    fields[0].parent.mark_changed()
                ui.chat_history_panel.add_message(
                    f"Renamed permission profile: {old_name} → {new_name}", msg_type=SysMsg())
                return True
            except (KeyError, OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return False

        def delete_profile(name: str):
            try:
                replacement = editor.remove(name)
                if name in profile_options:
                    profile_options.remove(name)
                if replacement.name not in profile_options:
                    profile_options.append(replacement.name)
                fields[0].options = profile_options
                fields[0].set_value(profile_options.index(replacement.name))
                loaded = editor.draft
                sync_profile(loaded)
                ui.chat_history_panel.add_message(f"Deleted profile: {name}", msg_type=SysMsg())
            except (KeyError, OSError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())

        fields[0]._on_create = new_profile
        fields[0]._on_rename = rename_profile
        fields[0]._on_duplicate = duplicate_profile
        fields[0]._on_remove = delete_profile

        def on_submit(values: dict):
            try:
                save_current_profile()
                suffix = f" and saved as '{fields[0].get_value()}'"
            except (OSError, ValueError) as exc:
                suffix = f" (not saved: {exc})"
            ui.chat_history_panel.add_message(f"Permission settings updated{suffix}", msg_type=SysMsg())

        ui.show_form_popup("Permissions", fields, on_submit, field_spacing=0)

    async def _execute_role_editor(self, ui: ChatUIProtocol):
        from pico_chat.ui.role_editor_form import RoleEditorForm
        from pico_chat.ui.role_editor_model import RoleEditorModel

        runtime = ui._active_runtime() if hasattr(ui, "_active_runtime") else None
        active_role = getattr(getattr(runtime, "agent", None), "role", None)
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
                    ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                    return
            if updated.name not in role_options:
                role_options.append(updated.name)
                field("available_roles").options = role_options
            field("available_roles").set_value(role_options.index(updated.name))

        def select_role(name: str):
            try:
                sync_fields(editor.select(name))
            except (KeyError, OSError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())

        def create_role():
            try:
                created = editor.create()
                role_options.append(created.name)
                field("available_roles").options = role_options
                field("available_roles").set_value(role_options.index(created.name))
                sync_fields(created)
            except (KeyError, OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())

        def duplicate_role(name: str):
            try:
                copied = editor.duplicate(name)
                role_options.append(copied.name)
                field("available_roles").options = role_options
                field("available_roles").set_value(role_options.index(copied.name))
                sync_fields(copied)
            except (KeyError, OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())

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
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                return False

        def remove_role(name: str):
            if len(role_options) <= 1:
                ui.chat_history_panel.add_message(
                    "At least one role must remain.", msg_type=SysMsgError())
                return
            ui.show_confirmation(
                f"Delete role '{name}'?",
                lambda: remove_role_now(name),
            )

        def remove_role_now(name: str):
            try:
                replacement = editor.remove(name)
                active_runtime_role = getattr(getattr(runtime, "agent", None), "role", None)
                if active_runtime_role is not None and active_runtime_role.name == name:
                    try:
                        runtime.switch_role(replacement)
                    except RuntimeError as exc:
                        ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())
                        return
                role_options.remove(name)
                field("available_roles").options = role_options
                field("available_roles").set_value(role_options.index(replacement.name))
                sync_fields(replacement)
                ui.form_popup.refresh()
            except (KeyError, OSError, ValueError, TypeError) as exc:
                ui.chat_history_panel.add_message(str(exc), msg_type=SysMsgError())

        fields[0]._on_select = select_role
        fields[0]._on_create = create_role
        fields[0]._on_duplicate = duplicate_role
        fields[0]._on_rename = rename_role
        fields[0]._on_remove = remove_role
        role_form.set_on_change(save_role)

        ui.show_form_popup("Permissions", fields, lambda _values: save_role(), field_spacing=0)



__all__ = ["PermissionsCommand"]
