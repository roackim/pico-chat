"""
Tool permissions configuration system.

Provides granular permission control for LLM tools:
- read/write/patch: Inside/outside repo granularity
- run: Command execution with configurable command lists and policies
"""
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import toml


Permission = Literal["allow", "ask", "deny"]


# Default command lists (migrated from security.py)
CMD_DEFAULT_ALLOW = {
    'cat', 'head', 'tail', 'less', 'more',                      # File reading
    'ls', 'find', 'tree', 'file', 'which',                      # File discovery   
    'grep', 'awk', 'sed', 'cut', 'sort', 'uniq', 'wc',          # Text processing
    'echo', 'pwd', 'basename', 'dirname', 'realpath', 'date',   # Utilities
    'cp', 'mv', 'mkdir', 'touch', 'cd'                          # File writing (non-destructive)
}

CMD_DEFAULT_ASK = {
    'curl', 'wget',           # Network access
    'git',                    # Version control
    'python', 'python3',      # Code execution
    'node', 'npm', 'npx',     # JavaScript
    'rm', 'rmdir',            # Deletion
    'bash', 'sh', 'zsh', 'fish',  # Shell spawning
    'eval', 'exec',               # Code injection vectors
    'ln',                           # Symlinks
}

CMD_DEFAULT_DENY = {
    'dd', 'mkfs',                 # Low-level operations
    'sudo', 'su', 'doas',         # Privilege escalation
    'reboot', 'shutdown',         # System control
}

# Dangerous patterns that escalate ALLOW commands to ASK
# Maps command name to list of dangerous strings to detect in the full command
CMD_DANGEROUS_PATTERNS = {
    'find': ['-exec', '-execdir', '-delete', '-ok'],
    'awk': ['system('],
    'sed': ['/e'],  # The 'e' flag in s///e (may have false positives, but safe)
}


@dataclass
class FilePermissions:
    """Permissions for file operations with inside/outside repo granularity."""
    inside_repo: Permission
    outside_repo: Permission
    
    def get(self, is_inside_repo: bool) -> Permission:
        """Get permission based on whether path is inside or outside repo."""
        return self.inside_repo if is_inside_repo else self.outside_repo


@dataclass
class RunPermissions:
    """Permissions for shell command execution with granular command control."""
    # Command classifications
    allow: set[str] = field(default_factory=lambda: CMD_DEFAULT_ALLOW.copy())
    deny: set[str] = field(default_factory=lambda: CMD_DEFAULT_DENY.copy())
    ask: set[str] = field(default_factory=lambda: CMD_DEFAULT_ASK.copy())
    
    # Policy for commands not in any list
    others: Literal["allow", "ask", "deny"] = "deny"
    
    # Policy for command chains (&&, ||, |, ;)
    # Simplified: any operators detected = treated as chain
    chain_policy: Literal["ask", "deny"] = "ask"
    #   ask: Always ask when operators detected (even in strings)
    #   deny: Block any command with operators
    
    # Containerization (bubblewrap)
    use_container: bool = False
    container_network: bool = False  # Allow network access in container


@dataclass
class ToolPermissionsProfile:
    """Complete tool permissions profile."""
    name: str
    
    # File operations (with inside/outside repo granularity)
    read: FilePermissions
    write: FilePermissions
    patch: FilePermissions
    
    # Shell execution
    run: RunPermissions
    
    # Search operations (search_web/search_wiki)
    # Safe read-only external API calls, typically allowed
    search: Permission = "allow"
    
    def get_read_permission(self, is_inside_repo: bool) -> Permission:
        """Get read permission for a path."""
        return self.read.get(is_inside_repo)
    
    def get_write_permission(self, is_inside_repo: bool) -> Permission:
        """Get write permission for a path."""
        return self.write.get(is_inside_repo)
    
    def get_patch_permission(self, is_inside_repo: bool) -> Permission:
        """Get patch permission for a path."""
        return self.patch.get(is_inside_repo)
    
    def get_run_permission(self) -> RunPermissions:
        """Get run permissions."""
        return self.run
    
    def get_search_permission(self) -> Permission:
        """Get search operation permission."""
        return self.search


# --- Predefined Profiles ---

