"""
Tool permissions configuration system.

Provides granular permission control for LLM tools:
- read/write/patch: Inside/outside repo granularity
- run: Command execution with configurable command lists and policies
"""
from dataclasses import dataclass, field
from typing import Literal


Permission = Literal["allow", "ask", "deny"]


# Default command lists (migrated from security.py)
DEFAULT_ALLOW = {
    'cat', 'head', 'tail', 'less', 'more',                      # File reading
    'ls', 'find', 'tree', 'file', 'which',                      # File discovery   
    'grep', 'awk', 'sed', 'cut', 'sort', 'uniq', 'wc',          # Text processing
    'echo', 'pwd', 'basename', 'dirname', 'realpath', 'date',   # Utilities
    'cp', 'mv', 'mkdir', 'touch', 'ln',                         # File writing (non-destructive)
}

DEFAULT_ASK = {
    'curl', 'wget',           # Network access
    'git',                    # Version control
    'python', 'python3',      # Code execution
    'node', 'npm', 'npx',     # JavaScript
    'rm', 'rmdir',            # Deletion
}

DEFAULT_DENY = {
    'bash', 'sh', 'zsh', 'fish',  # Shell spawning
    'eval', 'exec',               # Code injection vectors
    'dd', 'mkfs',                 # Low-level operations
    'sudo', 'su', 'doas',         # Privilege escalation
    'reboot', 'shutdown',         # System control
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
    allow: set[str] = field(default_factory=lambda: DEFAULT_ALLOW.copy())
    deny: set[str] = field(default_factory=lambda: DEFAULT_DENY.copy())
    ask: set[str] = field(default_factory=lambda: DEFAULT_ASK.copy())
    
    # Policy for commands not in any list
    others: Literal["allow", "ask", "deny"] = "deny"
    
    # Policy for command chains (&&, ||, |, ;)
    chain_policy: Literal["ask", "strictest", "allow"] = "strictest"
    #   ask: Always ask when multiple commands detected
    #   strictest: Use the strictest policy of any command in chain
    #   allow: Allow if all individual commands are allowed
    
    # Containerization toggle - future feature
    use_container: bool = False


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
        use_container=False
    ),
)

# Permissive profile: allow operations inside repo, ask for outside/commands
permissive = ToolPermissionsProfile(
    name="permissive",
    read=FilePermissions(inside_repo="allow", outside_repo="ask"),
    write=FilePermissions(inside_repo="allow", outside_repo="deny"),
    patch=FilePermissions(inside_repo="allow", outside_repo="deny"),
    run=RunPermissions(use_container=False),
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
        use_container=False
    ),
)

# Locked profile: deny everything
locked = ToolPermissionsProfile(
    name="locked",
    read=FilePermissions(inside_repo="deny", outside_repo="deny"),
    write=FilePermissions(inside_repo="deny", outside_repo="deny"),
    patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
    run=RunPermissions(
        allow=set(),
        deny=DEFAULT_ALLOW | DEFAULT_ASK | DEFAULT_DENY,
        ask=set(),
        others="deny",
        use_container=False
    ),
)

# Global permissions profile (can be changed at runtime)
permissions: ToolPermissionsProfile = permissive
