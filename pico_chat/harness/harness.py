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

    # def set_user_response(self, text: str):
        # """Called by the UI when a response to a tool's prompt is ready."""
        # self._user_response_queue.put_nowait(text)

    async def _wait_for_user_input(self, prompt: str) -> str:
        """Wait for the user to provide text via the UI."""
        # Note: The UI is responsible for seeing the prompt (yielded below) 
        # and then calling set_user_response.
        return await self._user_response_queue.get()
    
    def _request_user_confirmation(self, command: str) -> bool:
        """
        Request user confirmation for a command.
        
        NOTE: This is a synchronous callback used by the security checker,
        but actual confirmation happens in the async chat loop.
        For now, we return False (deny) as the async mechanism handles it.
        
        TODO: Consider refactoring security checker to be async.
        """
        # This is called during security checking which is synchronous
        # The actual user confirmation should happen in the async chat loop
        # For now, we return False to indicate "needs confirmation"
        # The chat loop will detect this and handle it appropriately
        return False


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
                if message_id in self.memory_snapshots:
                    self.memory = self.memory_snapshots[message_id].copy()
                
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
        context = build_harness_context(self.workspace)
        # build_harness_context returns a string with "Project Root: ...", "Files ...", and then the paths
        lines = context.split('\n')
        # Skip the first two lines (Project Root and Files header)
        return [line.strip() for line in lines[2:] if line.strip()]

    def estimate_context_usage(self) -> tuple[int, int, float]:
        """
        Estimate current context usage in tokens.
        Returns: (current_tokens, max_tokens, percentage)
        """
        # Simple estimation: 1 token ~= 4 characters for English text
        total_chars = 0
        for msg in self.history:
            content = msg.get("content")
            if content:
                total_chars += len(content)
            
        # Add system prompt estimation (approx 500 chars)
        total_chars += 500
        
        current_tokens = total_chars // 4
        # Get max context from server's cached value (will be queried on first use)
        max_tokens = self.server._cached_context_window or 32768
        
        percentage = (current_tokens / max_tokens) * 100 if max_tokens > 0 else 0
        return current_tokens, max_tokens, percentage

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
        
        # Inject memory into system message content if any exists (single system message for compatibility)
        if self.memory:
            memory_items = list(self.memory.values())
            # Compact JSON - no pretty printing, keeps metadata
            memory_json = json.dumps(memory_items, separators=(',', ':'), ensure_ascii=False)
            # Append memory to system message content with clear delimiter
            system_msg["content"] += f"\n\nMEMORY:{memory_json}"
        
        messages = [system_msg]
        messages.extend(self.history)
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
        
        # Inject memory into system message content if any exists
        if self.memory:
            memory_items = list(self.memory.values())
            # Compact JSON - no pretty printing, keeps metadata
            memory_json = json.dumps(memory_items, separators=(',', ':'), ensure_ascii=False)
            # Append memory to system message content with clear delimiter
            system_msg["content"] += f"\n\nMEMORY:{memory_json}"
        
        messages = [system_msg]
        messages.extend(self.history)
        return messages

    async def _stream_llm_response(self, messages: List[Dict[str, Any]]) -> AsyncGenerator[chunks.Chunk, None]:
        """
        Stream LLM response and collect content/tool calls.
        
        Yields: chunks.Chunk subclasses:
            - chunks.Thinking: Reasoning content
            - chunks.Content: Regular response content
        
        Sets instance variables:
        - self._last_full_content: Complete response content
        - self._last_tool_calls: Tool calls from the response
        """
        self.state = AgentState.THINKING
        self.debug_stream.log("REQUEST", messages)
        
        # Track time-to-first-token (TTFT)
        request_start_time = time.perf_counter()
        first_chunk_received = False
        
        full_content = ""
        tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
        
        # Use server's create_completion (handles retries automatically)
        async for chunk in self.server.create_completion(messages, tools=self.tool_schemas, stream=True):
            # Log TTFT on first chunk
            if not first_chunk_received:
                ttft = time.perf_counter() - request_start_time
                logger.info(f"Time-to-first-token: {ttft*1000:.0f}ms")
                self.debug_stream.log("TTFT", f"{ttft*1000:.0f}ms")
                first_chunk_received = True
            
            if not chunk.choices:
                continue
                
            delta = chunk.choices[0].delta
            
            # 1. Handle Reasoning (DeepSeek/R1 style)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                if self.state != AgentState.THINKING:
                    self.state = AgentState.THINKING
                
                # Yield structured thinking chunk
                yield chunks.Thinking(content=reasoning)
                continue

            # 2. Handle Content
            content = delta.content
            if content:
                if self.state != AgentState.ANSWERING:
                    self.state = AgentState.ANSWERING
                full_content += content
                yield chunks.Content(content=content)
                
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
                    if tc.function.name:
                        tool_calls_buffer[idx]["function"]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls_buffer[idx]["function"]["arguments"] += tc.function.arguments

        # Reconstruct tool calls list
        tool_calls_list = []
        if tool_calls_buffer:
            for idx in sorted(tool_calls_buffer.keys()):
                tc_data = tool_calls_buffer[idx]
                tool_calls_list.append({
                    "id": tc_data["id"],
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
        Execute all tool calls and update history.
        
        Yields: chunks.Chunk subclasses:
            - chunks.ToolStart: Individual tool execution begins
            - chunks.ToolComplete: Tool finished successfully
            - chunks.ToolWaitInput: Waiting for user input
            - chunks.ToolError: Tool execution failed
        """
        self.state = AgentState.THINKING
        
        for tc in tool_calls_list:
            func_name = tc["function"]["name"]
            args_str = tc["function"]["arguments"]
            call_id = tc["id"]
            
            result = ""
            try:
                self.debug_stream.log("TOOL_EXEC", {"name": func_name, "args": args_str})
                
                # Yield tool start chunk
                yield chunks.ToolStart(name=func_name, args=args_str)
                
                if func_name in self.tools_map:
                    try:
                        # Parse args
                        args = json.loads(args_str)
                        
                        func = self.tools_map[func_name]
                        
                        if hasattr(func, "is_blocking") and func.is_blocking:
                            # Handle blocking tools (e.g. user input)
                            prompt = args.get("prompt", "Please provide input:")
                            yield chunks.ToolWaitInput(prompt=prompt)
                            
                            user_resp = await self._wait_for_user_input(prompt)
                            result = f"User responded with: {user_resp}"
                        else:
                            # Execute normally (sync or async)
                            if asyncio.iscoroutinefunction(func.execute):
                                result = await func.execute(**args)
                            else:
                                result = func.execute(**args)
                        
                        if not isinstance(result, str):
                            result = str(result)

                    except json.JSONDecodeError:
                        result = f"Error: Invalid JSON arguments: {args_str}"
                    except Exception as e:
                        result = f"Error executing {func_name}: {str(e)}"
                else:
                    result = f"Error: Tool '{func_name}' not found"
                
                # Log tool result
                self.debug_stream.log("TOOL_RESULT", {"call_id": call_id, "result": result})
                    
                # Append tool result to history
                self._add_message_to_history(
                    role="tool",
                    content=result,
                    tool_call_id=call_id
                )
                
                # Also add to messages for current request
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result
                })
                
                # Yield tool complete chunk with status
                # Detect status from result content
                if "[DENIED]" in result or "[WARNING] User denied" in result:
                    status = "denied"
                elif result.startswith("[ERROR]"):
                    status = "error"
                else:
                    status = "ok"
                yield chunks.ToolComplete(name=func_name, result=result, status=status)

            except Exception as e:
                # Fallback for system errors during tool processing
                err_msg = f"System Error processing tool call: {str(e)}"
                self.debug_stream.log("TOOL_SYSTEM_ERROR", {"call_id": call_id, "error": err_msg})
                
                # Ensure we append SOMETHING to history so LLM doesn't hang
                if not self.history or self.history[-1].get("tool_call_id") != call_id:
                    self._add_message_to_history(
                        role="tool",
                        content=err_msg,
                        tool_call_id=call_id
                    )
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": err_msg
                    })
                
                yield chunks.ToolError(name=func_name, error=str(e))

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
