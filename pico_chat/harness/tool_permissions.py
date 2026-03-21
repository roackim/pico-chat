"""
Tool permissions configuration system.

Provides granular permission control for LLM tools:
- read/write/patch: Inside/outside repo granularity
- run: Command execution with containerization toggle
"""
from dataclasses import dataclass
from typing import Literal


Permission = Literal["allow", "ask", "deny"]


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
    """Permissions for shell command execution."""
    enabled: Permission
    # Containerization toggle - future feature
    # NOTE: containerization cannot be applied to file operations outside repo
    use_container: bool = False
    
    def get(self) -> Permission:
        """Get permission for running commands."""
        return self.enabled


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
    
    def get_run_permission(self) -> Permission:
        """Get run permission."""
        return self.run.get()


# --- Predefined Profiles ---

# Strict profile: ask for everything
strict = ToolPermissionsProfile(
    name="strict",
    read=FilePermissions(inside_repo="ask", outside_repo="deny"),
    write=FilePermissions(inside_repo="ask", outside_repo="deny"),
    patch=FilePermissions(inside_repo="ask", outside_repo="deny"),
    run=RunPermissions(enabled="ask", use_container=False),
)

safe = ToolPermissionsProfile(
    name="safe",
    read=FilePermissions(inside_repo="allow", outside_repo="deny"),
    write=FilePermissions(inside_repo="allow", outside_repo="deny"),
    patch=FilePermissions(inside_repo="allow", outside_repo="deny"),
    run=RunPermissions(enabled="ask", use_container=True),
)

# Permissive profile: allow operations inside repo, ask for outside/commands
permissive = ToolPermissionsProfile(
    name="permissive",
    read=FilePermissions(inside_repo="allow", outside_repo="ask"),
    write=FilePermissions(inside_repo="allow", outside_repo="deny"),
    patch=FilePermissions(inside_repo="allow", outside_repo="deny"),
    run=RunPermissions(enabled="ask", use_container=False),
)

# Unrestricted profile: allow everything (use with caution!)
unrestricted = ToolPermissionsProfile(
    name="unrestricted",
    read=FilePermissions(inside_repo="allow", outside_repo="allow"),
    write=FilePermissions(inside_repo="allow", outside_repo="allow"),
    patch=FilePermissions(inside_repo="allow", outside_repo="allow"),
    run=RunPermissions(enabled="allow", use_container=False),
)

# Locked profile: deny everything
locked = ToolPermissionsProfile(
    name="locked",
    read=FilePermissions(inside_repo="deny", outside_repo="deny"),
    write=FilePermissions(inside_repo="deny", outside_repo="deny"),
    patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
    run=RunPermissions(enabled="deny", use_container=False),
)

# Global permissions profile (can be changed at runtime)
permissions: ToolPermissionsProfile = permissive
