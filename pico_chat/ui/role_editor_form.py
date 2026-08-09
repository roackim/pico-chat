from __future__ import annotations

from typing import Iterator

from pico_chat.harness.roles import Role
from pico_chat.ui.role_editor_model import RoleEditorModel
from pico_chat.ui.tui.components.form import (
    ComponentField, FormSection, InlineChoiceField, ProfileList, TextAreaField,
    TextField, ToggleField,
)
from pico_chat.ui.tui.components.layout import SeparatorLine
from pico_chat.ui.tui.colors import theme


class RoleEditorForm:
    """Declarative fields and role bindings for the unified permissions form."""

    field_labels = {
        "available_roles": "Available roles",
        "description": "Description",
        "role_prompt": "Role prompt",
        "read_inside_repo": "Read inside repo",
        "read_outside_repo": "Read outside repo",
        "write_inside_repo": "Write inside repo",
        "write_outside_repo": "Write outside repo",
        "patch_inside_repo": "Patch inside repo",
        "patch_outside_repo": "Patch outside repo",
        "unknown_commands": "Unknown commands",
        "command_chains": "Command chains",
        "use_container": "Use container",
        "container_network": "Container network",
    }

    tool_names = [
        "read", "write", "patch", "run_command", "search_web", "search_wiki",
        "subagent", "wait_for_subagents",
    ]
    policies = ["allow", "ask", "deny"]
    policy_colors = {"allow": theme.SUCCESS, "deny": theme.ERROR}

    def __init__(self, editor: RoleEditorModel):
        self.editor = editor
        draft = editor.draft
        role_names = editor.role_names()
        labels = self.field_labels
        self.fields = [
            ProfileList(labels["available_roles"], options=role_names,
                        value=role_names.index(editor.selected_name)),
            ComponentField(SeparatorLine()),
            TextField(labels["description"], value=draft.description, highlight_label=True),
            TextAreaField(labels["role_prompt"], value=draft.prompt, min_lines=4,
                          highlight_label=True),
            FormSection(
                "Tools:",
                [ToggleField(name, value=draft.policy_for(name).enabled)
                 for name in self.tool_names],
            ),
            FormSection(
                "File policies:",
                self._file_policy_fields(draft),
                spacing_before=1,
            ),
            FormSection(
                "Containerization:",
                [
                    ToggleField(labels["use_container"], value=draft.policy_for("run_command").settings.get("use_container", False)),
                    ToggleField(labels["container_network"], value=draft.policy_for("run_command").settings.get("container_network", False)),
                ],
                spacing_before=1,
            ),
        ]
        self._fields_by_key = {
            key: self._find_field(label)
            for key, label in labels.items()
            if key not in self.tool_names
        }

    def _find_field(self, label: str):
        return next(item for item in self.iter_fields() if item.label == label)

    def _file_policy_fields(self, role: Role):
        policies = self.policies
        labels = self.field_labels
        option_colors = self.policy_colors
        return [
            InlineChoiceField(labels["read_inside_repo"], options=policies, option_colors=option_colors, value=policies.index(role.policy_for("read").settings.get("inside_repo", "deny"))),
            InlineChoiceField(labels["read_outside_repo"], options=policies, option_colors=option_colors, value=policies.index(role.policy_for("read").settings.get("outside_repo", "deny"))),
            InlineChoiceField(labels["write_inside_repo"], options=policies, option_colors=option_colors, value=policies.index(role.policy_for("write").settings.get("inside_repo", "deny"))),
            InlineChoiceField(labels["write_outside_repo"], options=policies, option_colors=option_colors, value=policies.index(role.policy_for("write").settings.get("inside_repo", "deny"))),
            InlineChoiceField(labels["patch_inside_repo"], options=policies, option_colors=option_colors, value=policies.index(role.policy_for("patch").settings.get("inside_repo", "deny"))),
            InlineChoiceField(labels["patch_outside_repo"], options=policies, option_colors=option_colors, value=policies.index(role.policy_for("patch").settings.get("outside_repo", "deny"))),
            InlineChoiceField(labels["unknown_commands"], options=policies, option_colors=option_colors, value=policies.index(role.policy_for("run_command").settings.get("others", "deny"))),
            InlineChoiceField(labels["command_chains"], options=["ask", "deny"], option_colors=option_colors, value=["ask", "deny"].index(role.policy_for("run_command").settings.get("chain_policy", "ask"))),
        ]

    def iter_fields(self) -> Iterator:
        for item in self.fields:
            if isinstance(item, FormSection):
                yield from item.fields
            else:
                yield item

    def field(self, key: str):
        if key in self._fields_by_key:
            return self._fields_by_key[key]
        return self._find_field(key)

    def set_on_change(self, callback) -> None:
        for field in self.iter_fields():
            if hasattr(field, "_on_change"):
                field._on_change = callback

    def sync(self, role: Role) -> None:
        self.field("description").set_value(role.description)
        self.field("role_prompt").set_value(role.prompt)
        for name in self.tool_names:
            self.field(name).set_value(role.policy_for(name).enabled)
        values = {
            "read_inside_repo": role.policy_for("read").settings.get("inside_repo", "deny"),
            "read_outside_repo": role.policy_for("read").settings.get("outside_repo", "deny"),
            "write_inside_repo": role.policy_for("write").settings.get("inside_repo", "deny"),
            "write_outside_repo": role.policy_for("write").settings.get("outside_repo", "deny"),
            "patch_inside_repo": role.policy_for("patch").settings.get("inside_repo", "deny"),
            "patch_outside_repo": role.policy_for("patch").settings.get("outside_repo", "deny"),
            "unknown_commands": role.policy_for("run_command").settings.get("others", "deny"),
            "command_chains": role.policy_for("run_command").settings.get("chain_policy", "ask"),
            "use_container": role.policy_for("run_command").settings.get("use_container", False),
            "container_network": role.policy_for("run_command").settings.get("container_network", False),
        }
        for key, value in values.items():
            if isinstance(value, str):
                options = ["ask", "deny"] if key == "command_chains" else self.policies
                value = options.index(value)
            self.field(key).set_value(value)

    def apply(self) -> Role:
        role = self.editor.draft
        role.description = self.field("description").get_value()
        role.prompt = self.field("role_prompt").get_value()
        for name in self.tool_names:
            role.tools[name].enabled = self.field(name).get_value()
        for name, inside_label, outside_label in (
            ("read", "read_inside_repo", "read_outside_repo"),
            ("write", "write_inside_repo", "write_outside_repo"),
            ("patch", "patch_inside_repo", "patch_outside_repo"),
        ):
            role.tools[name].permission = self.field(inside_label).get_value()
            role.tools[name].settings.update(
                inside_repo=self.field(inside_label).get_value(),
                outside_repo=self.field(outside_label).get_value(),
            )
        run = role.tools["run_command"]
        run.permission = self.field("unknown_commands").get_value()
        run.settings.update(
            others=self.field("unknown_commands").get_value(),
            chain_policy=self.field("command_chains").get_value(),
            use_container=self.field("use_container").get_value(),
            container_network=self.field("container_network").get_value(),
        )
        return self.editor.update(role)