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
from pico_chat.harness.iteration_tools import IterationTools


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
                "Modify an existing file by replacing one exact code block. "
                "Preferred format: provide path + search + replace. "
                "Use write only for creating new files or full rewrites."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace"
                    },
                    "search": {
                        "type": "string",
                        "description": "Exact existing text block to replace (include enough context to be unique)"
                    },
                    "replace": {
                        "type": "string",
                        "description": "Replacement text block"
                    },
                    "patch_content": {
                        "type": "string",
                        "description": "Legacy replace-block format (backward compatible)"
                    },
                },
                "required": ["path", "search", "replace"]
            }
        )
        self.toolset = toolset
    
    def execute(self, path: str = None, search: str = None, replace: str = None, patch_content: str = None) -> str:
        try:
            return self.toolset.patch(path=path, search=search, replace=replace, patch_content=patch_content)
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


class LoopTool(ToolWrapper):
    """Start unified iteration"""
    
    def __init__(self, iteration_tools: IterationTools):
        super().__init__(
            name="loop",
            description=(
                "Start iteration over files, tasks, or any list. "
                "Supports glob patterns, explicit lists, and references to previous tool outputs."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": (
                            "Items to iterate:\n"
                            "- '@' - Use last run() output\n"
                            "- Glob pattern: '*.py' or 'auth/**/*.py'\n"
                            "- Newline string: 'file1\\nfile2\\nfile3' (auto-split)\n"
                            "- List: ['file1', 'file2', 'task1']"
                        )
                    }
                },
                "required": ["items"]
            }
        )
        self.iteration_tools = iteration_tools
    
    def execute(self, items: str | list[str]) -> str:
        return self.iteration_tools.loop(items)


