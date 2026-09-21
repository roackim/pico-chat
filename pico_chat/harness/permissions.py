"""
Unified tool-permission decision point.

This module is the single place that answers "may I run this?" for a tool
call.  It combines what used to live in three separate modules:

- ``security.py``       — quote-aware command parsing and allowlist checks.
- ``tool_permissions.py`` — policy data (file/run) and defaults.
- ``permission_gate.py`` — the role-aware gate and prompt building.

``Role`` (see :mod:`pico_chat.harness.roles`) is the source of truth for a
conversation's policy.  The dataclasses here describe the low-level policy
primitives that tools and tests construct directly; they are not a second
user-facing model.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Literal, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pico_chat.harness.roles import Role


Permission = Literal["allow", "ask", "deny"]


# ---------------------------------------------------------------------------
# Command allowlists
# ---------------------------------------------------------------------------

# Default command lists.
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

# Dangerous patterns that escalate ALLOW commands to ASK.
# Maps command name to list of dangerous strings to detect in the full command.
CMD_DANGEROUS_PATTERNS = {
    'find': ['-exec', '-execdir', '-delete', '-ok'],
    'awk': ['system('],
    'sed': ['/e'],  # The 'e' flag in s///e (may have false positives, but safe)
}


# ---------------------------------------------------------------------------
# Policy primitives
# ---------------------------------------------------------------------------

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


# --- Predefined low-level profiles (used by tests and tool defaults) ---

# Strict profile: ask for everything.
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
    ),
)

# Permissive profile: allow operations inside repo, ask for outside/commands.
permissive = ToolPermissionsProfile(
    name="permissive",
    read=FilePermissions(inside_repo="allow", outside_repo="ask"),
    write=FilePermissions(inside_repo="allow", outside_repo="deny"),
    patch=FilePermissions(inside_repo="allow", outside_repo="deny"),
    run=RunPermissions(
        allow=CMD_DEFAULT_ALLOW,
        ask=CMD_DEFAULT_ASK,
        deny=CMD_DEFAULT_DENY,
    ),
)

# Unrestricted profile: allow everything (use with caution!).
unrestricted = ToolPermissionsProfile(
    name="unrestricted",
    read=FilePermissions(inside_repo="allow", outside_repo="allow"),
    write=FilePermissions(inside_repo="allow", outside_repo="allow"),
    patch=FilePermissions(inside_repo="allow", outside_repo="allow"),
    run=RunPermissions(
        allow=set(),
        deny=set(),
        ask=set(),
        others="allow",  # allow all commands
    ),
)

# Locked profile: deny everything.
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
    ),
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
    ),
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
)

# Global permissions profile used when no role policy is supplied.
# Keep the predefined profile as a pristine template.  The active profile is
# a separate object so editing it cannot silently corrupt the built-in default.
permissions: ToolPermissionsProfile = deepcopy(permissive)


# ---------------------------------------------------------------------------
# Policy adapters
#
# Both ``Role`` and ``ToolPermissionsProfile`` answer the same low-level
# questions.  These helpers are the one place that knows how to ask either
# shape, so tools and the gate never need a Role<->profile translation.
# ---------------------------------------------------------------------------

def _is_role_policy(policy) -> bool:
    return hasattr(policy, "policy_for")


def file_permission(policy, tool_name: str, is_inside_repo: bool) -> Permission:
    """Return the file permission for ``tool_name`` (read/write/patch)."""
    if _is_role_policy(policy):
        tool = policy.policy_for(tool_name)
        if not tool.enabled:
            return "deny"
        setting = "inside_repo" if is_inside_repo else "outside_repo"
        default = tool.permission if is_inside_repo else "deny"
        return tool.settings.get(setting, default)
    return getattr(policy, f"get_{tool_name}_permission")(is_inside_repo)


def resolve_run_permissions(policy) -> RunPermissions:
    """Return the effective :class:`RunPermissions` for a role or profile."""
    if _is_role_policy(policy):
        tool = policy.policy_for("run_command")
        if not tool.enabled:
            return RunPermissions(allow=set(), ask=set(), deny=set(), others="deny")
        settings = tool.settings
        return RunPermissions(
            allow=set(settings.get("allow", ())),
            ask=set(settings.get("ask", ())),
            deny=set(settings.get("deny", ())),
            others=settings.get("others", tool.permission),
            chain_policy=settings.get("chain_policy", "ask"),
        )
    return policy.get_run_permission()


# ---------------------------------------------------------------------------
# Command parsing and checks
# ---------------------------------------------------------------------------

class CommandAction(Enum):
    """Action to take for a command."""
    ALLOW = "allow"       # Auto-allowed
    ASK = "ask"           # Needs user confirmation
    DENY = "deny"         # Never allowed


@dataclass
class CommandCheck:
    """Result of command security check."""
    allowed: bool
    action: CommandAction
    message: str


def parse_operators(command: str) -> list[str]:
    """
    Parse command string by operators (|, &&, ||, ;) respecting quotes.

    Args:
        command: Shell command string potentially containing operators

    Returns:
        List of individual commands split by operators

    Examples:
        >>> parse_operators("cat file | grep pattern")
        ['cat file', 'grep pattern']
        >>> parse_operators('echo "a | b" && ls')
        ['echo "a | b"', 'ls']
        >>> parse_operators("cmd1 && cmd2 || cmd3")
        ['cmd1', 'cmd2', 'cmd3']
    """
    result = []
    current = []
    in_single_quote = False
    in_double_quote = False
    escaped = False
    i = 0

    while i < len(command):
        c = command[i]

        # Handle escape sequences
        if escaped:
            current.append(c)
            escaped = False
            i += 1
            continue

        if c == '\\' and not in_single_quote:
            escaped = True
            current.append(c)
            i += 1
            continue

        # Handle quotes
        if c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(c)
            i += 1
            continue

        if c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(c)
            i += 1
            continue

        # Check for operators only if not in quotes
        if not in_single_quote and not in_double_quote:
            # Check for two-character operators (&&, ||)
            if i + 1 < len(command):
                two_char = command[i:i+2]
                if two_char in ('&&', '||'):
                    if current:
                        result.append(''.join(current).strip())
                        current = []
                    i += 2
                    continue

            # Check for single-character operators (|, ;)
            if c in ('|', ';'):
                if current:
                    result.append(''.join(current).strip())
                    current = []
                i += 1
                continue

        current.append(c)
        i += 1

    # Add final command
    if current:
        result.append(''.join(current).strip())

    # Filter out empty strings
    return [cmd for cmd in result if cmd]


def get_command_name(command: str) -> str:
    """
    Extract the base command name from a command string.

    Args:
        command: Command string (e.g., "cat file.txt")

    Returns:
        Base command name (e.g., "cat")
    """
    # Simple split on whitespace, take first token
    # Handle quoted strings if command name itself is quoted (rare)
    parts = command.strip().split(None, 1)
    if not parts:
        return ""
    return parts[0]


def check_command(command: str, permissions: RunPermissions) -> CommandCheck:
    """
    Check if a single command is allowed based on permissions.

    Args:
        command: Single command string (no operators)
        permissions: RunPermissions object with command lists and policies

    Returns:
        CommandCheck with allowed status and action
    """
    cmd_name = get_command_name(command)

    if not cmd_name:
        return CommandCheck(
            allowed=False,
            action=CommandAction.DENY,
            message="Empty command"
        )

    # Check command lists
    if cmd_name in permissions.deny:
        return CommandCheck(
            allowed=False,
            action=CommandAction.DENY,
            message=f"Command '{cmd_name}' is blocked"
        )

    if cmd_name in permissions.ask:
        return CommandCheck(
            allowed=False,
            action=CommandAction.ASK,
            message=f"Command '{cmd_name}' requires confirmation"
        )

    if cmd_name in permissions.allow:
        # Check for dangerous patterns that escalate to ASK
        if cmd_name in CMD_DANGEROUS_PATTERNS:
            for pattern in CMD_DANGEROUS_PATTERNS[cmd_name]:
                if pattern in command:
                    return CommandCheck(
                        allowed=False,
                        action=CommandAction.ASK,
                        message=f"Command '{cmd_name}' with dangerous pattern '{pattern}' requires confirmation"
                    )

        # No dangerous patterns found
        return CommandCheck(
            allowed=True,
            action=CommandAction.ALLOW,
            message=f"Command '{cmd_name}' is allowed"
        )

    # Not in any list - use 'others' policy
    if permissions.others == "allow":
        return CommandCheck(
            allowed=True,
            action=CommandAction.ALLOW,
            message=f"Command '{cmd_name}' allowed (others policy)"
        )
    elif permissions.others == "ask":
        return CommandCheck(
            allowed=False,
            action=CommandAction.ASK,
            message=f"Command '{cmd_name}' requires confirmation (others policy)"
        )
    else:  # deny
        return CommandCheck(
            allowed=False,
            action=CommandAction.DENY,
            message=f"Command '{cmd_name}' not in allowlist"
        )


class SecurityChecker:
    """
    Validates command chains against security policies.
    Handles user confirmation for interactive commands.
    """

    def __init__(
        self,
        permissions: RunPermissions,
        confirmation_callback: Optional[Callable[[str], bool]] = None
    ):
        """
        Args:
            permissions: RunPermissions object defining command policies
            confirmation_callback: Function that prompts user and returns True if approved
        """
        self.permissions = permissions
        self.confirmation_callback = confirmation_callback

    def classify(self, command: str) -> CommandAction:
        """Return the effective action for a command chain without prompting.

        This is the typed decision used by :class:`PermissionGate`; callers no
        longer need to parse human-readable messages to tell *deny* from *ask*.
        """
        commands = parse_operators(command)
        if not commands:
            return CommandAction.DENY

        is_chain = len(commands) > 1
        chain_asks = is_chain and self.permissions.chain_policy == "ask"
        if is_chain and self.permissions.chain_policy == "deny":
            return CommandAction.DENY

        action = CommandAction.ASK if chain_asks else CommandAction.ALLOW
        for cmd in commands:
            check = check_command(cmd, self.permissions)
            if check.action == CommandAction.DENY:
                return CommandAction.DENY
            if check.action == CommandAction.ASK:
                action = CommandAction.ASK
        return action

    def check_chain(self, command: str) -> Tuple[bool, str]:
        """
        Check entire command chain for security.

        Args:
            command: Full command string with potential operators

        Returns:
            Tuple of (allowed: bool, message: str)
            - allowed: True if entire chain is safe to execute
            - message: Feedback message for the LLM
        """
        # Quote-aware chain detection: parse_operators respects quotes,
        # so operators inside quoted strings (e.g. echo "a|b") are not
        # treated as chain separators.
        commands = parse_operators(command)

        if not commands:
            return False, "Empty command"

        is_chain = len(commands) > 1

        if is_chain:
            # Treat as chain - check chain_policy
            if self.permissions.chain_policy == "deny":
                return False, f"[ERROR] Command chains are blocked by policy"
            elif self.permissions.chain_policy == "ask":
                if self.confirmation_callback:
                    approved = self.confirmation_callback(command)
                    if not approved:
                        return False, f"[DENIED] User denied command chain"
                else:
                    return False, f"[DENIED] Command chain requires confirmation (no confirmation mechanism available)"

        # Check each command individually
        denied = []
        needs_confirmation = []

        for cmd in commands:
            check = check_command(cmd, self.permissions)

            if check.action == CommandAction.DENY:
                denied.append((cmd, check.message))
            elif check.action == CommandAction.ASK:
                needs_confirmation.append((cmd, check.message))

        # If any denied, reject immediately
        if denied:
            messages = [f"[ERROR] {msg}" for cmd, msg in denied]
            return False, "\n".join(messages)

        # Handle commands that need confirmation
        for cmd, msg in needs_confirmation:
            if self.confirmation_callback:
                approved = self.confirmation_callback(cmd)
                if not approved:
                    return False, f"[DENIED] User denied: {cmd}"
            else:
                return False, f"[DENIED] {msg} (no confirmation mechanism available)"

        # All checks passed
        return True, f"[OK] Command validated ({len(commands)} command(s))"


# ---------------------------------------------------------------------------
# Permission gate
# ---------------------------------------------------------------------------

def is_inside_workspace(workspace: str | Path, path: str) -> bool:
    """Resolve ``path`` and check whether it is inside ``workspace``."""
    try:
        workspace_resolved = Path(workspace).resolve()
        if Path(path).is_absolute():
            target = Path(path).resolve()
        else:
            target = (workspace_resolved / path).resolve()
        target.relative_to(workspace_resolved)
        return True
    except Exception:
        return False


def build_prompt(tool_name: str, args: dict) -> str:
    """Build a human-readable permission prompt for a tool call."""
    if tool_name == "read":
        return f"Allow reading file: {args.get('path', 'unknown')}?"
    elif tool_name == "write":
        return f"Allow writing to file: {args.get('path', 'unknown')}?"
    elif tool_name == "patch":
        return f"Allow patching file: {args.get('path', 'unknown')}?"
    elif tool_name in ("run", "run_command"):
        command = args.get("command", "unknown")
        return f"Allow running command: {command}?"
    return f"Allow {tool_name}?"


class PermissionGate:
    """Checks tool permissions and manages user-confirmation prompts.

    The gate accepts either a low-level :class:`ToolPermissionsProfile`
    (legacy/tests) or a conversation ``Role``.  When a role is present its
    policies are authoritative; otherwise the profile (or the module-level
    default) is used.  It owns the ``_user_response_queue`` so the Harness
    doesn't have to.
    """

    def __init__(
        self,
        workspace: str,
        permissions: Optional[ToolPermissionsProfile] = None,
        enabled_tools: Optional[set[str]] = None,
        role: Optional["Role"] = None,
    ):
        self._workspace = workspace
        self._workspace_resolved = Path(workspace).resolve()
        self._permissions = permissions  # None = use global default
        self._enabled_tools = enabled_tools
        self._role = role
        self._user_response_queue: asyncio.Queue[str] = asyncio.Queue()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def permissions(self) -> ToolPermissionsProfile:
        """The active permission profile (falls back to the global default)."""
        return self._permissions if self._permissions is not None else permissions

    @property
    def role(self) -> Optional["Role"]:
        return self._role

    def set_user_response(self, text: str):
        """Called by the UI when a response to a tool's prompt is ready."""
        self._user_response_queue.put_nowait(text)

    def set_policy(
        self,
        permissions: Optional[ToolPermissionsProfile] = None,
        enabled_tools: Optional[set[str]] = None,
        role: Optional["Role"] = None,
    ) -> None:
        """Replace the active role policy for a conversation."""
        self._permissions = permissions
        self._enabled_tools = set(enabled_tools) if enabled_tools is not None else None
        self._role = role

    async def wait_for_user_input(self, prompt: str) -> str:
        """Wait for the user to provide text via the UI."""
        return await self._user_response_queue.get()

    @staticmethod
    def build_prompt(tool_name: str, args: dict) -> str:
        """Build a human-readable permission prompt for a tool call."""
        return build_prompt(tool_name, args)

    def check(self, tool_name: str, args: dict) -> str:
        """Check tool permission status.

        Returns:
            ``"allow"`` — auto-approve
            ``"ask"`` — need user permission
            ``"deny"`` — auto-deny
        """
        tool_name = "run_command" if tool_name == "run" else tool_name
        if self._enabled_tools is not None and tool_name not in self._enabled_tools:
            return "deny"

        if self._role is not None:
            policy = self._role.policy_for(tool_name)
            if not policy.enabled:
                return "deny"
            if tool_name in ("subagent", "wait_for_subagents"):
                return policy.permission

        perms = self.permissions

        if tool_name in ("read", "write", "patch"):
            path = args.get("path", "")
            is_inside = self._is_inside_workspace(path)
            if self._role is not None:
                policy = self._role.policy_for(tool_name)
                setting = "inside_repo" if is_inside else "outside_repo"
                return policy.settings.get(setting, policy.permission if is_inside else "deny")
            if tool_name == "read":
                return perms.get_read_permission(is_inside)
            elif tool_name == "write":
                return perms.get_write_permission(is_inside)
            else:
                return perms.get_patch_permission(is_inside)

        elif tool_name == "run_command":
            if self._role is not None:
                return self._check_role_run_permission(args)
            return self._check_run_permission(args, perms.get_run_permission())

        elif tool_name in ("subagent", "wait_for_subagents"):
            # Delegation can execute tools in a child harness, so it must not
            # bypass the active profile's approval policy.
            return "ask"

        return "ask"  # Default to asking

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_inside_workspace(self, path: str) -> bool:
        """Resolve a path and check if it's inside the workspace root."""
        return is_inside_workspace(self._workspace, path)

    def _check_run_permission(self, args: dict, run_perms: RunPermissions) -> str:
        """Check shell command permission via SecurityChecker (typed result)."""
        command = args.get("command", "")
        checker = SecurityChecker(run_perms, confirmation_callback=None)
        return checker.classify(command).value

    def _check_role_run_permission(self, args: dict) -> str:
        """Check shell commands using the active role's run settings."""
        policy = self._role.policy_for("run_command")
        settings = policy.settings
        run_permissions = RunPermissions(
            allow=set(settings.get("allow", ())),
            ask=set(settings.get("ask", ())),
            deny=set(settings.get("deny", ())),
            others=settings.get("others", policy.permission),
            chain_policy=settings.get("chain_policy", "ask"),
        )
        return self._check_run_permission(args, run_permissions)


__all__ = [
    "Permission",
    "FilePermissions",
    "RunPermissions",
    "ToolPermissionsProfile",
    "CMD_DEFAULT_ALLOW",
    "CMD_DEFAULT_ASK",
    "CMD_DEFAULT_DENY",
    "CMD_DANGEROUS_PATTERNS",
    "strict",
    "permissive",
    "unrestricted",
    "locked",
    "TESTING",
    "scaffolder",
    "permissions",
    "CommandAction",
    "CommandCheck",
    "parse_operators",
    "get_command_name",
    "check_command",
    "SecurityChecker",
    "is_inside_workspace",
    "build_prompt",
    "PermissionGate",
]
