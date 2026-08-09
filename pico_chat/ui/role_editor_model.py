"""UI-independent lifecycle model for conversation roles."""

from __future__ import annotations

from copy import deepcopy

from pico_chat.harness import roles
from pico_chat.harness.roles import Role


class RoleEditorModel:
    """Keep role selection, drafts, and persistence outside widget callbacks."""

    def __init__(self, selected_name: str = "default"):
        self._selected_name = selected_name
        self._draft = deepcopy(roles.load_role(selected_name))

    @property
    def selected_name(self) -> str:
        return self._selected_name

    @property
    def draft(self) -> Role:
        return deepcopy(self._draft)

    def role_names(self) -> list[str]:
        names = roles.list_roles()
        if self._selected_name not in names:
            names.insert(0, self._selected_name)
        return names

    def select(self, name: str) -> Role:
        selected = roles.load_role(name)
        self._selected_name = name
        self._draft = deepcopy(selected)
        return self.draft

    def create(self) -> Role:
        created = roles.duplicate_role("default")
        self._selected_name = created.name
        self._draft = deepcopy(created)
        return self.draft

    def duplicate(self, name: str | None = None) -> Role:
        copied = roles.duplicate_role(name or self._selected_name)
        self._selected_name = copied.name
        self._draft = deepcopy(copied)
        return self.draft

    def rename(self, new_name: str, old_name: str | None = None) -> Role:
        source = old_name or self._selected_name
        roles.rename_role(source, new_name)
        return self.select(new_name)

    def remove(self, name: str | None = None) -> Role:
        target = name or self._selected_name
        roles.delete_role(target)
        remaining = roles.list_roles()
        replacement_name = "default" if "default" in remaining else remaining[0]
        replacement = roles.load_role(replacement_name)
        self._selected_name = replacement.name
        self._draft = deepcopy(replacement)
        return self.draft

    def update(self, role: Role) -> Role:
        updated = deepcopy(role)
        updated.name = self._selected_name
        roles.save_role(updated)
        self._draft = deepcopy(updated)
        return self.draft

    def ensure_tool(self, name: str, *, enabled: bool, permission: str = "ask") -> None:
        self._draft.tools[name] = ToolPolicy(enabled=enabled, permission=permission)