class LoopNextTool(ToolWrapper):
    """Get next item in iteration"""
    
    def __init__(self, iteration_tools: IterationTools):
        super().__init__(
            name="loop_next",
            description=(
                "Get the next item in the current iteration. "
                "Call this repeatedly to process each item. "
                "Returns the item with progress, or completion message when done."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        self.iteration_tools = iteration_tools
    
    def execute(self) -> str:
        return self.iteration_tools.loop_next()


class LoopItrDoneTool(ToolWrapper):
    """Reflection checkpoint for current iteration item"""
    
    def __init__(self, iteration_tools: IterationTools):
        super().__init__(
            name="loop_itr_done",
            description=(
                "Mark current iteration item as done and reflect on the outcome. "
                "Use this to validate your work before proceeding to the next item. "
                "Returns a reflection prompt asking if you're satisfied with the work."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        self.iteration_tools = iteration_tools
    
    def execute(self) -> str:
        return self.iteration_tools.loop_itr_done()


class LoopAbortTool(ToolWrapper):
    """Abort current iteration"""
    
    def __init__(self, iteration_tools: IterationTools):
        super().__init__(
            name="loop_abort",
            description=(
                "Abort the current iteration (e.g., if you realize the scope is too large). "
                "Returns confirmation of how many files were processed before aborting."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        self.iteration_tools = iteration_tools
    
    def execute(self) -> str:
        return self.iteration_tools.loop_abort()


import asyncio as _asyncio


class _ContextLimitError(Exception):
    def __init__(self, tokens: int):
        self.tokens = tokens


class SubagentTool(ToolWrapper):
    """Spawn a read-only scaffolding subagent (foreground or background)"""

    def __init__(self, workspace_path: str | Path, depth: int, pending_subagents: list):
        super().__init__(
            name="subagent",
            description=(
                "Spawn a read-only scaffolding subagent to explore the codebase and return findings. "
                "The subagent can only read files — it cannot write, patch, or run commands. "
                "Set background=true to queue multiple subagents in parallel; "
                "collect their results with wait_for_subagents. "
                "Returns the subagent's complete text response (foreground) or a queue confirmation (background)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task for the subagent. Be explicit — it has no conversation history."
                    },
                    "background": {
                        "type": "boolean",
                        "description": "If true, run in background and return immediately. Collect results with wait_for_subagents."
                    }
                },
                "required": ["task"]
            }
        )
        self.workspace_path = workspace_path
        self.depth = depth
        self._pending = pending_subagents

    async def _run_subagent(self, task: str) -> str:
        from pico_chat import pico_cfg
        from pico_chat.harness.harness import Harness
        from pico_chat.harness import chunks as chunk_types

        timeout = pico_cfg.config.subagent_timeout
        max_context = pico_cfg.config.subagent_max_context

        sub = Harness(workspace_path=str(self.workspace_path), depth=self.depth + 1)

        result_parts = []
        cumulative_tokens = 0
        last_call_tokens = 0
        in_assistant_turn = False

        async def _collect():
            nonlocal cumulative_tokens, last_call_tokens, in_assistant_turn
            async for chunk in sub.chat(task):
                if isinstance(chunk, chunk_types.MessageStart):
                    if chunk.role == "assistant":
                        if in_assistant_turn:
                            cumulative_tokens += last_call_tokens
                            last_call_tokens = 0
                        in_assistant_turn = True
                elif isinstance(chunk, chunk_types.Content):
                    result_parts.append(chunk.content)
                elif isinstance(chunk, chunk_types.GenerationMetrics):
                    last_call_tokens = chunk.tokens
                    if max_context and (cumulative_tokens + last_call_tokens) > max_context:
                        raise _ContextLimitError(cumulative_tokens + last_call_tokens)

        try:
            await _asyncio.wait_for(_collect(), timeout=timeout)
        except _asyncio.TimeoutError:
            return f"[subagent timed out after {timeout}s]"
        except _ContextLimitError as e:
            return f"[subagent aborted: context limit exceeded ({e.tokens} > {max_context} tokens)]"

        return "".join(result_parts) or "[subagent returned no response]"

    async def execute(self, task: str, background: bool = False) -> str:
        from pico_chat import pico_cfg

        if self.depth >= pico_cfg.config.subagent_max_depth:
            return f"[subagent] Depth limit reached ({pico_cfg.config.subagent_max_depth})."

        if not background:
            return await self._run_subagent(task)

        index = len(self._pending)
        future = _asyncio.create_task(self._run_subagent(task))
        self._pending.append({"index": index, "task": task, "future": future})
        return f"[subagent:{index}] Queued in background."


class WaitForSubagentsTool(ToolWrapper):
    """Wait for all background subagents and collect results"""

    def __init__(self, pending_subagents: list):
        super().__init__(
            name="wait_for_subagents",
            description=(
                "Wait for all background subagents to finish and return their results. "
                "Call this after launching subagents with background=true."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        self._pending = pending_subagents

    async def execute(self) -> str:
        if not self._pending:
            return "[wait_for_subagents] No pending subagents."

        pending = list(self._pending)
        futures = [p["future"] for p in pending]
        results = await _asyncio.gather(*futures, return_exceptions=True)
        self._pending.clear()

        parts = []
        for p, result in zip(pending, results):
            if isinstance(result, Exception):
                parts.append(f"[subagent:{p['index']}] Error: {result}")
            else:
                parts.append(f"[subagent:{p['index']}] Task: {p['task']}\n{result}")

        return "\n\n".join(parts)


def create_minimal_tools(
    workspace_path: str | Path,
    confirmation_callback: Optional[Callable[[str], bool]] = None,
    memory_store: Optional[Dict[str, Dict]] = None,
    iteration_state: Optional[Dict[str, Any]] = None,
    get_tool_output: Optional[Callable[[str], Optional[str]]] = None,
    permissions=None,
    depth: int = 0,
    pending_subagents: Optional[list] = None,
) -> dict[str, ToolWrapper]:
    """
    Create the minimal toolset with harness-compatible wrappers.

    Args:
        workspace_path: Root directory for all operations
        confirmation_callback: Function to prompt user for command confirmation
        memory_store: Reference to harness memory dict (for memory tools)
        iteration_state: Reference to harness iteration dict (for loop tools)
        get_tool_output: Callback to resolve @ references to previous tool outputs
        permissions: ToolPermissionsProfile to use (defaults to default_permissions)
        depth: Current subagent depth (0 = top-level harness)
        pending_subagents: Shared list for background subagent tracking

    Returns:
        Dict of tool name to tool wrapper
    """
    toolset = MinimalToolset(workspace_path, confirmation_callback, permissions=permissions)

    tools = {
        "read": ReadTool(toolset),
        "write": WriteTool(toolset),
        "patch": PatchTool(toolset),
        "run": RunTool(toolset),
    }

    # Memory tools disabled - conversation history serves as working memory
    # To re-enable: uncomment and ensure memory_store is passed to create_minimal_tools()
    # if memory_store is not None:
    #     memory_tools = MemoryTools(memory_store)
    #     tools["memorize"] = MemorizeTool(memory_tools)
    #     tools["forget"] = ForgetTool(memory_tools)

    # Add iteration tools if iteration state is provided
    if iteration_state is not None:
        iteration_tools = IterationTools(workspace_path, iteration_state, get_tool_output)
        tools["loop"] = LoopTool(iteration_tools)
        tools["loop_next"] = LoopNextTool(iteration_tools)
        tools["loop_itr_done"] = LoopItrDoneTool(iteration_tools)
        tools["loop_abort"] = LoopAbortTool(iteration_tools)

    # Add subagent tools if within depth limit
    from pico_chat import pico_cfg
    _pending = pending_subagents if pending_subagents is not None else []
    if depth < pico_cfg.config.subagent_max_depth:
        tools["subagent"] = SubagentTool(workspace_path, depth, _pending)
    tools["wait_for_subagents"] = WaitForSubagentsTool(_pending)

    return tools
