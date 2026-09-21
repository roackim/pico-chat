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
            "read", "write", "patch", "run_command",
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
                },
            ),
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
        enabled_tools={"read", "subagent", "wait_for_subagents"},
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
                },
            ),
            "subagent": ("ask", {}),
            "wait_for_subagents": ("ask", {}),
        },
    )
    researcher = _build_role(
        name="researcher",
        description="Research and summarize without making changes",
        prompt="Investigate the request, gather evidence, and report precise findings without modifying files.",
        enabled_tools={"read"},
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
                },
            ),
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
        enabled_tools={"read", "subagent", "wait_for_subagents"},
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
                },
            ),
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


def _default_roles_dir() -> Path:
    from pico_chat import pico_cfg

    return pico_cfg.get_roles_dir()


# One role per file: ``<config>/roles/<name>.toml``. The file body is the role
# itself (``description``/``prompt``/``[tools.<tool>]``), and the stem is the
# role name. Files whose stem starts with ``_`` or ``.`` are ignored, which is
# where the shipped example lives.
_ROLES_DIR = _default_roles_dir()


def _role_file(name: str) -> Path:
    return _ROLES_DIR / f"{name}.toml"


def _validate_name(name: str) -> str:
    name = name.strip()
    if not name or name.startswith(".") or any(c in name for c in "[]\\/"):
        raise ValueError("Role name must be non-empty and cannot contain '[', '\\', '/' or start with '.'")
    return name


def _iter_role_files():
    if not _ROLES_DIR.exists():
        return []
    return sorted(
        path for path in _ROLES_DIR.glob("*.toml")
        if not path.stem.startswith(("_", "."))
    )


def _read_role_file(path: Path) -> dict[str, Any]:
    try:
        return toml.load(path)
    except (toml.TomlDecodeError, OSError) as exc:
        raise ValueError(f"Invalid role file {path.name}: {exc}") from exc


def save_role(role: Role) -> None:
    name = _validate_name(role.name)
    _ROLES_DIR.mkdir(parents=True, exist_ok=True)
    _role_file(name).write_text(toml.dumps(_role_to_dict(role)), encoding="utf-8")


def rename_role(old_name: str, new_name: str) -> None:
    """Rename a saved role; built-in roles must be copied first."""
    new_name = _validate_name(new_name)
    if old_name in builtin_roles():
        raise ValueError(f"Built-in role cannot be renamed: {old_name}")
    source = _role_file(old_name)
    if not source.exists():
        raise KeyError(f"Role not found: {old_name}")
    if new_name in builtin_roles() or _role_file(new_name).exists():
        raise ValueError(f"Role already exists: {new_name}")
    source.rename(_role_file(new_name))


def delete_role(name: str) -> None:
    """Delete a role file; a deleted built-in is hidden by a tombstone file."""
    if name not in list_roles():
        raise KeyError(f"Role not found: {name}")
    if len(list_roles()) <= 1:
        raise ValueError("At least one role must remain")
    path = _role_file(name)
    if name in builtin_roles():
        # Hide the built-in rather than resurrecting it by deleting the file.
        _ROLES_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text("disabled = true\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


def duplicate_role(name: str, new_name: str | None = None) -> Role:
    """Copy a built-in or saved role into a new saved role."""
    source = load_role(name)
    target_name = _validate_name(new_name or f"{name}-copy")
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
    path = _role_file(name)
    if path.exists():
        data = _read_role_file(path)
        if data.get("disabled"):
            raise KeyError(f"Role not found: {name}")
        return _role_from_dict(name, data)
    builtins = builtin_roles()
    if name in builtins:
        return builtins[name]
    raise KeyError(f"Role not found: {name}")


def list_roles() -> list[str]:
    names = set(builtin_roles())
    for path in _iter_role_files():
        data = _read_role_file(path)
        if data.get("disabled"):
            names.discard(path.stem)
        else:
            names.add(path.stem)
    return sorted(names)
