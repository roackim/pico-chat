"""Conversation roles combining tool availability, policies, and instructions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml

from pico_chat.harness import tool_permissions
from pico_chat.harness.tool_permissions import (
    FilePermissions,
    Permission,
    RunPermissions,
    ToolPermissionsProfile,
)


@dataclass
class ToolPolicy:
    """Availability and permission settings for one registered tool."""

    enabled: bool = True
    permission: Permission = "ask"
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class Role:
    """Complete operating mode for one conversation."""

    name: str
    description: str = ""
    prompt: str = ""
    tools: dict[str, ToolPolicy] = field(default_factory=dict)

    def enabled_tool_names(self) -> set[str]:
        return {name for name, policy in self.tools.items() if policy.enabled}

    def policy_for(self, tool_name: str) -> ToolPolicy:
        return self.tools.get(tool_name, ToolPolicy(enabled=False, permission="deny"))

    def to_permission_profile(self) -> ToolPermissionsProfile:
        """Adapt role policies to the existing permission enforcement model."""
        base = deepcopy(tool_permissions.permissive)

        for tool_name in ("read", "write", "patch"):
            policy = self.policy_for(tool_name)
            inside = policy.settings.get("inside_repo", policy.permission)
            outside = policy.settings.get("outside_repo", "deny")
            permissions = FilePermissions(inside_repo=inside, outside_repo=outside)
            setattr(base, tool_name, permissions if policy.enabled else FilePermissions("deny", "deny"))

        run_policy = self.policy_for("run_command")
        if run_policy.enabled:
            settings = run_policy.settings
            base.run = RunPermissions(
                allow=set(settings.get("allow", tool_permissions.CMD_DEFAULT_ALLOW)),
                ask=set(settings.get("ask", tool_permissions.CMD_DEFAULT_ASK)),
                deny=set(settings.get("deny", tool_permissions.CMD_DEFAULT_DENY)),
                others=settings.get("others", run_policy.permission),
                chain_policy=settings.get("chain_policy", "ask"),
                use_container=bool(settings.get("use_container", False)),
                container_network=bool(settings.get("container_network", False)),
            )
        else:
            base.run = RunPermissions(allow=set(), ask=set(), deny=set(), others="deny")

        search_policy = self.policy_for("search_web")
        wiki_policy = self.policy_for("search_wiki")
        base.search = (
            search_policy.permission
            if search_policy.enabled or wiki_policy.enabled
            else "deny"
        )
        base.name = self.name
        return base

    @classmethod
    def from_permission_profile(
        cls,
        profile: ToolPermissionsProfile,
        *,
        description: str = "",
        prompt: str = "",
        enabled_tools: set[str] | None = None,
    ) -> "Role":
        """Create a role from a legacy permission profile."""
        from pico_chat.harness.tool_wrappers import registered_tool_specs

        tool_specs = registered_tool_specs()
        enabled = set(tool_specs) if enabled_tools is None else set(enabled_tools)
        policies = {
            "read": ToolPolicy(
                "read" in enabled,
                profile.read.inside_repo,
                {"inside_repo": profile.read.inside_repo, "outside_repo": profile.read.outside_repo},
            ),
            "write": ToolPolicy(
                "write" in enabled,
                profile.write.inside_repo,
                {"inside_repo": profile.write.inside_repo, "outside_repo": profile.write.outside_repo},
            ),
            "patch": ToolPolicy(
                "patch" in enabled,
                profile.patch.inside_repo,
                {"inside_repo": profile.patch.inside_repo, "outside_repo": profile.patch.outside_repo},
            ),
            "run_command": ToolPolicy(
                "run_command" in enabled,
                profile.run.others,
                {
                    "allow": sorted(profile.run.allow),
                    "ask": sorted(profile.run.ask),
                    "deny": sorted(profile.run.deny),
                    "others": profile.run.others,
                    "chain_policy": profile.run.chain_policy,
                    "use_container": profile.run.use_container,
                    "container_network": profile.run.container_network,
                },
            ),
            "search_web": ToolPolicy("search_web" in enabled, profile.search),
            "search_wiki": ToolPolicy("search_wiki" in enabled, profile.search),
            "subagent": ToolPolicy("subagent" in enabled, "ask"),
            "wait_for_subagents": ToolPolicy("wait_for_subagents" in enabled, "ask"),
        }
        for tool_name, spec in tool_specs.items():
            policies.setdefault(
                tool_name,
                ToolPolicy(
                    tool_name in enabled,
                    spec.default_permission,
                    deepcopy(spec.default_settings),
                ),
            )
        return cls(profile.name, description, prompt, policies)


_ROLE_PATH = Path("~/.config/pico-chat/roles.toml").expanduser()


def default_role() -> Role:
    role = Role.from_permission_profile(
        deepcopy(tool_permissions.permissive),
        description="General coding assistant",
        prompt="",
    )
    role.name = "default"
    return role


def builtin_roles() -> dict[str, Role]:
    return {
        "default": default_role(),
        "reviewer": Role.from_permission_profile(
            deepcopy(tool_permissions.scaffolder),
            description="Read-only code review",
            prompt="Review code carefully. Do not modify files. Prioritize defects, regressions, and missing tests.",
            enabled_tools={"read", "search_web", "search_wiki", "subagent", "wait_for_subagents"},
        ),
        "researcher": Role.from_permission_profile(
            deepcopy(tool_permissions.strict),
            description="Research and summarize without making changes",
            prompt="Investigate the request, gather evidence, and report precise findings without modifying files.",
            enabled_tools={"read", "search_web", "search_wiki"},
        ),
    }


def _policy_to_dict(policy: ToolPolicy) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "permission": policy.permission,
        "settings": policy.settings,
    }


def _role_to_dict(role: Role) -> dict[str, Any]:
    return {
        "description": role.description,
        "prompt": role.prompt,
        "tools": {name: _policy_to_dict(policy) for name, policy in role.tools.items()},
    }


def _role_from_dict(name: str, data: dict[str, Any]) -> Role:
    from pico_chat.harness.tool_wrappers import registered_tool_specs

    tools = {}
    for tool_name, values in data.get("tools", {}).items():
        tools[tool_name] = ToolPolicy(
            enabled=bool(values.get("enabled", False)),
            permission=values.get("permission", "deny"),
            settings=dict(values.get("settings", {})),
        )
    for tool_name, spec in registered_tool_specs().items():
        tools.setdefault(
            tool_name,
            ToolPolicy(False, spec.default_permission, deepcopy(spec.default_settings)),
        )
    return Role(
        name=name,
        description=data.get("description", ""),
        prompt=data.get("prompt", ""),
        tools=tools,
    )


def save_role(role: Role) -> None:
    name = role.name.strip()
    if not name or any(char in name for char in "[]\\"):
        raise ValueError("Role name must be non-empty and cannot contain '[' or '\\'")
    data = toml.load(_ROLE_PATH) if _ROLE_PATH.exists() else {}
    deleted_roles = set(data.get("deleted_roles", []))
    deleted_roles.discard(name)
    if deleted_roles:
        data["deleted_roles"] = sorted(deleted_roles)
    else:
        data.pop("deleted_roles", None)
    data.setdefault("roles", {})[name] = _role_to_dict(role)
    _ROLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ROLE_PATH.write_text(toml.dumps(data), encoding="utf-8")


def rename_role(old_name: str, new_name: str) -> None:
    """Rename a saved role; built-in roles must be copied first."""
    new_name = new_name.strip()
    if not new_name or any(char in new_name for char in "[]\\"):
        raise ValueError("Role name must be non-empty and cannot contain '[' or '\\'")
    if old_name in builtin_roles():
        raise ValueError(f"Built-in role cannot be renamed: {old_name}")
    if not _ROLE_PATH.exists():
        raise KeyError(f"Role not found: {old_name}")
    data = toml.load(_ROLE_PATH)
    saved = data.get("roles", {})
    if old_name not in saved:
        raise KeyError(f"Role not found: {old_name}")
    if new_name in builtin_roles() or new_name in saved:
        raise ValueError(f"Role already exists: {new_name}")
    saved[new_name] = saved.pop(old_name)
    _ROLE_PATH.write_text(toml.dumps(data), encoding="utf-8")


def delete_role(name: str) -> None:
    """Delete a role, retaining a tombstone for deleted built-ins."""
    data = toml.load(_ROLE_PATH) if _ROLE_PATH.exists() else {}
    if name not in list_roles():
        raise KeyError(f"Role not found: {name}")
    if len(list_roles()) <= 1:
        raise ValueError("At least one role must remain")
    saved = data.get("roles", {})
    saved.pop(name, None)
    if name in builtin_roles():
        deleted_roles = set(data.get("deleted_roles", []))
        deleted_roles.add(name)
        data["deleted_roles"] = sorted(deleted_roles)
    _ROLE_PATH.write_text(toml.dumps(data), encoding="utf-8")


def duplicate_role(name: str, new_name: str | None = None) -> Role:
    """Copy a built-in or saved role into a new saved role."""
    source = load_role(name)
    target_name = (new_name or f"{name}-copy").strip()
    existing = set(list_roles())
    if target_name in existing:
        suffix = 2
        base = target_name
        while f"{base}-{suffix}" in existing:
            suffix += 1
        target_name = f"{base}-{suffix}"
    copy = deepcopy(source)
    copy.name = target_name
    save_role(copy)
    return copy


def load_role(name: str) -> Role:
    builtins = builtin_roles()
    data = toml.load(_ROLE_PATH).get("roles", {}) if _ROLE_PATH.exists() else {}
    if name in set(data.get("deleted_roles", [])):
        raise KeyError(f"Role not found: {name}")
    if name in data:
        return _role_from_dict(name, data[name])
    if name in builtins:
        return builtins[name]
    raise KeyError(f"Role not found: {name}")


def list_roles() -> list[str]:
    names = set(builtin_roles())
    if _ROLE_PATH.exists():
        data = toml.load(_ROLE_PATH)
        names.update(data.get("roles", {}).keys())
        names.difference_update(data.get("deleted_roles", []))
    return sorted(names)
