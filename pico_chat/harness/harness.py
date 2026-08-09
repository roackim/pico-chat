import asyncio
import inspect
import json
import logging
import time
import uuid
from pathlib import Path
from typing import AsyncGenerator, Any, Dict, List, Optional

from pico_chat.harness.llm_status import AgentState
from pico_chat.harness.debug import get_debug_stream
from pico_chat.harness.context_builder import build_harness_context, is_git_repo
from pico_chat.harness.system_prompt import get_system_message
from pico_chat.harness import chunks
from pico_chat.harness.llm_server import create_server, LLMServer
from pico_chat.harness.llm_server_config import server_config
from pico_chat.harness.permission_gate import PermissionGate
from pico_chat.harness.thinking_parser import ThinkingTagParser, MetricsState

# Import the minimal toolset
from pico_chat.harness.tool_wrappers import create_toolset

import os

logger = logging.getLogger(__name__)


COMPACTION_MARKER_PREFIX = "[COMPACTION_SUMMARY]"

class Harness:
    def __init__(self, workspace_path: str | None = None, depth: int = 0, role=None):
        self.debug_stream = get_debug_stream()
        self.state = AgentState.IDLE
        self.history = []
        self.depth = depth

        # Background subagent tracking
        self._pending_subagents: list = []      # [{index, task, future}, ...]
        self._abort_subagents_event = asyncio.Event()
        
        # Tools initialization with minimal toolset
        import os
        self.workspace = workspace_path or os.getcwd()

        # Subagents use scaffolder (read-only) permissions
        from pico_chat.harness.roles import Role, default_role
        from pico_chat.harness.tool_permissions import scaffolder
        requested_role = role
        if depth > 0:
            role = Role.from_permission_profile(scaffolder, enabled_tools={
                "read", "search_web", "search_wiki", "subagent", "wait_for_subagents",
            })
            role.name = "scaffolder"
        self.role = role or default_role()
        tool_permissions = scaffolder if depth > 0 else (
            self.role.to_permission_profile() if requested_role is not None else None
        )
        self._tool_permissions = tool_permissions  # used by PermissionGate

        # Permission gate owns the user-response queue and path resolution
        self._permission_gate = PermissionGate(
            workspace=self.workspace,
            permissions=tool_permissions,
            enabled_tools=self.role.enabled_tool_names(),
        )

        self.tools_map = create_toolset(
            workspace_path=self.workspace,
            # Subagents are read-only; they never need to ask the user for approval.
            confirmation_callback=None if depth > 0 else self._request_user_confirmation,
            permissions=tool_permissions,
            depth=depth,
            pending_subagents=self._pending_subagents,
        )
        
        # Build initial project context
        self.startup_warnings: list[str] = []
        if not is_git_repo(self.workspace):
            self.startup_warnings.append(
                f"Not a git repository: '{self.workspace}'\n"
                "File tree context is disabled. Initialize a git repo to enable it."
            )
        self.project_context = build_harness_context(self.workspace)
        self.debug_stream.log("CONTEXT", "Project context built")
        
        # Calculate schemas once and log
        self.tools_map = {
            name: tool for name, tool in self.tools_map.items()
            if name in self.role.enabled_tool_names()
        }
        self.tool_schemas = [tool.get_schema() for tool in self.tools_map.values()] if self.tools_map else None
        self.debug_stream.log("TOOL_SCHEMAS", self.tool_schemas)

        # Select LLM server: subagents use subagent_server if configured
        from pico_chat import pico_cfg
        from pico_chat.harness.llm_server_config import get_server_config_by_name
        chosen_config = server_config
        if depth > 0 and pico_cfg.config.subagent_server:
            sub_cfg = get_server_config_by_name(pico_cfg.config.subagent_server)
            if sub_cfg:
                chosen_config = sub_cfg

        self.server: LLMServer = create_server(chosen_config)
        self.debug_stream.log("INIT", f"Server initialized: {chosen_config.name} ({chosen_config.type}) at {chosen_config.base_url}")

    def set_role(self, role) -> None:
        """Apply a role to this conversation before its next turn."""
        from pico_chat.harness.roles import Role

        if not isinstance(role, Role):
            raise TypeError("role must be a Role")
        previous_name = getattr(self, "role", role).name
        self.role = role
        self._tool_permissions = role.to_permission_profile()
        self._permission_gate.set_policy(
            self._tool_permissions,
            role.enabled_tool_names(),
        )
        self.tools_map = create_toolset(
            workspace_path=self.workspace,
            confirmation_callback=None if self.depth > 0 else self._request_user_confirmation,
            permissions=self._tool_permissions,
            depth=self.depth,
            pending_subagents=self._pending_subagents,
        )
        self.tools_map = {
            name: tool for name, tool in self.tools_map.items()
            if name in role.enabled_tool_names()
        }
        self.tool_schemas = [tool.get_schema() for tool in self.tools_map.values()] if self.tools_map else None
        self.debug_stream.log("ROLE", {"name": role.name, "tools": sorted(role.enabled_tool_names())})
        if previous_name != role.name:
            self._add_message_to_history(
                "system",
                f"[Role changed from {previous_name} to {role.name}]",
            )

        # Steering / pause state
        # Updated live on every Thinking chunk so the UI can snapshot it.
        self._current_reasoning: str = ""
        # Set before a generation starts to prefill the assistant <thinking> block.
        self._pending_thinking_prefill: Optional[str] = None
        # Tracks which open tag the last generation actually used (None = reasoning_content path).
        self._last_detected_thinking_tag: Optional[str] = None

    def switch_workspace(self, new_path: str) -> list[str]:
        """Change the workspace directory and rebuild project context.

        Returns a list of warning strings (may be empty).
        Raises ValueError if the path does not exist or is not a directory.
        """
        resolved = Path(new_path).expanduser().resolve()
        if not resolved.exists():
            raise ValueError(f"Path does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Not a directory: {resolved}")

        self.workspace = str(resolved)
        os.chdir(self.workspace)

        # Rebuild project context
        self.project_context = build_harness_context(self.workspace)
        self.debug_stream.log("WORKSPACE", f"Workspace changed to: {self.workspace}")

        # Recheck git-repo warning
        warnings: list[str] = []
        if not is_git_repo(self.workspace):
            warnings.append(
                f"Not a git repository: '{self.workspace}'\n"
                "File tree context is disabled. Initialize a git repo to enable it."
            )
        return warnings

    def switch_server(self, new_config):
        """Switch to a different LLM server at runtime.
        
        Args:
            new_config: LLMServerConfig instance
        """
        from pico_chat.harness.llm_server_config import LLMServerConfig
        
        # Create new server instance
        self.server = create_server(new_config)
        self.debug_stream.log("SWITCH", f"Server switched to: {new_config.name} ({new_config.type}) at {new_config.base_url}")
        logger.info(f"Switched to server: {new_config.name} ({new_config.type})")

    def _is_compaction_message(self, msg: Dict[str, Any]) -> bool:
        """Return True if message is a compaction marker message."""
        if msg.get("role") != "assistant":
            return False
        content = msg.get("content")
        return isinstance(content, str) and content.startswith(COMPACTION_MARKER_PREFIX)

    def _get_last_compaction_index(self) -> Optional[int]:
        """Get index of the most recent compaction marker, if any."""
        for i in range(len(self.history) - 1, -1, -1):
            if self._is_compaction_message(self.history[i]):
                return i
        return None

    def _get_effective_history(self) -> List[Dict[str, Any]]:
        """Return history slice sent to the LLM, starting from latest compaction marker."""
        last_compaction_idx = self._get_last_compaction_index()
        if last_compaction_idx is None:
            return self.history
        return self.history[last_compaction_idx:]

    def _get_tool_output(self, ref: str) -> Optional[str]:
        """
        Get a previous tool output by reference.
        
        Args:
            ref: Reference string (currently only "@" for last run() output)
            
        Returns:
            Tool output or None if not found
        """
        if ref == "@":
            # Get last run() output
            for name, result in reversed(self.tool_output_history):
                if name in ("run", "run_command"):
                    return result
            return None
        
        return None

    def _add_message_to_history(self, role: str, content: Optional[str], **kwargs) -> str:
        """Add a message to history with a unique ID.
        
        Args:
            role: Message role (user, assistant, tool)
            content: Message content
            **kwargs: Additional fields (tool_calls, tool_call_id, name, etc.)
            
        Returns:
            The generated message ID
        """
        msg_id = uuid.uuid4().hex[:8]  # 8-char short ID instead of full UUID
        msg = {
            "id": msg_id,
            "role": role,
            "content": content,
            **kwargs
        }
        self.history.append(msg)
        
        return msg_id

    def set_user_response(self, text: str):
        """Called by the UI when a response to a tool's prompt is ready."""
        self._permission_gate.set_user_response(text)

    def set_thinking_prefill(self, content: str):
        """Queue content to be prepended as the assistant <thinking> prefix on
        the next LLM call.  Subsequent calls overwrite any pending prefill."""
        self._pending_thinking_prefill = content

    def get_current_reasoning(self) -> str:
        """Return the reasoning accumulated so far in the active generation."""
        return self._current_reasoning

    def abort_subagents(self):
        """Called by the UI when the user wants to abort waiting background subagents."""
        self._abort_subagents_event.set()

    async def _wait_for_user_input(self, prompt: str) -> str:
        """Wait for the user to provide text via the UI."""
        return await self._permission_gate.wait_for_user_input(prompt)

    def _check_tool_permission(self, tool_name: str, args: dict) -> str:
        """Check tool permission status. Delegates to PermissionGate."""
        return self._permission_gate.check(tool_name, args)

    def _build_permission_prompt(self, tool_name: str, args: dict) -> str:
        """Build a human-readable permission prompt for a tool call."""
        return PermissionGate.build_prompt(tool_name, args)

    def _request_user_confirmation(self, command: str) -> bool:
        """
        Synchronous callback used by the security checker.

        Since we handle permissions asynchronously via ToolWaitInput chunks,
        we return True here to pass the security check, and handle the actual
        user confirmation in the async tool execution flow.
        """
        return True


    def get_state(self) -> AgentState:
        return self.state

    def clear_history(self):
        """Clear the conversation history for the agent."""
        self.history = []
        self.debug_stream.log("CLEAR", "Conversation history cleared")
    
    def delete_messages_after_id(self, message_id: str, inclusive: bool = True) -> bool:
        """Delete all messages after (and optionally including) the message with given ID.
        
        Args:
            message_id: The ID of the message to delete from
            inclusive: If True, delete the message with this ID too. If False, keep it.
            
        Returns:
            True if message was found and deletion occurred, False otherwise
        """
        for i, msg in enumerate(self.history):
            if msg.get("id") == message_id:
                # Delete messages
                if inclusive:
                    self.history = self.history[:i]
                else:
                    self.history = self.history[:i+1]
                
                self.debug_stream.log("DELETE_AFTER_ID", f"Deleted messages after ID {message_id} (inclusive={inclusive})")
                return True
        return False
    
    def get_message_by_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get a message by its ID.
        
        Args:
            message_id: The ID of the message to find
            
        Returns:
            The message dict if found, None otherwise
        """
        for msg in self.history:
            if msg.get("id") == message_id:
                return msg
        return None

    def list_files_and_folders(self) -> List[str]:
        """Returns a list of all files and folders in the workspace, respecting .gitignore."""
        # Always use flat format for file/folder listing (needed for @file completion)
        context = build_harness_context(self.workspace, format="flat")
        # build_harness_context returns a string with "Project Root: ...", "Files ...", and then the paths
        lines = context.split('\n')
        # Skip the first two lines (Project Root and Files header)
        return [line.strip() for line in lines[2:] if line.strip()]

    def estimate_context_usage(self) -> tuple[int, int, float]:
        """
        Estimate current context usage in tokens.
        Returns: (current_tokens, max_tokens, percentage)
        """
        from pico_chat.harness.token_estimation import estimate_messages_tokens, estimate_tokens
        
        effective_history = self._get_effective_history()
        
        # Check if the first message is a compaction marker
        compacted_tokens = 0
        if effective_history and self._is_compaction_message(effective_history[0]):
            # Extract original token count from compaction marker if available
            content = effective_history[0].get("content", "")
            import re
            match = re.search(r"original_tokens=(\d+)", content)
            if match:
                compacted_tokens = int(match.group(1))
        
        # Estimate tokens for effective history (from latest compaction marker onward)
        current_tokens = estimate_messages_tokens(effective_history)
        
        # If we have compacted history, add the original token count (subtracting the marker itself)
        if compacted_tokens > 0:
            # Subtract the compaction marker's tokens to avoid double-counting
            marker_tokens = estimate_messages_tokens([effective_history[0]])
            current_tokens = current_tokens - marker_tokens + compacted_tokens
        
        # Add system prompt estimation (system message is added during _build_messages)
        # Rough estimate: project context + base system prompt
        system_estimate = estimate_tokens(self.project_context) + 500
        
        current_tokens += system_estimate
        
        # Get max context from server's cached value (will be queried on first use)
        max_tokens = self.server._cached_context_window or 32768
        
        percentage = (current_tokens / max_tokens) * 100 if max_tokens > 0 else 0
        return current_tokens, max_tokens, percentage

    async def compact_history(self) -> Dict[str, Any]:
        """Summarize effective history with one LLM call and insert compaction marker.

        Returns:
            Summary stats describing the compaction operation.
        """
        effective_history = list(self._get_effective_history())
        if not effective_history:
            return {
                "ok": False,
                "reason": "empty",
                "message": "No messages to compact.",
            }

        # Avoid compacting if the effective history is already only one compaction marker.
        if len(effective_history) == 1 and self._is_compaction_message(effective_history[0]):
            return {
                "ok": False,
                "reason": "already_compacted",
                "message": "History is already compacted.",
            }

        model_name = await self.server.get_model_name()
        context_window = await self.server.get_context_window()
        context_window_str = f"{context_window // 1024}k" if isinstance(context_window, int) else str(context_window)

        system_msg = get_system_message(
            project_context=self.project_context,
            model_name=model_name,
            context_window=context_window_str,
            role_name=getattr(getattr(self, "role", None), "name", ""),
            role_prompt=getattr(getattr(self, "role", None), "prompt", ""),
        )

        summarize_user = {
            "role": "user",
            "content": (
                "Summarize the following conversation for future continuation. "
                "The summary will replace the conversation history, so it must be COMPREHENSIVE enough "
                "for the conversation to continue naturally. Include:\n"
                "- Key decisions made and their reasoning\n"
                "- Technical constraints and requirements\n"
                "- Open tasks and next steps\n"
                "- Important file paths, code snippets, and artifacts\n"
                "- Failed attempts and lessons learned\n"
                "- Any context the assistant needs to continue helping\n\n"
                "Be thorough and factual. Preserve all critical technical details. "
                "Aim for at least 20-30% of the original length to maintain quality.\n\n"
                f"Conversation JSON:\n{json.dumps(effective_history, ensure_ascii=False)}"
            ),
        }

        summary_text = ""
        async for response in self.server.create_completion(
            messages=[system_msg, summarize_user],
            tools=None,
            stream=False,
        ):
            if not response.choices:
                continue
            message = response.choices[0].message
            content = getattr(message, "content", None)
            if content:
                summary_text = content.strip()
                break

        if not summary_text:
            raise RuntimeError("Compaction failed: model returned empty summary")

        # Estimate tokens in the original effective history to preserve context accounting
        from pico_chat.harness.token_estimation import estimate_messages_tokens
        original_tokens = estimate_messages_tokens(effective_history)

        compact_message = (
            f"{COMPACTION_MARKER_PREFIX}\n"
            f"compacted_messages={len(effective_history)}\n"
            f"original_tokens={original_tokens}\n\n"
            f"{summary_text}"
        )

        compaction_id = self._add_message_to_history("assistant", compact_message)
        self.debug_stream.log("COMPACT", f"Inserted compaction marker {compaction_id} over {len(effective_history)} messages")

        return {
            "ok": True,
            "message_id": compaction_id,
            "compacted_messages": len(effective_history),
            "summary_chars": len(summary_text),
        }

    async def check_connection(self) -> bool:
        """Check if the LLM server is reachable."""
        return await self.server.check_connection()

    async def get_model_name(self) -> str:
        """
        Get the active model name from the server.
        Returns cached value if already queried.
        """
        return await self.server.get_model_name()

    async def _build_messages(self, user_input: str) -> List[Dict[str, Any]]:
        """Build message list with system prompt and conversation history."""
        # Add user message to history and store its ID
        user_msg_id = self._add_message_to_history("user", user_input)
        self._last_user_message_id = user_msg_id
        
        # Get model context information from server
        model_name = await self.server.get_model_name()
        context_window = await self.server.get_context_window()
        
        # Format context window for display
        if isinstance(context_window, int):
            context_window_str = f"{context_window // 1024}k"
        else:
            context_window_str = str(context_window)
        
        # Build System Prompt with Context
        system_msg = get_system_message(
            project_context=self.project_context,
            model_name=model_name,
            context_window=context_window_str,
            role_name=getattr(getattr(self, "role", None), "name", ""),
            role_prompt=getattr(getattr(self, "role", None), "prompt", ""),
        )
        
        messages = [system_msg]
        messages.extend(self._get_effective_history())
        # Log how much reasoning context is in history
        think_msgs = [m for m in messages if isinstance(m.get('content'), str) and '<think>' in m.get('content', '')]
        if think_msgs:
            logger.info(f"[reasoning] {len(think_msgs)} message(s) in history contain <think> blocks")
        else:
            logger.debug("[reasoning] No <think> blocks in history messages")
        return messages

    async def get_current_context(self) -> List[Dict[str, Any]]:
        """Get the current conversation context (system + history) without modifying state.
        
        Returns the exact message list that would be sent to the LLM.
        Useful for debugging and inspecting what the model sees.
        """
        # Get model context information from server
        model_name = await self.server.get_model_name()
        context_window = await self.server.get_context_window()
        
        # Format context window for display
        if isinstance(context_window, int):
            context_window_str = f"{context_window // 1024}k"
        else:
            context_window_str = str(context_window)
        
        # Build System Prompt with Context
        system_msg = get_system_message(
            project_context=self.project_context,
            model_name=model_name,
            context_window=context_window_str,
            role_name=getattr(getattr(self, "role", None), "name", ""),
            role_prompt=getattr(getattr(self, "role", None), "prompt", ""),
        )
        
        messages = [system_msg]
        messages.extend(self._get_effective_history())
        return messages

    async def _stream_llm_response(self, messages: List[Dict[str, Any]]) -> AsyncGenerator[chunks.Chunk, None]:
        """Stream LLM response and collect content/tool calls.

        Yields: chunks.Chunk subclasses (Thinking, Content, ToolDraft, GenerationMetrics).
        Sets: self._last_full_content, _last_full_reasoning, _last_tool_calls,
              _last_detected_thinking_tag.
        """
        from pico_chat.harness.token_estimation import estimate_tokens
        from pico_chat import pico_cfg

        self.state = AgentState.THINKING
        self.debug_stream.log("REQUEST", messages)

        request_start_time = time.perf_counter()
        first_chunk_received = False
        ttft_ms = None

        metrics = MetricsState()
        parser = ThinkingTagParser()
        tool_calls_buffer: Dict[int, Dict[str, Any]] = {}

        # Reset live reasoning accumulator for this generation
        self._current_reasoning = ""

        metrics_interval = pico_cfg.config.ui_metrics_refresh_interval

        chunk_count = 0
        empty_chunks = 0
        async for chunk in self.server.create_completion(messages, tools=self.tool_schemas, stream=True):
            chunk_count += 1

            if not chunk.choices:
                empty_chunks += 1
                logger.debug(f"Chunk {chunk_count}: No choices")
                continue

            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            if finish_reason:
                logger.debug(f"Chunk {chunk_count}: finish_reason={finish_reason}")
                if hasattr(delta, 'content') and delta.content:
                    logger.debug(f"  Final delta content: {delta.content}")
                if hasattr(delta, 'refusal') and delta.refusal:
                    logger.warning(f"  LLM REFUSAL: {delta.refusal}")
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    logger.debug(f"  Final delta has tool calls")
                if chunk_count <= 3:
                    logger.warning(f"Got finish_reason={finish_reason} on chunk {chunk_count} - very early finish! Possible API error or content filter.")
                    logger.debug(f"  Full chunk: {chunk}")

            if not first_chunk_received:
                ttft = time.perf_counter() - request_start_time
                ttft_ms = ttft * 1000
                logger.info(f"Time-to-first-token: {ttft_ms:.0f}ms")
                self.debug_stream.log("TTFT", f"{ttft_ms:.0f}ms")
                first_chunk_received = True
                metrics.ttft_ms = ttft_ms

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # 1. Handle Reasoning (DeepSeek/R1 style — reasoning_content API field)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if self.state != AgentState.THINKING:
                    self.state = AgentState.THINKING
                metrics.ensure_started()
                metrics.add_tokens(reasoning, estimate_tokens)
                self._current_reasoning += reasoning
                yield chunks.Thinking(content=reasoning)
                m = metrics.maybe_metrics(metrics_interval)
                if m:
                    yield m
                continue

            # 2. Handle Content (with thinking tag parsing)
            content = delta.content
            if content:
                metrics.ensure_started()
                metrics.add_tokens(content, estimate_tokens)

                for segment in parser.feed(content):
                    if segment.is_thinking:
                        if self.state != AgentState.THINKING:
                            self.state = AgentState.THINKING
                        self._current_reasoning += segment.text
                        yield chunks.Thinking(content=segment.text)
                    else:
                        if self.state != AgentState.ANSWERING:
                            self.state = AgentState.ANSWERING
                        yield chunks.Content(content=segment.text)
                    m = metrics.maybe_metrics(metrics_interval)
                    if m:
                        yield m

            # 3. Handle Tool Calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        }
                    elif tc.id:
                        tool_calls_buffer[idx]["id"] = tc.id

                    if tc.function.name:
                        tool_calls_buffer[idx]["function"]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls_buffer[idx]["function"]["arguments"] += tc.function.arguments

                    tc_data = tool_calls_buffer[idx]
                    tool_call_id = tc_data["id"] or f"idx_{idx}"
                    yield chunks.ToolDraft(
                        tool_call_id=tool_call_id,
                        tool_name=tc_data["function"]["name"],
                        tool_args=tc_data["function"]["arguments"]
                    )

        # Flush any remaining content buffer at end of stream
        for segment in parser.flush():
            if segment.is_thinking:
                if self.state != AgentState.THINKING:
                    self.state = AgentState.THINKING
                self._current_reasoning += segment.text
                yield chunks.Thinking(content=segment.text)
            else:
                if self.state != AgentState.ANSWERING:
                    self.state = AgentState.ANSWERING
                yield chunks.Content(content=segment.text)

        # Yield final metrics
        m = metrics.final_metrics()
        if m:
            yield m

        # Reconstruct tool calls list
        tool_calls_list = []
        if tool_calls_buffer:
            for idx in sorted(tool_calls_buffer.keys()):
                tc_data = tool_calls_buffer[idx]
                tool_calls_list.append({
                    "id": tc_data["id"] or f"idx_{idx}",
                    "type": "function",
                    "function": {
                        "name": tc_data["function"]["name"],
                        "arguments": tc_data["function"]["arguments"]
                    }
                })

        # Log results
        full_content = parser.full_content
        full_reasoning = parser.full_reasoning
        if full_content and not tool_calls_list:
            self.debug_stream.log("RESPONSE", full_content)
        if tool_calls_list:
            self.debug_stream.log("TOOL_CALLS", tool_calls_list)

        if not full_content and not tool_calls_list:
            logger.warning(f"LLM returned empty response - no content and no tool calls! Received {chunk_count} chunks ({empty_chunks} empty)")
            logger.debug(f"Total tokens received: {metrics.total_tokens}")
            if chunk_count <= 3:
                logger.warning("Very few chunks received - likely server error or immediate EOF")
        else:
            logger.debug(f"LLM response: {len(full_content)} chars content, {len(tool_calls_list)} tool calls from {chunk_count} chunks")

        # Store results for caller
        self._last_full_content = full_content
        self._last_full_reasoning = full_reasoning
        self._last_detected_thinking_tag = parser.detected_open_tag  # None = reasoning_content API path
        self._last_tool_calls = tool_calls_list


    async def _execute_tool_calls(
        self, 
        tool_calls_list: List[Dict[str, Any]], 
        messages: List[Dict[str, Any]]
    ) -> AsyncGenerator[chunks.Chunk, None]:
        """
        Execute all tool calls following the state machine flow.
        
        Yields: chunks.ToolStatusChange for each state transition
        """
        self.state = AgentState.THINKING
        
        for tc in tool_calls_list:
            tool_name = tc["function"]["name"]
            tool_args = tc["function"]["arguments"]
            tool_call_id = tc["id"]
            
            self.debug_stream.log("TOOL_EXEC", {"name": tool_name, "args": tool_args})
            
            # STEP 1: Check permissions (without executing)
            try:
                args = json.loads(tool_args)
            except json.JSONDecodeError:
                # Invalid JSON - treat as error
                error_msg = f"Invalid JSON arguments: {tool_args}"
                yield chunks.ToolStatusChange(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status=chunks.ToolStatus.ERROR,
                    error=error_msg
                )
                self._add_message_to_history(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_call_id
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": f"Error: {error_msg}"
                })
                continue
            
            permission_decision = self._check_tool_permission(tool_name, args)
            prompt = self._build_permission_prompt(tool_name, args)
            
            # Emit permission request state
            if permission_decision == "ask":
                # Need user input
                yield chunks.ToolStatusChange(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status=chunks.ToolStatus.PERMISSION_REQUESTED,
                    permission_prompt=prompt,
                    auto_decision=False
                )
                
                # Wait for user response
                user_response = await self._wait_for_user_input(prompt)
                approved = user_response.lower() in ["approve", "yes", "y", "allow"]
            else:
                # Auto-approve or auto-deny
                approved = (permission_decision == "allow")
                yield chunks.ToolStatusChange(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status=chunks.ToolStatus.PERMISSION_REQUESTED,
                    permission_prompt=prompt,
                    auto_decision=True
                )
            
            # STEP 2: Emit approval/denial
            if approved:
                yield chunks.ToolStatusChange(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status=chunks.ToolStatus.APPROVED
                )
            else:
                denial_reason = "User denied" if permission_decision == "ask" else "Auto-denied by security policy"
                yield chunks.ToolStatusChange(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status=chunks.ToolStatus.DENIED,
                    denial_reason=denial_reason
                )
                # Add to history and continue to next tool
                # Make the denial message more explicit to help LLM understand what to do
                result = f"[TOOL DENIED] The '{tool_name}' tool call was not executed. Reason: {denial_reason}. You should proceed with answering based on the information from other successful tool calls, or acknowledge the denial and ask if the user would like you to try a different approach."
                logger.debug(f"Tool {tool_name} denied, sending explanation to LLM: {result[:100]}...")
                self._add_message_to_history(
                    role="tool",
                    content=result,
                    tool_call_id=tool_call_id
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result
                })
                continue
            
            # STEP 3: Execute tool
            yield chunks.ToolStatusChange(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=tool_args,
                status=chunks.ToolStatus.EXECUTING
            )
            
            try:
                # Execute the tool
                lookup_name = "run_command" if tool_name == "run" else tool_name
                if lookup_name not in self.tools_map and tool_name == "run":
                    lookup_name = "run"
                if lookup_name not in self.tools_map:
                    raise Exception(f"Tool '{tool_name}' not found")
                
                func = self.tools_map[lookup_name]
                
                # Execute normally (sync or async)
                if inspect.iscoroutinefunction(func.execute):
                    result = await func.execute(**args)
                else:
                    result = func.execute(**args)
                
                if not isinstance(result, str):
                    result = str(result)
                
                # STEP 4: Success
                self.debug_stream.log("TOOL_RESULT", {"call_id": tool_call_id, "result": result})
                
                yield chunks.ToolStatusChange(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status=chunks.ToolStatus.COMPLETED,
                    result=result
                )
                self._add_message_to_history(
                    role="tool",
                    content=result,
                    tool_call_id=tool_call_id
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result
                })
                
            except Exception as e:
                # STEP 4: Error
                error_msg = str(e)
                self.debug_stream.log("TOOL_ERROR", {"call_id": tool_call_id, "error": error_msg})
                yield chunks.ToolStatusChange(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    status=chunks.ToolStatus.ERROR,
                    error=error_msg
                )
                self._add_message_to_history(
                    role="tool",
                    content=f"Error: {error_msg}",
                    tool_call_id=tool_call_id
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": f"Error: {error_msg}"
                })

    async def get_status(self) -> Dict[str, Any]:
        """
        Check server status at startup.
        
        Returns:
            Dictionary with status information
        """
        status = {
            "online": False,
            "server_name": self.server.config.name,
            "server_type": self.server.config.type,
            "base_url": self.server.config.base_url,
            "model": "unknown",
            "context_window": "unknown",
            "context_used": 0,
            "context_max": 0,
            "context_percentage": 0.0,
        }
        
        # Check connection
        status["online"] = await self.server.check_connection()
        
        if status["online"]:
            # Query model info
            try:
                status["model"] = await self.server.get_model_name()
            except Exception as e:
                logger.warning(f"Failed to query model name: {e}")
            
            try:
                ctx = await self.server.get_context_window()
                status["context_window"] = f"{ctx // 1024}k" if isinstance(ctx, int) else str(ctx)
            except Exception as e:
                logger.warning(f"Failed to query context window: {e}")
            
            # Estimate context usage
            try:
                current_tokens, max_tokens, percentage = self.estimate_context_usage()
                status["context_used"] = current_tokens
                status["context_max"] = max_tokens
                status["context_percentage"] = percentage
            except Exception as e:
                logger.warning(f"Failed to estimate context usage: {e}")
        
        return status

    async def _auto_wait_subagents(self) -> AsyncGenerator[chunks.Chunk, None]:
        """Auto-wait for any background subagents still running after the LLM loop ends."""
        if not self._pending_subagents:
            return

        pending = list(self._pending_subagents)
        yield chunks.SubagentsWaiting(count=len(pending))

        futures_map = {p["future"]: p for p in pending}
        remaining = set(futures_map.keys())
        completed = 0
        aborted = 0

        abort_task = asyncio.create_task(self._abort_subagents_event.wait())
        try:
            while remaining:
                done, _ = await asyncio.wait(
                    remaining | {abort_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if abort_task in done:
                    for f in remaining:
                        f.cancel()
                    aborted = len(remaining)
                    remaining.clear()
                    break

                for f in done - {abort_task}:
                    remaining.discard(f)
                    p = futures_map[f]
                    try:
                        result = f.result()
                    except Exception as e:
                        result = f"[error: {e}]"
                    yield chunks.SubagentResult(index=p["index"], task=p["task"], result=result)
                    completed += 1
        finally:
            abort_task.cancel()
            self._abort_subagents_event.clear()
            self._pending_subagents.clear()

        yield chunks.SubagentsDone(completed=completed, aborted=aborted)

    async def chat(self, user_input: str) -> AsyncGenerator[chunks.Chunk, None]:
        """
        Main chat loop orchestrator.
        Handles: User Input -> LLM -> [Tool Calls -> Tool Execution -> LLM]* -> Final Answer
        
        Yields: chunks.Chunk objects - see chunks.py for all chunk types.
        """
        messages = await self._build_messages(user_input)
        
        # Emit user message start with its ID
        yield chunks.MessageStart(message_id=self._last_user_message_id, role="user")

        # Agent Loop (Handle Multi-step Tool Calls)
        while True:
            try:
                from pico_chat import pico_cfg
                
                # Generate assistant message ID upfront so UI can track it
                assistant_msg_id = str(uuid.uuid4())
                yield chunks.MessageStart(message_id=assistant_msg_id, role="assistant")
                
                # Log request about to be sent
                logger.debug(f"Calling LLM with {len(messages)} messages in context")
                
                # Log last few messages for debugging
                last_msgs = messages[-3:] if len(messages) > 3 else messages
                for i, msg in enumerate(last_msgs, start=max(1, len(messages)-2)):
                    role = msg.get("role", "?")
                    content_len = len(str(msg.get("content", "")))
                    tool_calls_count = len(msg.get("tool_calls", []))
                    logger.debug(f"  Message {i}: role={role}, content_len={content_len}, tool_calls={tool_calls_count}")
                    
                    # If this is an assistant message with tool calls, log the IDs
                    if role == "assistant" and msg.get("tool_calls"):
                        for tc in msg.get("tool_calls", []):
                            logger.debug(f"    Tool call ID: {tc.get('id', 'MISSING')}, name: {tc.get('function', {}).get('name', '?')}")
                    
                    # If this is a tool result message, log first 200 chars to check format
                    if role == "tool":
                        content = str(msg.get("content", ""))
                        logger.debug(f"    Tool result preview: {content[:200]}")
                        tool_call_id = msg.get('tool_call_id', 'MISSING!')
                        logger.debug(f"    Tool call ID: {tool_call_id}")
                        if tool_call_id == "MISSING!":
                            logger.error("Tool message is missing tool_call_id - this will cause API errors!")
                
                # Inject pending thinking prefill: append a partial assistant message
                # so the model continues thinking from the steered/resumed position.
                prefill_messages = list(messages)
                if self._pending_thinking_prefill:
                    # Use the same tag the model used last turn so the format is consistent.
                    open_tag = self._last_detected_thinking_tag or THINKING_TAGS[0][0]
                    prefill = self._pending_thinking_prefill
                    if not prefill.endswith('\n'):
                        prefill += '\n'
                    prefill_content = f"{open_tag}\n{prefill}"
                    prefill_messages = messages + [{"role": "assistant", "content": prefill_content}]
                    logger.debug(f"Injecting thinking prefill ({len(prefill)} chars)")
                    self._pending_thinking_prefill = None

                # Stream LLM response
                async for chunk in self._stream_llm_response(prefill_messages):
                    yield chunk
                
                # Collect results from instance variables
                full_content = self._last_full_content
                full_reasoning = self._last_full_reasoning
                tool_calls_list = self._last_tool_calls
                # Tag the model actually used (None for reasoning_content field path)
                detected_tag = getattr(self, '_last_detected_thinking_tag', None)
                
                logger.debug(f"LLM response complete. Content length: {len(full_content) if full_content else 0}, Reasoning length: {len(full_reasoning) if full_reasoning else 0}, Tool calls: {len(tool_calls_list) if tool_calls_list else 0}")
                
                # Optionally reconstruct full output with thinking tags for multi-turn reasoning
                if pico_cfg.config.preserve_reasoning_traces and full_reasoning:
                    # Use the tag the model produced this turn; fall back to THINKING_TAGS[0]
                    # (<think>) when reasoning arrived via the reasoning_content API field.
                    open_tag = detected_tag or THINKING_TAGS[0][0]
                    close_tag = next(c for o, c in THINKING_TAGS if o == open_tag)
                    full_content_for_history = f"{open_tag}\n{full_reasoning}\n{close_tag}\n\n{full_content}"
                    logger.info(f"[reasoning] Stored {len(full_reasoning)} chars of reasoning in history (tag={open_tag!r})")
                else:
                    full_content_for_history = full_content if full_content else None
                    if full_reasoning:
                        logger.warning(f"[reasoning] preserve_reasoning_traces=False, dropping {len(full_reasoning)} chars of reasoning")
                    else:
                        logger.debug("[reasoning] No reasoning to preserve this turn")
                
                # Add assistant message to history with pre-generated ID
                msg = {
                    "id": assistant_msg_id,
                    "role": "assistant",
                    "content": full_content_for_history
                }
                if tool_calls_list:
                    msg["tool_calls"] = tool_calls_list
                self.history.append(msg)
                self._last_assistant_message_id = assistant_msg_id
                
                # Also add to messages for current request (without ID for API call)
                messages.append({
                    "role": "assistant",
                    "content": full_content_for_history,
                    "tool_calls": tool_calls_list if tool_calls_list else None
                })
                
                # If no tools, we're done
                if not tool_calls_list:
                    logger.debug("No tool calls - generation complete")
                    break
                    
                # Execute tools and yield feedback
                logger.debug(f"Executing {len(tool_calls_list)} tool call(s)")
                async for feedback in self._execute_tool_calls(tool_calls_list, messages):
                    yield feedback
                
                logger.debug("Tool execution complete - continuing loop")

            except Exception as e:
                raise e
            
        self.state = AgentState.IDLE

        # Auto-wait for any background subagents still running
        async for chunk in self._auto_wait_subagents():
            yield chunk

_harness = None

def get_harness(config_path: str | None = None) -> Harness:
    global _harness
    if _harness is None:
        _harness = Harness(config_path)
    return _harness