# Strict profile: ask for everything
strict = ToolPermissionsProfile(
    name="strict",
    read=FilePermissions(inside_repo="ask", outside_repo="deny"),
    write=FilePermissions(inside_repo="ask", outside_repo="deny"),
    patch=FilePermissions(inside_repo="ask", outside_repo="deny"),
    run=RunPermissions(
        allow=set(),
        deny=set(),
        ask=set(),
        others="ask",
        use_container=True,
        container_network=True,
    ),
    search="ask",
)

# Permissive profile: allow operations inside repo, ask for outside/commands
permissive = ToolPermissionsProfile(
    name="permissive",
    read=FilePermissions(inside_repo="allow", outside_repo="ask"),
    write=FilePermissions(inside_repo="allow", outside_repo="deny"),
    patch=FilePermissions(inside_repo="allow", outside_repo="deny"),
    run=RunPermissions(
        allow=CMD_DEFAULT_ALLOW,
        ask=CMD_DEFAULT_ASK,
        deny=CMD_DEFAULT_DENY,
        use_container=True,
        container_network=True,
    ),
    search="allow",  # Search is safe read-only external API
)

# Unrestricted profile: allow everything (use with caution!)
unrestricted = ToolPermissionsProfile(
    name="unrestricted",
    read=FilePermissions(inside_repo="allow", outside_repo="allow"),
    write=FilePermissions(inside_repo="allow", outside_repo="allow"),
    patch=FilePermissions(inside_repo="allow", outside_repo="allow"),
    run=RunPermissions(
        allow=set(),
        deny=set(),
        ask=set(),
        others="allow", # allow all commands
        use_container=True,
        container_network=True,
    ),
    search="allow",
)

# Locked profile: deny everything
locked = ToolPermissionsProfile(
    name="locked",
    read=FilePermissions(inside_repo="deny", outside_repo="deny"),
    write=FilePermissions(inside_repo="deny", outside_repo="deny"),
    patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
    run=RunPermissions(
        allow=set(),
        deny=CMD_DEFAULT_ALLOW | CMD_DEFAULT_ASK | CMD_DEFAULT_DENY,
        ask=set(),
        others="deny",
        use_container=True,
        container_network=True,
    ),
    search="deny",
)

TESTING = ToolPermissionsProfile(
    name="askall",
    read=FilePermissions(inside_repo="ask", outside_repo="ask"),
    write=FilePermissions(inside_repo="ask", outside_repo="ask"),
    patch=FilePermissions(inside_repo="ask", outside_repo="ask"),
    run=RunPermissions(
        allow=set(),
        deny=set(),
        ask=set(),
        others="ask",
        use_container=True,
        container_network=True,
    ),
    search="ask",
)

# Scaffolder profile: read-only inside repo, deny everything else.
# Used by subagents to explore the codebase without side effects.
scaffolder = ToolPermissionsProfile(
    name="scaffolder",
    read=FilePermissions(inside_repo="allow", outside_repo="deny"),
    write=FilePermissions(inside_repo="deny", outside_repo="deny"),
    patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
    run=RunPermissions(
        allow=set(),
        deny=set(),
        ask=set(),
        others="deny",
    ),
    search="allow",  # Subagents can search for library docs and research
)

# Global permissions profile (can be changed at runtime)
# Keep the predefined profile as a pristine template.  The active profile is
# a separate object so editing it cannot silently corrupt the built-in default.
permissions: ToolPermissionsProfile = deepcopy(permissive)


_PROFILE_PATH = Path("~/.config/pico-chat/permission-profiles.toml").expanduser()


def _profile_to_dict(profile: ToolPermissionsProfile) -> dict:
    """Serialize a permission profile to TOML-compatible values."""
    return {
        "read": {"inside_repo": profile.read.inside_repo, "outside_repo": profile.read.outside_repo},
        "write": {"inside_repo": profile.write.inside_repo, "outside_repo": profile.write.outside_repo},
        "patch": {"inside_repo": profile.patch.inside_repo, "outside_repo": profile.patch.outside_repo},
        "search": profile.search,
        "run": {
            "allow": sorted(profile.run.allow),
            "ask": sorted(profile.run.ask),
            "deny": sorted(profile.run.deny),
            "others": profile.run.others,
            "chain_policy": profile.run.chain_policy,
            "use_container": profile.run.use_container,
            "container_network": profile.run.container_network,
        },
    }


