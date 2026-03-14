import inspect
import time
import asyncio
from typing import Dict, Any, Callable, Optional, Tuple, List, Union

class CommandRouter:
    """
    Routes commands to registered handler functions.
    Implements Layer 1 (Lossless Execution) semantics.
    """
    def __init__(self):
        self._commands: Dict[str, Dict[str, Any]] = {}

    def command(self, name: str, description: str = ""):
        """Decorator to register a command handler."""
        def decorator(func: Callable):
            self._commands[name] = {
                "handler": func,
                "description": description,
                "is_async": inspect.iscoroutinefunction(func)
            }
            return func
        return decorator

    async def run_single(self, name: str, args: List[str], stdin: Optional[str] = None) -> Tuple[str, str, int, float]:
        """
        Executes a single command.
        Returns: (stdout, stderr, exit_code, duration_ms)
        """
        start_time = time.perf_counter()
        
        if name not in self._commands:
            duration = (time.perf_counter() - start_time) * 1000
            return "", f"unknown command: {name}. Available: {', '.join(sorted(self._commands.keys()))}", 127, duration

        cmd_info = self._commands[name]
        handler = cmd_info["handler"]
        
        try:
            if cmd_info["is_async"]:
                result = await handler(args, stdin)
            else:
                result = handler(args, stdin)
            
            # Handler should return (stdout, stderr, exit_code)
            # If it only returns stdout (str), assume success
            if isinstance(result, str):
                stdout, stderr, exit_code = result, "", 0
            elif isinstance(result, tuple):
                stdout, stderr, exit_code = result
            else:
                stdout, stderr, exit_code = str(result), "", 0
                
        except Exception as e:
            stdout, stderr, exit_code = "", f"error executing {name}: {str(e)}", 1
            
        duration = (time.perf_counter() - start_time) * 1000
        return stdout, stderr, exit_code, duration

    def get_help(self) -> str:
        """Returns a brief help message for all commands."""
        help_lines = ["Available commands:"]
        for name, info in sorted(self._commands.items()):
            desc = info["description"].split('\n')[0] # First line only
            help_lines.append(f"  {name.ljust(10)} - {desc}")
        return "\n".join(help_lines)

# Singleton instance
router = CommandRouter()
