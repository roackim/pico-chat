"""
Security layer for command execution.

Provides:
- Operator parsing (quote-aware splitting of command chains)
- Command whitelist checking
- User confirmation for interactive commands
"""
from typing import List, Tuple, Optional, Callable
from dataclasses import dataclass
from enum import Enum


class CommandCategory(Enum):
    """Command security categories"""
    SAFE = "safe"           # Auto-allowed
    INTERACTIVE = "interactive"  # Needs user confirmation
    BLOCKED = "blocked"     # Never allowed


@dataclass
class CommandCheck:
    """Result of command security check"""
    allowed: bool
    category: CommandCategory
    message: str


# Command classification
SAFE_COMMANDS = {
    # File reading
    'cat', 'head', 'tail', 'less', 'more',
    # File discovery
    'ls', 'find', 'tree', 'file', 'which',
    # Text processing
    'grep', 'awk', 'sed', 'cut', 'sort', 'uniq', 'wc',
    # Utilities
    'echo', 'pwd', 'basename', 'dirname', 'realpath', 'date',
    # File operations (within workspace)
    'cp', 'mv', 'mkdir', 'touch', 'ln',
}

INTERACTIVE_COMMANDS = {
    'curl', 'wget',           # Network access
    'git',                    # Version control
    'python', 'python3',      # Code execution
    'node', 'npm', 'npx',     # JavaScript
    'rm', 'rmdir',            # Deletion
}

BLOCKED_COMMANDS = {
    'bash', 'sh', 'zsh', 'fish',  # Shell spawning
    'eval', 'exec',               # Code injection vectors
    'dd', 'mkfs',                 # Low-level operations
    'sudo', 'su', 'doas',         # Privilege escalation
    'reboot', 'shutdown',         # System control
}


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


def check_command(command: str) -> CommandCheck:
    """
    Check if a single command is allowed based on whitelist.
    
    Args:
        command: Single command string (no operators)
        
    Returns:
        CommandCheck with allowed status and category
    """
    cmd_name = get_command_name(command)
    
    if not cmd_name:
        return CommandCheck(
            allowed=False,
            category=CommandCategory.BLOCKED,
            message="Empty command"
        )
    
    if cmd_name in BLOCKED_COMMANDS:
        return CommandCheck(
            allowed=False,
            category=CommandCategory.BLOCKED,
            message=f"Command '{cmd_name}' is blocked for security reasons"
        )
    
    if cmd_name in INTERACTIVE_COMMANDS:
        return CommandCheck(
            allowed=False,  # Will be True after user confirmation
            category=CommandCategory.INTERACTIVE,
            message=f"Command '{cmd_name}' requires user confirmation"
        )
    
    if cmd_name in SAFE_COMMANDS:
        return CommandCheck(
            allowed=True,
            category=CommandCategory.SAFE,
            message=f"Command '{cmd_name}' is safe"
        )
    
    # Unknown command - block by default
    return CommandCheck(
        allowed=False,
        category=CommandCategory.BLOCKED,
        message=f"Unknown command '{cmd_name}' (not in whitelist)"
    )


class SecurityChecker:
    """
    Validates command chains against security policies.
    Handles user confirmation for interactive commands.
    """
    
    def __init__(self, confirmation_callback: Optional[Callable[[str], bool]] = None):
        """
        Args:
            confirmation_callback: Function that prompts user and returns True if approved
        """
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
        # Parse into individual commands
        commands = parse_operators(command)
        
        if not commands:
            return False, "Empty command"
        
        # Check each command
        blocked = []
        needs_confirmation = []
        
        for cmd in commands:
            check = check_command(cmd)
            
            if check.category == CommandCategory.BLOCKED:
                blocked.append((cmd, check.message))
            elif check.category == CommandCategory.INTERACTIVE:
                needs_confirmation.append((cmd, check.message))
        
        # If any blocked, reject immediately
        if blocked:
            messages = [f"[ERROR] {msg}" for cmd, msg in blocked]
            return False, "\n".join(messages)
        
        # If any need confirmation, ask user
        if needs_confirmation:
            for cmd, msg in needs_confirmation:
                if self.confirmation_callback:
                    approved = self.confirmation_callback(cmd)
                    if not approved:
                        return False, f"[WARNING] User denied: {cmd}"
                else:
                    # No callback means we can't confirm, so reject
                    return False, f"[WARNING] {msg} (no confirmation mechanism available)"
        
        # All checks passed
        return True, f"[OK] Command validated ({len(commands)} command(s))"
