"""
Security layer for command execution.

Provides:
- Operator parsing (quote-aware splitting of command chains)
- Permission-based command checking
- Dangerous pattern detection for escalation
- User confirmation for interactive commands
"""
from typing import List, Tuple, Optional, Callable, Literal, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from pico_chat.harness.tool_permissions import RunPermissions

# Import dangerous patterns for escalation checking
from pico_chat.harness.tool_permissions import CMD_DANGEROUS_PATTERNS


class CommandAction(Enum):
    """Action to take for a command"""
    ALLOW = "allow"       # Auto-allowed
    ASK = "ask"           # Needs user confirmation
    DENY = "deny"         # Never allowed


@dataclass
class CommandCheck:
    """Result of command security check"""
    allowed: bool
    action: CommandAction
    message: str


def parse_operators(command: str) -> List[str]:
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


def check_command(command: str, permissions: 'RunPermissions') -> CommandCheck:
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
        permissions: 'RunPermissions',
        confirmation_callback: Optional[Callable[[str], bool]] = None
    ):
        """
        Args:
            permissions: RunPermissions object defining command policies
            confirmation_callback: Function that prompts user and returns True if approved
        """
        self.permissions = permissions
        self.confirmation_callback = confirmation_callback
    
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
        # Simplified chain detection: if any operators exist anywhere (even in strings),
        # consider it a chain and check chain_policy
        has_operators = any(op in command for op in ['|', '&&', '||', ';'])
        
        if has_operators:
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
        
        # Parse into individual commands for single-command checks
        commands = parse_operators(command)
        
        if not commands:
            return False, "Empty command"
        
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

# TODO: rework message passing with proper status, like return status, str