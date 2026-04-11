import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Any, Dict, List, Optional

from pico_chat.harness.llm_status import AgentState
from pico_chat.harness.debug import get_debug_stream
from pico_chat.harness.context_builder import build_harness_context
from pico_chat.harness.system_prompt import get_system_message
from pico_chat.harness import chunks
from pico_chat.harness.llm_server import create_server, LLMServer
from pico_chat.harness.llm_server_config import server_config

# Import the minimal toolset
from pico_chat.harness.tool_wrappers import create_minimal_tools

logger = logging.getLogger(__name__)

# Supported thinking tag delimiters
THINKING_TAGS = [
    ("<think>", "</think>"),
    ("<thinking>", "</thinking>"),
]

COMPACTION_MARKER_PREFIX = "[COMPACTION_SUMMARY]"

class Harness:
    def __init__(self, workspace_path: str | None = None):
        self.debug_stream = get_debug_stream()
        self.state = AgentState.IDLE
        self.history = []
        
        # Memory system
        self.memory = {}  # Current memory state
        self.memory_snapshots = {}  # Snapshots keyed by user message ID
        
        # User input queue for tool confirmations and prompts
        self._user_response_queue = asyncio.Queue()
        
        # Tools initialization with minimal toolset
        import os
        self.workspace = workspace_path or os.getcwd()
        self.tools_map = create_minimal_tools(
            workspace_path=self.workspace,
            confirmation_callback=self._request_user_confirmation,
            memory_store=self.memory
        )
        
        # Build initial project context
        self.project_context = build_harness_context(self.workspace)
        self.debug_stream.log("CONTEXT", "Project context built")
        
        # Calculate schemas once and log
        self.tool_schemas = [tool.get_schema() for tool in self.tools_map.values()] if self.tools_map else None
        self.debug_stream.log("TOOL_SCHEMAS", self.tool_schemas)
        
        # Initialize LLM server
        self.server: LLMServer = create_server(server_config)
        self.debug_stream.log("INIT", f"Server initialized: {server_config.name} ({server_config.type}) at {server_config.base_url}")

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

    def _memory_json(self) -> str:
        """Return compact JSON representation of memory, including explicit empty list."""
        memory_items = list(self.memory.values())
        return json.dumps(memory_items, separators=(',', ':'), ensure_ascii=False)

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
        
        # Take memory snapshot on user messages (for rollback support)
        if role == "user":
            self.memory_snapshots[msg_id] = self.memory.copy()
        
        return msg_id

    def set_user_response(self, text: str):
        """Called by the UI when a response to a tool's prompt is ready."""
        self._user_response_queue.put_nowait(text)

    async def _wait_for_user_input(self, prompt: str) -> str:
        """Wait for the user to provide text via the UI."""
        # Note: The UI is responsible for seeing the prompt (yielded below) 
        # and then calling set_user_response.
        return await self._user_response_queue.get()
    
    def _check_tool_permission(self, tool_name: str, args: dict) -> str:
        """Check tool permission status.
        
        Returns:
            "allow" - auto-approve
            "ask" - need user permission
            "deny" - auto-deny
        """
        from pico_chat.harness.tool_permissions import permissions
        
        if tool_name == "read":
            path = args.get("path", "")
            from pathlib import Path
            try:
                if Path(path).is_absolute():
                    target = Path(path).resolve()
                else:
                    target = (Path(self.workspace) / path).resolve()
                is_inside = target.relative_to(Path(self.workspace).resolve())
                return permissions.get_read_permission(True)
            except:
                return permissions.get_read_permission(False)
        
        elif tool_name == "write":
            path = args.get("path", "")
            from pathlib import Path
            try:
                if Path(path).is_absolute():
                    target = Path(path).resolve()
                else:
                    target = (Path(self.workspace) / path).resolve()
                is_inside = target.relative_to(Path(self.workspace).resolve())
                return permissions.get_write_permission(True)
            except:
                return permissions.get_write_permission(False)
        
        elif tool_name == "patch":
            path = args.get("path", "")
            from pathlib import Path
            try:
                if Path(path).is_absolute():
                    target = Path(path).resolve()
                else:
                    target = (Path(self.workspace) / path).resolve()
                target.relative_to(Path(self.workspace).resolve())
                return permissions.get_patch_permission(True)
            except Exception:
                return permissions.get_patch_permission(False)
        
        elif tool_name == "run":
            # Run command permission - for now return ask if configured
            run_perms = permissions.get_run_permission()
            # Simplified: if others is ask or ask list not empty, return ask
            if run_perms.others == "ask" or len(run_perms.ask) > 0:
                return "ask"
            elif run_perms.others == "deny":
                return "deny"
            else:
                return "allow"
        
        elif tool_name in ["memorize", "forget"]:
            # Memory operations
            return permissions.get_memory_permission()
        
        return "ask"  # Default to asking
    
    def _build_permission_prompt(self, tool_name: str, args: dict) -> str:
        """Build a human-readable permission prompt for a tool call."""
        if tool_name == "read":
            return f"Allow reading file: {args.get('path', 'unknown')}?"
        elif tool_name == "write":
            return f"Allow writing to file: {args.get('path', 'unknown')}?"
        elif tool_name == "patch":
            path = args.get('path', 'unknown')
            return f"Allow patching file: {path}?"
        elif tool_name == "run":
            command = args.get('command', 'unknown')
            # Truncate long commands
            if len(command) > 100:
                command = command[:97] + "..."
            return f"Allow running command: {command}?"
        elif tool_name == "memorize":
            key = args.get('key', 'unknown')
            return f"Allow memorizing: {key}?"
        elif tool_name == "forget":
            key = args.get('key', 'unknown')
            return f"Allow forgetting: {key}?"
        return f"Allow {tool_name}?"
    
    def _request_user_confirmation(self, command: str) -> bool:
        """
        Request user confirmation for a command.
        
        NOTE: This is a synchronous callback used by the security checker.
        Since we handle permissions asynchronously via ToolWaitInput chunks,
        we return True here to pass the security check, and handle the actual
        user confirmation in the async tool execution flow.
        """
        # Return True to pass security check - actual permission handling
        # happens via ToolWaitInput in the async chat loop
        return True


    def get_state(self) -> AgentState:
        return self.state

    def clear_history(self):
        """Clear the conversation history for the agent."""
        self.history = []
        self.memory = {}
        self.memory_snapshots = {}
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
                # Restore memory to this snapshot (if user message)
                # Use clear() + update() to preserve the dict reference that MemoryTools holds
                if message_id in self.memory_snapshots:
                    self.memory.clear()
                    self.memory.update(self.memory_snapshots[message_id])
                
                # Collect deleted messages for snapshot cleanup
                delete_from = i if inclusive else i + 1
                deleted_msgs = self.history[delete_from:]
                
                # Delete messages
                if inclusive:
                    self.history = self.history[:i]
                else:
                    self.history = self.history[:i+1]
                
                # Cleanup orphaned snapshots
                for deleted_msg in deleted_msgs:
                    deleted_id = deleted_msg.get("id")
                    if deleted_id in self.memory_snapshots:
                        del self.memory_snapshots[deleted_id]
                
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
        
        # Estimate tokens for effective history (from latest compaction marker onward)
        current_tokens = estimate_messages_tokens(self._get_effective_history())
        
        # Add system prompt estimation (system message is added during _build_messages)
        # Rough estimate: project context + base system prompt + memory
        system_estimate = estimate_tokens(self.project_context) + 500
        system_estimate += estimate_tokens(self._memory_json())
        
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
            context_window=context_window_str
        )

        summarize_user = {
            "role": "user",
            "content": (
                "Summarize the following conversation for future continuation. "
                "Return concise plain text with these sections in order: "
                "Decisions, Constraints, Open Tasks, Important Artifacts, Failed Attempts. "
                "Be factual and avoid speculation. "
                "Keep it compact and preserve critical technical details.\n\n"
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

        compact_message = (
            f"{COMPACTION_MARKER_PREFIX}\n"
            f"compacted_messages={len(effective_history)}\n\n"
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
            context_window=context_window_str
        )
        
        # Always append memory state so empty memory is explicit as MEMORY:[]
        system_msg["content"] += f"\n\nMEMORY:{self._memory_json()}"
        
        messages = [system_msg]
        messages.extend(self._get_effective_history())
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
            context_window=context_window_str
        )
        
        # Always append memory state so empty memory is explicit as MEMORY:[]
        system_msg["content"] += f"\n\nMEMORY:{self._memory_json()}"
        
        messages = [system_msg]
        messages.extend(self._get_effective_history())
        return messages

    async def _stream_llm_response(self, messages: List[Dict[str, Any]]) -> AsyncGenerator[chunks.Chunk, None]:
        """
        Stream LLM response and collect content/tool calls.
        
        Yields: chunks.Chunk subclasses:
            - chunks.Thinking: Reasoning content
            - chunks.Content: Regular response content
            - chunks.GenerationMetrics: Live performance metrics
        
        Sets instance variables:
        - self._last_full_content: Complete response content
        - self._last_tool_calls: Tool calls from the response
        """
        from pico_chat.harness.token_estimation import estimate_tokens
        from pico_chat import pico_cfg
        
        self.state = AgentState.THINKING
        self.debug_stream.log("REQUEST", messages)
        
        # Track time-to-first-token (TTFT)
        request_start_time = time.perf_counter()
        first_chunk_received = False
        ttft_ms = None
        
        # Track generation metrics
        generation_start_time = None
        total_tokens = 0
        last_metrics_update = 0
        metrics_interval = pico_cfg.config.ui_metrics_refresh_interval
        
        full_content = ""
        tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
        
        # State for parsing thinking tags in content
        content_buffer = ""
        in_thinking_block = False
        current_thinking_open_tag = None
        
        # Use server's create_completion (handles retries automatically)
        async for chunk in self.server.create_completion(messages, tools=self.tool_schemas, stream=True):
            # Log TTFT on first chunk
            if not first_chunk_received:
                ttft = time.perf_counter() - request_start_time
                ttft_ms = ttft * 1000
                logger.info(f"Time-to-first-token: {ttft_ms:.0f}ms")
                self.debug_stream.log("TTFT", f"{ttft_ms:.0f}ms")
                first_chunk_received = True
            
            if not chunk.choices:
                continue
                
            delta = chunk.choices[0].delta
            
            # 1. Handle Reasoning (DeepSeek/R1 style)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if self.state != AgentState.THINKING:
                    self.state = AgentState.THINKING
                
                # Start tracking on first content
                if generation_start_time is None:
                    generation_start_time = time.perf_counter()
                
                # Count tokens and yield content
                total_tokens += estimate_tokens(reasoning)
                yield chunks.Thinking(content=reasoning)
                
                # Yield metrics update periodically
                current_time = time.perf_counter()
                if current_time - last_metrics_update >= metrics_interval:
                    duration = current_time - generation_start_time
                    tokens_per_second = total_tokens / duration if duration > 0 else 0
                    yield chunks.GenerationMetrics(
                        tokens=total_tokens,
                        tokens_per_second=tokens_per_second,
                        ttft_ms=ttft_ms
                    )
                    last_metrics_update = current_time
                
                continue

            # 2. Handle Content (with thinking tag parsing)
            content = delta.content
            if content:
                # Start tracking on first content
                if generation_start_time is None:
                    generation_start_time = time.perf_counter()
                
                # Add to buffer for tag parsing
                content_buffer += content
                # Count tokens for this content chunk
                total_tokens += estimate_tokens(content)
                
                # Parse for thinking tags
                while content_buffer:
                    if not in_thinking_block:
                        # Look for opening thinking tag
                        earliest_pos = len(content_buffer)
                        found_tag = None
                        
                        for open_tag, close_tag in THINKING_TAGS:
                            pos = content_buffer.find(open_tag)
                            if pos != -1 and pos < earliest_pos:
                                earliest_pos = pos
                                found_tag = (open_tag, close_tag)
                        
                        if found_tag:
                            open_tag, close_tag = found_tag
                            # Yield content before the tag
                            if earliest_pos > 0:
                                before_content = content_buffer[:earliest_pos]
                                if self.state != AgentState.ANSWERING:
                                    self.state = AgentState.ANSWERING
                                full_content += before_content
                                yield chunks.Content(content=before_content)
                                
                                # Yield metrics update periodically
                                current_time = time.perf_counter()
                                if current_time - last_metrics_update >= metrics_interval:
                                    duration = current_time - generation_start_time
                                    tokens_per_second = total_tokens / duration if duration > 0 else 0
                                    yield chunks.GenerationMetrics(
                                        tokens=total_tokens,
                                        tokens_per_second=tokens_per_second,
                                        ttft_ms=ttft_ms
                                    )
                                    last_metrics_update = current_time
                            
                            # Enter thinking block
                            in_thinking_block = True
                            current_thinking_open_tag = open_tag
                            # Move past the opening tag (but don't include it in output)
                            content_buffer = content_buffer[earliest_pos + len(open_tag):]
                        else:
                            # No opening tag found, check if we might have a partial tag at the end
                            # Keep the last N characters where N is the length of the longest open tag
                            max_tag_len = max(len(tag[0]) for tag in THINKING_TAGS)
                            if len(content_buffer) > max_tag_len:
                                # Safe to yield everything except potential partial tag
                                safe_content = content_buffer[:-max_tag_len]
                                if self.state != AgentState.ANSWERING:
                                    self.state = AgentState.ANSWERING
                                full_content += safe_content
                                yield chunks.Content(content=safe_content)
                                
                                # Yield metrics update periodically
                                current_time = time.perf_counter()
                                if current_time - last_metrics_update >= metrics_interval:
                                    duration = current_time - generation_start_time
                                    tokens_per_second = total_tokens / duration if duration > 0 else 0
                                    yield chunks.GenerationMetrics(
                                        tokens=total_tokens,
                                        tokens_per_second=tokens_per_second,
                                        ttft_ms=ttft_ms
                                    )
                                    last_metrics_update = current_time
                                
                                content_buffer = content_buffer[-max_tag_len:]
                            break  # Wait for more content
                    else:
                        # Look for closing tag matching the current open tag
                        close_tag = next(close for open_, close in THINKING_TAGS if open_ == current_thinking_open_tag)
                        close_pos = content_buffer.find(close_tag)
                        
                        if close_pos != -1:
                            # Found closing tag - yield thinking content
                            thinking_content = content_buffer[:close_pos]
                            if thinking_content:
                                if self.state != AgentState.THINKING:
                                    self.state = AgentState.THINKING
                                yield chunks.Thinking(content=thinking_content)
                                
                                # Yield metrics update periodically
                                current_time = time.perf_counter()
                                if current_time - last_metrics_update >= metrics_interval:
                                    duration = current_time - generation_start_time
                                    tokens_per_second = total_tokens / duration if duration > 0 else 0
                                    yield chunks.GenerationMetrics(
                                        tokens=total_tokens,
                                        tokens_per_second=tokens_per_second,
                                        ttft_ms=ttft_ms
                                    )
                                    last_metrics_update = current_time
                            
                            # Exit thinking block
                            in_thinking_block = False
                            current_thinking_open_tag = None
                            # Move past the closing tag (don't include it in output)
                            content_buffer = content_buffer[close_pos + len(close_tag):]
                        else:
                            # No closing tag yet, check if we might have a partial at the end
                            if len(content_buffer) > len(close_tag):
                                # Safe to yield as thinking content except potential partial
                                safe_content = content_buffer[:-len(close_tag)]
                                if safe_content:
                                    if self.state != AgentState.THINKING:
                                        self.state = AgentState.THINKING
                                    yield chunks.Thinking(content=safe_content)
                                    
                                    # Yield metrics update periodically
                                    current_time = time.perf_counter()
                                    if current_time - last_metrics_update >= metrics_interval:
                                        duration = current_time - generation_start_time
                                        tokens_per_second = total_tokens / duration if duration > 0 else 0
                                        yield chunks.GenerationMetrics(
                                            tokens=total_tokens,
                                            tokens_per_second=tokens_per_second,
                                            ttft_ms=ttft_ms
                                        )
                                        last_metrics_update = current_time
                                
                                content_buffer = content_buffer[-len(close_tag):]
                            break  # Wait for more content
                
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
        
        # Flush any remaining content buffer at the end
        if content_buffer:
            if in_thinking_block:
                # Unclosed thinking block - yield as thinking (model might have been cut off)
                if self.state != AgentState.THINKING:
                    self.state = AgentState.THINKING
                yield chunks.Thinking(content=content_buffer)
            else:
                # Regular content
                if self.state != AgentState.ANSWERING:
                    self.state = AgentState.ANSWERING
                full_content += content_buffer
                yield chunks.Content(content=content_buffer)
        
        # Yield final metrics
        if generation_start_time is not None:
            final_duration = time.perf_counter() - generation_start_time
            final_tokens_per_second = total_tokens / final_duration if final_duration > 0 else 0
            yield chunks.GenerationMetrics(
                tokens=total_tokens,
                tokens_per_second=final_tokens_per_second,
                ttft_ms=ttft_ms,
                duration_ms=final_duration * 1000
            )

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
        if full_content and not tool_calls_list:
            self.debug_stream.log("RESPONSE", full_content)
        if tool_calls_list:
            self.debug_stream.log("TOOL_CALLS", tool_calls_list)
        
        # Store results in instance variables for caller to access
        self._last_full_content = full_content
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
                result = f"Permission denied: {denial_reason}"
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
                if tool_name not in self.tools_map:
                    raise Exception(f"Tool '{tool_name}' not found")
                
                func = self.tools_map[tool_name]
                
                # Execute normally (sync or async)
                if asyncio.iscoroutinefunction(func.execute):
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
            "memory_items": len(self.memory),
            "memory_tokens": sum(item["metadata"].get("token_size", 0) for item in self.memory.values()),
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
                # Generate assistant message ID upfront so UI can track it
                assistant_msg_id = str(uuid.uuid4())
                yield chunks.MessageStart(message_id=assistant_msg_id, role="assistant")
                
                # Stream LLM response
                async for chunk in self._stream_llm_response(messages):
                    yield chunk
                
                # Collect results from instance variables
                full_content = self._last_full_content
                tool_calls_list = self._last_tool_calls
                
                # Add assistant message to history with pre-generated ID
                msg = {
                    "id": assistant_msg_id,
                    "role": "assistant",
                    "content": full_content if full_content else None
                }
                if tool_calls_list:
                    msg["tool_calls"] = tool_calls_list
                self.history.append(msg)
                self._last_assistant_message_id = assistant_msg_id
                
                # Also add to messages for current request (without ID for API call)
                messages.append({
                    "role": "assistant",
                    "content": full_content if full_content else None,
                    "tool_calls": tool_calls_list if tool_calls_list else None
                })
                
                # If no tools, we're done
                if not tool_calls_list:
                    break
                    
                # Execute tools and yield feedback
                async for feedback in self._execute_tool_calls(tool_calls_list, messages):
                    yield feedback

            except Exception as e:
                raise e
            
        self.state = AgentState.IDLE

_harness = None

def get_harness(config_path: str | None = None) -> Harness:
    global _harness
    if _harness is None:
        _harness = Harness(config_path)
    return _harness
