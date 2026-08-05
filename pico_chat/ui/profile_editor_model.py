"""State and persistence model for the permissions-profile editor."""

from __future__ import annotations

from copy import deepcopy
from types import ModuleType
from typing import Optional

from pico_chat.harness import tool_permissions as default_permissions
from pico_chat.harness.tool_permissions import (
    FilePermissions,
    RunPermissions,
    ToolPermissionsProfile,
)


class ProfileEditorModel:
    """Own profile selection, lifecycle operations, and immediate persistence.

    UI components use this public API rather than changing widget cursor state
    or calling persistence helpers directly.  ``selected_name`` is the active
    profile; focus remains entirely a UI concern.
    """

    def __init__(self, permissions_module: ModuleType = default_permissions):
        self._permissions = permissions_module
        self._selected_name = permissions_module.permissions.name
        self._draft = deepcopy(permissions_module.permissions)

    @property
    def selected_name(self) -> str:
        return self._selected_name

    @property
    def draft(self) -> ToolPermissionsProfile:
        """Return an isolated copy so callers cannot mutate model state silently."""
        return deepcopy(self._draft)

    def profile_names(self) -> list[str]:
        saved = self._permissions.list_profiles()
        return [self._selected_name] + [name for name in saved if name != self._selected_name]

    def select(self, name: str) -> ToolPermissionsProfile:
        if name in self._permissions.list_profiles():
            profile = self._permissions.load_profile(name)
        else:
            profile = self._builtin(name)
        self._selected_name = name
        self._draft = deepcopy(profile)
        self._permissions.apply_profile(profile)
        return self.draft

    def create(self) -> ToolPermissionsProfile:
        name = self._unique_name("new-profile")
        profile = ToolPermissionsProfile(
            name=name,
            read=FilePermissions("ask", "deny"),
            write=FilePermissions("ask", "deny"),
            patch=FilePermissions("ask", "deny"),
            search="allow",
            run=RunPermissions(others="deny"),
        )
        self._permissions.save_profile(name, profile)
        self._selected_name = name
        self._draft = deepcopy(profile)
        self._permissions.apply_profile(profile)
        return self.draft

    def duplicate(self, name: Optional[str] = None) -> ToolPermissionsProfile:
        source_name = name or self._selected_name
        source = self._load(source_name)
        copy_name = self._unique_name(f"{source_name}-copy")
        source.name = copy_name
        self._permissions.save_profile(copy_name, source)
        self._selected_name = copy_name
        self._draft = deepcopy(source)
        self._permissions.apply_profile(source)
        return self.draft

    def rename(self, new_name: str, old_name: Optional[str] = None) -> ToolPermissionsProfile:
        source_name = old_name or self._selected_name
        if source_name in self._permissions.list_profiles():
            self._permissions.rename_profile(source_name, new_name)
            profile = self._permissions.load_profile(new_name)
        else:
            if new_name in self._permissions.list_profiles():
                raise ValueError(f"Permission profile already exists: {new_name}")
            profile = self._load(source_name)
            profile.name = new_name
            self._permissions.save_profile(new_name, profile)
        self._selected_name = new_name
        self._draft = deepcopy(profile)
        self._permissions.apply_profile(profile)
        return self.draft

    def remove(self, name: Optional[str] = None) -> ToolPermissionsProfile:
        target = name or self._selected_name
        saved_names = self._permissions.list_profiles()
        if target not in saved_names:
            # Built-in profiles are valid editor entries even before they have
            # been written to the profile store. Removing one should behave
            # like removing the active profile, not fail because there is no
            # file entry to delete.
            if target != self._selected_name:
                raise ValueError(f"Cannot remove unsaved permission profile: {target}")
        else:
            self._permissions.delete_profile(target)
        if target != self._selected_name:
            return self.draft
        remaining = self._permissions.list_profiles()
        if remaining:
            return self.select(remaining[0])
        return self.create()

    def update_permissions(self, profile: ToolPermissionsProfile) -> ToolPermissionsProfile:
        """Apply and persist an edited profile immediately."""
        updated = deepcopy(profile)
        updated.name = self._selected_name
        self._permissions.save_profile(self._selected_name, updated)
        self._draft = deepcopy(updated)
        self._permissions.apply_profile(updated)
        return self.draft

    def _load(self, name: str) -> ToolPermissionsProfile:
        if name in self._permissions.list_profiles():
            return self._permissions.load_profile(name)
        # The active profile may be an unsaved custom profile left by a
        # caller.  Its draft is the authoritative source until it is saved.
        if name == self._selected_name and self._draft.name == name:
            return self.draft
        return self._builtin(name)

    def _builtin(self, name: str) -> ToolPermissionsProfile:
        """Load a pristine predefined profile, independent of active state."""
        profile = getattr(self._permissions, name, None)
        if isinstance(profile, ToolPermissionsProfile):
            return deepcopy(profile)
        raise KeyError(f"Permission profile not found: {name}")

    def _unique_name(self, base: str) -> str:
        names = set(self.profile_names())
        if base not in names:
            return base
        suffix = 2
        while f"{base}-{suffix}" in names:
            suffix += 1
        return f"{base}-{suffix}"
