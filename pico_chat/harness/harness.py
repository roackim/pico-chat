import asyncio
import json
import logging
from typing import AsyncGenerator, Any, Dict, List, Optional

from openai import AsyncOpenAI
from pico_chat.config import get_config
from pico_chat.harness.llm_status import AgentState
from pico_chat.harness.debug import get_debug_stream

# Import the minimal toolset
from pico_chat.harness.tool_wrappers import create_minimal_tools

# Import tool feedback formatting
from pico_chat.harness.tool_feedback import (
    format_tool_call_start,
    format_tool_call_complete,
    format_batch_start
)

# Re-implementation based on minichat.py for maximum performance and simplicity
# Discarding complex Gateway logic in favor of direct AsyncOpenAI usage.

class Harness:
    def __init__(self, config_path: str | None = None, workspace_path: str | None = None):
        self.config = get_config(config_path)
        self.debug_stream = get_debug_stream(config_path)
        self.state = AgentState.IDLE
        self.history = []
        
        # User input queue for tool confirmations and prompts
        self._user_response_queue = asyncio.Queue()
        
        # Tools initialization with minimal toolset
        # Use current working directory as workspace if not specified
        import os
        workspace = workspace_path or os.getcwd()
        self.tools_map = create_minimal_tools(
            workspace_path=workspace,
            confirmation_callback=self._request_user_confirmation
        )
        
        # Direct Client Initialization (No Polling, No Gateway)
        self.client = AsyncOpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )
        self.debug_stream.log("INIT", f"Connected to {self.config.base_url}")

    def set_user_response(self, text: str):
        """Called by the UI when a response to a tool's prompt is ready."""
        self._user_response_queue.put_nowait(text)

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

    def start(self):
        """No-op: No background tasks needed."""
        pass

    def stop(self):
        """No-op: No background tasks to cancel."""
        pass

    def get_state(self) -> AgentState:
        return self.state

    async def chat(self, user_input: str) -> AsyncGenerator[str, None]:
        """
        Main chat loop, mimicking minichat.py's direct execution flow.
        Handles: User Input -> LLM -> [Tool Calls -> Tool Execution -> LLM]* -> Final Answer
        """
        # Add user message to history
        self.history.append({"role": "user", "content": user_input})
        
        # System prompt - Minimal (Progressive Discovery principle)
        system_msg = {
            "role": "system", 
            "content": (
                "You are a helpful AI assistant named Pico. Avoid using emojis. Make concise answers when possible."
            )
        }
        messages = [system_msg] + self.history

        # Agent Loop (Handle Multi-step Tool Calls)
        while True:
            self.state = AgentState.THINKING
            self.debug_stream.log("REQUEST", messages)
            
            # Tools are dynamic, so we recalculate schemas for the CLI architecture
            tool_schemas = [tool.get_schema() for tool in self.tools_map.values()] if self.tools_map else None

            try:
                stream = await self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=tool_schemas,
                    stream=True
                )
                
                full_content = ""
                tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
                
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                        
                    delta = chunk.choices[0].delta
                    
                    # 1. Handle Reasoning (DeepSeek/R1 style)
                    # minichat.py doesn't show this but user requested it based on minichat_debug.txt
                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        if self.state != AgentState.THINKING:
                            self.state = AgentState.THINKING
                        
                        # Only yield if config enabled (or force it for debugging?)
                        if self.config.render_thinking:
                            yield f"\033[90m{reasoning}\033[0m"
                        continue

                    # 2. Handle Content
                    content = delta.content
                    if content:
                        if self.state != AgentState.ANSWERING:
                             self.state = AgentState.ANSWERING
                        full_content += content
                        yield content
                        
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

                # End of stream for this turn
                
                # Append assistant message to history
                assistant_msg = {"role": "assistant", "content": full_content if full_content else None}
                
                # Log final answer if not a tool call
                if full_content and not tool_calls_buffer:
                    self.debug_stream.log("RESPONSE", full_content)
                
                # Reconstruct tool calls for history
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
                    assistant_msg["tool_calls"] = tool_calls_list
                
                # Log tool calls from LLM
                if tool_calls_list:
                    self.debug_stream.log("TOOL_CALLS", tool_calls_list)
                
                self.history.append(assistant_msg)
                messages.append(assistant_msg) # Keep in sync for next loop iteration
                
                # If no tools, we are done
                if not tool_calls_buffer:
                    break
                    
                # Execute Tools (Inner Loop)
                self.state = AgentState.THINKING
                yield format_batch_start(len(tool_calls_list))
                
                for tc in tool_calls_list:
                    func_name = tc["function"]["name"]
                    args_str = tc["function"]["arguments"]
                    call_id = tc["id"]
                    
                    self.debug_stream.log("TOOL_EXEC", {"name": func_name, "args": args_str})
                    
                    # Show which tool is being called
                    yield format_tool_call_start(func_name, args_str)
                    
                    result = ""
                    if func_name in self.tools_map:
                        try:
                            # Parse args
                            args = json.loads(args_str)
                            
                            # Check for user input required (e.g. 'ask' command in CLI)
                            # Or if the tool itself is marked as 'suspending' 
                            # If func is async, we await it
                            func = self.tools_map[func_name]
                            
                            if hasattr(func, "is_blocking") and func.is_blocking:
                                # We signal the UI that we are waiting for user input
                                prompt = args.get("prompt", "Please provide input:")
                                yield f"\n\033[94m[System: Waiting for user input: {prompt}]\033[0m\n"
                                
                                # Blocking actually happens here
                                user_resp = await self._wait_for_user_input(prompt)
                                result = f"User responded with: {user_resp}"
                            else:
                                # Execute normally (sync or async if we support both)
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
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result
                    }
                    self.history.append(tool_msg)
                    messages.append(tool_msg)
                    
                    # Show completion feedback
                    yield format_tool_call_complete(func_name, result)

            except Exception as e:
                yield f"\nError: {str(e)}"
                self.debug_stream.log("ERROR", str(e))
                break
        
        self.state = AgentState.IDLE


_harness = None

def get_harness(config_path: str | None = None) -> Harness:
    global _harness
    if _harness is None:
        _harness = Harness(config_path)
    return _harness