def _profile_from_dict(name: str, data: dict) -> ToolPermissionsProfile:
    """Build a profile loaded from TOML."""
    def file_permissions(key: str) -> FilePermissions:
        values = data.get(key, {})
        return FilePermissions(
            inside_repo=values.get("inside_repo", "deny"),
            outside_repo=values.get("outside_repo", "deny"),
        )

    run = data.get("run", {})
    return ToolPermissionsProfile(
        name=name,
        read=file_permissions("read"),
        write=file_permissions("write"),
        patch=file_permissions("patch"),
        search=data.get("search", "deny"),
        run=RunPermissions(
            allow=set(run.get("allow", [])),
            ask=set(run.get("ask", [])),
            deny=set(run.get("deny", [])),
            others=run.get("others", "deny"),
            chain_policy=run.get("chain_policy", "ask"),
            use_container=bool(run.get("use_container", False)),
            container_network=bool(run.get("container_network", False)),
        ),
    )


def apply_profile(source: ToolPermissionsProfile, target: ToolPermissionsProfile | None = None) -> None:
    """Apply a profile in place so existing harnesses see the new settings."""
    if target is None:
        target = permissions
    target.name = source.name
    target.read = FilePermissions(source.read.inside_repo, source.read.outside_repo)
    target.write = FilePermissions(source.write.inside_repo, source.write.outside_repo)
    target.patch = FilePermissions(source.patch.inside_repo, source.patch.outside_repo)
    target.search = source.search
    target.run = RunPermissions(
        allow=set(source.run.allow), ask=set(source.run.ask), deny=set(source.run.deny),
        others=source.run.others, chain_policy=source.run.chain_policy,
        use_container=source.run.use_container, container_network=source.run.container_network,
    )


def save_profile(name: str, profile: ToolPermissionsProfile | None = None) -> None:
    """Save a named permission profile to the user config directory."""
    if profile is None:
        profile = permissions
    name = name.strip()
    if not name or any(char in name for char in "[]\\"):
        raise ValueError("Profile name must be non-empty and cannot contain '[' or '\\'")
    data = toml.load(_PROFILE_PATH) if _PROFILE_PATH.exists() else {}
    data.setdefault("profiles", {})[name] = _profile_to_dict(profile)
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(toml.dumps(data), encoding="utf-8")


def load_profile(name: str) -> ToolPermissionsProfile:
    """Load a named permission profile without applying it."""
    if not _PROFILE_PATH.exists():
        raise KeyError(f"Permission profile not found: {name}")
    data = toml.load(_PROFILE_PATH).get("profiles", {})
    if name not in data:
        raise KeyError(f"Permission profile not found: {name}")
    return _profile_from_dict(name, data[name])


def list_profiles() -> list[str]:
    """Return saved permission profile names."""
    if not _PROFILE_PATH.exists():
        return []
    return sorted(toml.load(_PROFILE_PATH).get("profiles", {}).keys())


def delete_profile(name: str) -> None:
    """Delete a saved permission profile."""
    if not _PROFILE_PATH.exists():
        raise KeyError(f"Permission profile not found: {name}")
    data = toml.load(_PROFILE_PATH)
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise KeyError(f"Permission profile not found: {name}")
    del profiles[name]
    _PROFILE_PATH.write_text(toml.dumps(data), encoding="utf-8")


def rename_profile(old_name: str, new_name: str) -> None:
    """Rename a saved permission profile without changing its policy."""
    new_name = new_name.strip()
    if not new_name or any(char in new_name for char in "[]\\"):
        raise ValueError("Profile name must be non-empty and cannot contain '[' or '\\'")
    if not _PROFILE_PATH.exists():
        raise KeyError(f"Permission profile not found: {old_name}")
    data = toml.load(_PROFILE_PATH)
    profiles = data.get("profiles", {})
    if old_name not in profiles:
        raise KeyError(f"Permission profile not found: {old_name}")
    if new_name != old_name and new_name in profiles:
        raise ValueError(f"Permission profile already exists: {new_name}")
    profiles[new_name] = profiles.pop(old_name)
    _PROFILE_PATH.write_text(toml.dumps(data), encoding="utf-8")
