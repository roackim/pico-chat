"""
Tool execution feedback formatting for chat display.

Provides functions to format tool calls and results in a user-friendly way.
"""
import json
from typing import Dict, Any


class ToolFeedbackFormatter:
    """Formats tool execution feedback for display in chat"""
    
    def __init__(self, verbose: bool = True):
        """
        Args:
            verbose: If True, show detailed information about tool calls
        """
        self.verbose = verbose
    
    def format_tool_call_start(self, func_name: str, args_str: str) -> str:
        """
        Format message when a tool is about to be called.
        
        Args:
            func_name: Name of the tool being called
            args_str: JSON string of arguments
            
        Returns:
            Formatted message string
        """
        if not self.verbose:
            return f"\033[90m[Tool: {func_name}]\033[0m\n"
        
        try:
            args = json.loads(args_str)
            args_display = self._format_args_for_display(func_name, args)
            return f"\033[94m[Calling {func_name}({args_display})]\033[0m\n"
        except json.JSONDecodeError:
            return f"\033[94m[Calling {func_name}(...)]\033[0m\n"
    
    def format_tool_call_complete(self, func_name: str, result: str) -> str:
        """
        Format message when a tool execution completes.
        
        Args:
            func_name: Name of the tool that executed
            result: Result string from tool execution
            
        Returns:
            Formatted message string
        """
        if not self.verbose:
            return f"\033[90m> {func_name} done\033[0m\n"
        
        # Determine status from result
        if result.startswith('[OK]'):
            status = '\033[92m✓\033[0m'  # Green checkmark
            result_preview = result[4:].strip()  # Remove [OK] prefix
        elif result.startswith('[ERROR]'):
            status = '\033[91m✗\033[0m'  # Red X
            result_preview = result[7:].strip()  # Remove [ERROR] prefix
        elif result.startswith('[WARNING]'):
            status = '\033[93m⚠\033[0m'  # Yellow warning
            result_preview = result[9:].strip()  # Remove [WARNING] prefix
        else:
            status = '\033[90m•\033[0m'  # Gray bullet
            result_preview = result
        
        # Truncate long results
        if len(result_preview) > 80:
            result_preview = result_preview[:77] + "..."
        
        return f"\033[90m{status} {func_name}: {result_preview}\033[0m\n"
    
    def _format_args_for_display(self, func_name: str, args: Dict[str, Any]) -> str:
        """
        Format arguments for readable display.
        
        Args:
            func_name: Name of the tool (to customize display per tool)
            args: Dictionary of arguments
            
        Returns:
            Formatted argument string
        """
        # Customize display per tool type
        if func_name == 'read':
            return f"path='{args.get('path', '?')}'"
        
        elif func_name == 'write':
            path = args.get('path', '?')
            content = args.get('content', '')
            content_preview = f"{len(content)} bytes"
            return f"path='{path}', {content_preview}"
        
        elif func_name == 'patch':
            patch_content = args.get('patch_content', '')
            # Extract filename from patch
            lines = patch_content.split('\n')
            filename = lines[0] if lines else '?'
            return f"file='{filename}'"
        
        elif func_name == 'run':
            command = args.get('command', '?')
            if len(command) > 50:
                command = command[:47] + "..."
            return f"command='{command}'"
        
        else:
            # Generic: show first 2 arguments
            items = []
            for key, value in list(args.items())[:2]:
                if isinstance(value, str) and len(value) > 30:
                    value = value[:27] + "..."
                items.append(f"{key}={repr(value)}")
            
            if len(args) > 2:
                items.append("...")
            
            return ", ".join(items)


# Default formatter instance
_default_formatter = ToolFeedbackFormatter(verbose=True)


def format_tool_call_start(func_name: str, args_str: str) -> str:
    """Format tool call start message using default formatter"""
    return _default_formatter.format_tool_call_start(func_name, args_str)


def format_tool_call_complete(func_name: str, result: str) -> str:
    """Format tool call complete message using default formatter"""
    return _default_formatter.format_tool_call_complete(func_name, result)


def set_verbose(verbose: bool):
    """Set verbosity level for default formatter"""
    global _default_formatter
    _default_formatter = ToolFeedbackFormatter(verbose=verbose)
