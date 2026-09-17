"""Conversation roles combining tool availability, policies, and instructions.

``Role`` is the single source of truth for a conversation's operating mode:
which tools are enabled, what each tool's permission policy is, and the
role-specific prompt.  There is no parallel permission-profile model; the
low-level policy primitives live in :mod:`pico_chat.harness.permissions`.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml

from pico_chat.harness.permissions import (
    CMD_DEFAULT_ALLOW,
    CMD_DEFAULT_ASK,
    CMD_DEFAULT_DENY,
    Permission,
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


def _build_role(
    name: str,
    description: str,
    prompt: str,
    enabled_tools: set[str],
    policies: dict[str, tuple[Permission, dict[str, Any]]],
) -> Role:
    """Construct a role from explicit policies, filling defaults for any
    registered tool that is not listed."""
    from pico_chat.harness.tools import registered_tool_specs

    tools = {
        tool_name: ToolPolicy(
            enabled=tool_name in enabled_tools,
            permission=permission,
            settings=deepcopy(settings),
        )
        for tool_name, (permission, settings) in policies.items()
    }
    for tool_name, spec in registered_tool_specs().items():
        tools.setdefault(
            tool_name,
            ToolPolicy(
                enabled=tool_name in enabled_tools,
                permission=spec.default_permission,
                settings=deepcopy(spec.default_settings),
            ),
        )
    return Role(name=name, description=description, prompt=prompt, tools=tools)


def default_role() -> Role:
    """The permissive default role: all tools, safe defaults."""
    return _build_role(
        name="default",
        description="General coding assistant",
        prompt="",
        enabled_tools={
            "read", "write", "patch", "run_command", "search_web", "search_wiki",
            "subagent", "wait_for_subagents",
        },
        policies={
            "read": ("allow", {"inside_repo": "allow", "outside_repo": "ask"}),
            "write": ("allow", {"inside_repo": "allow", "outside_repo": "deny"}),
            "patch": ("allow", {"inside_repo": "allow", "outside_repo": "deny"}),
            "run_command": (
                "deny",
                {
                    "allow": sorted(CMD_DEFAULT_ALLOW),
                    "ask": sorted(CMD_DEFAULT_ASK),
                    "deny": sorted(CMD_DEFAULT_DENY),
                    "others": "deny",
                    "chain_policy": "ask",
                    "use_container": True,
                    "container_network": True,
                },
            ),
            "search_web": ("allow", {}),
            "search_wiki": ("allow", {}),
            "subagent": ("ask", {}),
            "wait_for_subagents": ("ask", {}),
        },
    )


def builtin_roles() -> dict[str, Role]:
    """The built-in roles shipped with pico-chat."""
    reviewer = _build_role(
        name="reviewer",
        description="Read-only code review",
        prompt="Review code carefully. Do not modify files. Prioritize defects, regressions, and missing tests.",
        enabled_tools={"read", "search_web", "search_wiki", "subagent", "wait_for_subagents"},
        policies={
            "read": ("allow", {"inside_repo": "allow", "outside_repo": "deny"}),
            "write": ("deny", {"inside_repo": "deny", "outside_repo": "deny"}),
            "patch": ("deny", {"inside_repo": "deny", "outside_repo": "deny"}),
            "run_command": (
                "deny",
                {
                    "allow": [],
                    "ask": [],
                    "deny": [],
                    "others": "deny",
                    "chain_policy": "ask",
                    "use_container": False,
                    "container_network": False,
                },
            ),
            "search_web": ("allow", {}),
            "search_wiki": ("allow", {}),
            "subagent": ("ask", {}),
            "wait_for_subagents": ("ask", {}),
        },
    )
    researcher = _build_role(
        name="researcher",
        description="Research and summarize without making changes",
        prompt="Investigate the request, gather evidence, and report precise findings without modifying files.",
        enabled_tools={"read", "search_web", "search_wiki"},
        policies={
            "read": ("ask", {"inside_repo": "ask", "outside_repo": "deny"}),
            "write": ("ask", {"inside_repo": "ask", "outside_repo": "deny"}),
            "patch": ("ask", {"inside_repo": "ask", "outside_repo": "deny"}),
            "run_command": (
                "ask",
                {
                    "allow": [],
                    "ask": [],
                    "deny": [],
                    "others": "ask",
                    "chain_policy": "ask",
                    "use_container": True,
                    "container_network": True,
                },
            ),
            "search_web": ("ask", {}),
            "search_wiki": ("ask", {}),
            "subagent": ("ask", {}),
            "wait_for_subagents": ("ask", {}),
        },
    )
    return {
        "default": default_role(),
        "reviewer": reviewer,
        "researcher": researcher,
    }


def scaffolder_role() -> Role:
    """Read-only role used by subagents to explore without side effects."""
    return _build_role(
        name="scaffolder",
        description="Read-only scaffolding subagent",
        prompt="",
        enabled_tools={"read", "search_web", "search_wiki", "subagent", "wait_for_subagents"},
        policies={
            "read": ("allow", {"inside_repo": "allow", "outside_repo": "deny"}),
            "write": ("deny", {"inside_repo": "deny", "outside_repo": "deny"}),
            "patch": ("deny", {"inside_repo": "deny", "outside_repo": "deny"}),
            "run_command": (
                "deny",
                {
                    "allow": [],
                    "ask": [],
                    "deny": [],
                    "others": "deny",
                    "chain_policy": "ask",
                    "use_container": False,
                    "container_network": False,
                },
            ),
            "search_web": ("allow", {}),
            "search_wiki": ("allow", {}),
            "subagent": ("ask", {}),
            "wait_for_subagents": ("ask", {}),
        },
    )


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
    from pico_chat.harness.tools import registered_tool_specs

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


_ROLE_PATH = Path("~/.config/pico-chat/roles.toml").expanduser()


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
