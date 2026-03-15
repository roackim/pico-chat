"""
Tool wrappers for OpenAI function calling interface.

Adapts the MinimalToolset to the expected harness interface with:
- get_schema() method for OpenAI tool definitions
- execute() method for tool invocation
"""
from pathlib import Path
from typing import Any, Callable, Optional

from pico_chat.harness.tools import MinimalToolset, ToolError


class ToolWrapper:
    """Base wrapper for tools to match harness expected interface"""
    
    def __init__(self, name: str, description: str, parameters: dict):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.is_blocking = False  # Override in subclass if needed
    
    def get_schema(self) -> dict:
        """Return OpenAI function calling schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
    
    def execute(self, **kwargs) -> str:
        """Execute the tool - override in subclass"""
        raise NotImplementedError


class ReadTool(ToolWrapper):
    """Read file content"""
    
    def __init__(self, toolset: MinimalToolset):
        super().__init__(
            name="read",
            description="Read the content of a file from the workspace",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace (e.g., 'config.py' or 'src/main.py')"
                    }
                },
                "required": ["path"]
            }
        )
        self.toolset = toolset
    
    def execute(self, path: str) -> str:
        try:
            return self.toolset.read(path)
        except ToolError as e:
            return str(e)


class WriteTool(ToolWrapper):
    """Write file content"""
    
    def __init__(self, toolset: MinimalToolset):
        super().__init__(
            name="write",
            description="Write content to a file in the workspace (creates or overwrites)",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file"
                    }
                },
                "required": ["path", "content"]
            }
        )
        self.toolset = toolset
    
    def execute(self, path: str, content: str) -> str:
        try:
            return self.toolset.write(path, content)
        except ToolError as e:
            return str(e)


class PatchTool(ToolWrapper):
    """Apply replace-block patch"""
    
    def __init__(self, toolset: MinimalToolset):
        super().__init__(
            name="patch",
            description=(
                "Apply a replace-block patch to modify an existing file. "
                "Use the format:\n"
                "filename.py\n"
                "<<<<<<< SEARCH\n"
                "exact code to find\n"
                "=======\n"
                "replacement code\n"
                ">>>>>>> REPLACE"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patch_content": {
                        "type": "string",
                        "description": "Patch in replace-block format with filename, SEARCH marker, divider, and REPLACE marker"
                    }
                },
                "required": ["patch_content"]
            }
        )
        self.toolset = toolset
    
    def execute(self, patch_content: str) -> str:
        try:
            return self.toolset.patch(patch_content)
        except ToolError as e:
            return str(e)


class RunTool(ToolWrapper):
    """Execute shell command"""
    
    def __init__(self, toolset: MinimalToolset):
        super().__init__(
            name="run",
            description=(
                "Execute a shell command in the workspace. "
                "Supports pipes (|), command chaining (&&, ||, ;). "
                "Safe commands are auto-allowed. Some commands require user confirmation. "
                "Blocked commands will be rejected."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute (e.g., 'ls -la', 'cat file.txt | grep pattern')"
                    }
                },
                "required": ["command"]
            }
        )
        self.toolset = toolset
    
    def execute(self, command: str) -> str:
        try:
            return self.toolset.run(command)
        except ToolError as e:
            return str(e)


def create_minimal_tools(
    workspace_path: str | Path,
    confirmation_callback: Optional[Callable[[str], bool]] = None
) -> dict[str, ToolWrapper]:
    """
    Create the minimal toolset with harness-compatible wrappers.
    
    Args:
        workspace_path: Root directory for all operations
        confirmation_callback: Function to prompt user for command confirmation
        
    Returns:
        Dict of tool name to tool wrapper
    """
    toolset = MinimalToolset(workspace_path, confirmation_callback)
    
    return {
        "read": ReadTool(toolset),
        "write": WriteTool(toolset),
        "patch": PatchTool(toolset),
        "run": RunTool(toolset),
    }
