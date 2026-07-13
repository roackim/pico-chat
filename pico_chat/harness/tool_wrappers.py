"""
Tool wrappers for OpenAI function calling interface.

Adapts the MinimalToolset to the expected harness interface with:
- get_schema() method for OpenAI tool definitions
- execute() method for tool invocation
"""
from pathlib import Path
from typing import Any, Callable, Optional, Dict

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


class SearchWebTool(ToolWrapper):
    """Search the web using DuckDuckGo"""
    
    def __init__(self, search_tools, max_results: int = 3, search_limit: Optional[int] = None):
        super().__init__(
            name="search_web",
            description=(
                "Search the web using DuckDuckGo. Returns top search results with titles, URLs, and snippets. "
                "Use this for: library documentation, API references, recent news, troubleshooting, "
                "technical queries, comparisons, and general web searches. "
                "Prefer this over search_wiki for most queries unless searching for a specific entity or concept."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'python asyncio tutorial', 'rust error handling best practices')"
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["day", "week", "month", "year"],
                        "description": "Optional: filter results by recency (useful for news or recent library updates)"
                    }
                },
                "required": ["query"]
            }
        )
        self.search_tools = search_tools
        self.max_results = max_results
        self.search_limit = search_limit
        self.search_count = 0
    
    def execute(self, query: str, time_range: Optional[str] = None) -> str:
        # Check rate limit
        if self.search_limit is not None and self.search_count >= self.search_limit:
            return f"[search_web] Rate limit reached ({self.search_limit} searches per session)"
        
        self.search_count += 1
        
        try:
            from pico_chat.harness.tools import ToolError
            return self.search_tools.search_web(query, max_results=self.max_results, time_range=time_range)
        except ToolError as e:
            return f"[search_web] {str(e)}"


class SearchWikiTool(ToolWrapper):
    """Search Wikipedia"""
    
    def __init__(self, search_tools, max_results: int = 3, search_limit: Optional[int] = None):
        super().__init__(
            name="search_wiki",
            description=(
                "Search Wikipedia for encyclopedic information. Returns top results with titles, URLs, and snippets. "
                "Use this for: named entities (people, places, organizations), concepts with canonical definitions, "
                "historical events, scientific concepts, algorithms, data structures, and programming paradigms. "
                "NOT recommended for library-specific documentation or recent news."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'Python programming language', 'Binary search algorithm')"
                    }
                },
                "required": ["query"]
            }
        )
        self.search_tools = search_tools
        self.max_results = max_results
        self.search_limit = search_limit
        self.search_count = 0
    
    def execute(self, query: str) -> str:
        # Check rate limit
        if self.search_limit is not None and self.search_count >= self.search_limit:
            return f"[search_wiki] Rate limit reached ({self.search_limit} searches per session)"
        
        self.search_count += 1
        
        try:
            from pico_chat.harness.tools import ToolError
            return self.search_tools.search_wiki(query, max_results=self.max_results)
        except ToolError as e:
            return f"[search_wiki] {str(e)}"


def create_toolset(
    workspace_path: str | Path,
    confirmation_callback: Optional[Callable[[str], bool]] = None,
    permissions=None,
    depth: int = 0,
    pending_subagents: Optional[list] = None,
) -> dict[str, ToolWrapper]:
    """
    Create the minimal toolset with harness-compatible wrappers.

    Args:
        workspace_path: Root directory for all operations
        confirmation_callback: Function to prompt user for command confirmation
        permissions: ToolPermissionsProfile to use (defaults to default_permissions)
        depth: Current subagent depth (0 = top-level harness)
        pending_subagents: Shared list for background subagent tracking

    Returns:
        Dict of tool name to tool wrapper
    """
    from pico_chat.harness.tools import SearchTools
    
    toolset = MinimalToolset(workspace_path, confirmation_callback, permissions=permissions)

    tools = {
        "read": ReadTool(toolset),
        "write": WriteTool(toolset),
        "patch": PatchTool(toolset),
        "run": RunTool(toolset),
    }
    
    # Search tools with depth-based configuration
    search_tools = SearchTools()
    if depth > 0:
        # Subagent: more results per search, but limited number of searches
        search_max_results = 10
        search_limit = 3
    else:
        # Main agent: fewer results per search, unlimited searches
        search_max_results = 3
        search_limit = None
    
    tools["search_web"]  = SearchWebTool(search_tools, max_results=search_max_results, search_limit=search_limit)
    tools["search_wiki"] = SearchWikiTool(search_tools, max_results=search_max_results, search_limit=search_limit)

    # Add subagent tools if within depth limit
    from pico_chat import pico_cfg
    
    _pending = pending_subagents if pending_subagents is not None else []
    if depth < pico_cfg.config.subagent_max_depth:
        tools["subagent"] = SubagentTool(workspace_path, depth, _pending)
        
    tools["wait_for_subagents"] = WaitForSubagentsTool(_pending)

    return tools
