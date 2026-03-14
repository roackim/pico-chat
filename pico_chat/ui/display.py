"""UI module for Open-Clank.

Handles rendering, console output formatting, and TUI components.
"""

import json

def display_assistant_header():
    """Print the assistant header."""
    print("\033[1m\033[95mAssistant:\033[0m ", end="", flush=True)

def display_tool_call(name: str, args: dict):
    """Display a tool call to the console."""
    if args:
        args_display = ", ".join(f"{k}={repr(v)[:50]}" for k, v in list(args.items())[:3])
        if len(args) > 3:
            args_display += ", ..."
    else:
        args_display = ""
    print(f"\n\033[34m→\033[0m \033[1m{name}\033[0m({args_display})")

def display_tool_result(result: str):
    """Display a tool execution result to the console."""
    # Truncate long results
    if len(result) > 200:
        result_display = result[:200] + "..."
    else:
        result_display = result
    
    # Color code based on result type
    if result.startswith("Error"):
        print(f"\033[31m✗\033[0m {result_display}")
    else:
        print(f"\033[32m✓\033[0m {result_display}")

def display_invalid_args(name: str):
    """Display invalid JSON arguments error."""
    print(f"\n\033[31m✗\033[0m Invalid JSON arguments for tool '\033[1m{name}\033[0m'")
