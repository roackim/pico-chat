"""
Tool wrappers for OpenAI function calling interface.

Adapts the MinimalToolset to the expected harness interface with:
- get_schema() method for OpenAI tool definitions
- execute() method for tool invocation
"""
from pathlib import Path
from typing import Any, Callable, Optional, Dict

from pico_chat.harness.tools import MinimalToolset, ToolError
from pico_chat.harness.memory_tools import MemoryTools


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


class MemorizeTool(ToolWrapper):
    """Store information in memory"""
    
    def __init__(self, memory_tools: MemoryTools):
        super().__init__(
            name="memorize",
            description=(
                "Store, update or forget information in memory. "
            ),
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Unique identifier for this memory (e.g., 'project_goal', 'main_config_location')"
                    },
                    "content": {
                        "type": "string",
                        "description": "Information to store (can be text or structured data)"
                    }
                },
                "required": ["key", "content"]
            }
        )
        self.memory_tools = memory_tools
    
    def execute(self, key: str, content: str) -> str:
        return self.memory_tools.memorize(key, content)


class ForgetTool(ToolWrapper):
    """Remove information from memory"""
    
    def __init__(self, memory_tools: MemoryTools):
        super().__init__(
            name="forget",
            description="Remove a memory item that is no longer needed or was incorrect",
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Unique identifier of the memory to remove"
                    }
                },
                "required": ["key"]
            }
        )
        self.memory_tools = memory_tools
    
    def execute(self, key: str) -> str:
        return self.memory_tools.forget(key)


def create_minimal_tools(
    workspace_path: str | Path,
    confirmation_callback: Optional[Callable[[str], bool]] = None,
    memory_store: Optional[Dict[str, Dict]] = None
) -> dict[str, ToolWrapper]:
    """
    Create the minimal toolset with harness-compatible wrappers.
    
    Args:
        workspace_path: Root directory for all operations
        confirmation_callback: Function to prompt user for command confirmation
        memory_store: Reference to harness memory dict (for memory tools)
        
    Returns:
        Dict of tool name to tool wrapper
    """
    toolset = MinimalToolset(workspace_path, confirmation_callback)
    
    tools = {
        "read": ReadTool(toolset),
        "write": WriteTool(toolset),
        "patch": PatchTool(toolset),
        "run": RunTool(toolset),
    }
    
    # Add memory tools if memory store is provided
    if memory_store is not None:
        memory_tools = MemoryTools(memory_store)
        tools["memorize"] = MemorizeTool(memory_tools)
        tools["forget"] = ForgetTool(memory_tools)
    
    return tools
