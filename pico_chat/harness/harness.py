import json
import logging
from typing import AsyncGenerator, Any, Dict, List

from openai import AsyncOpenAI
from pico_chat.config import get_config
from pico_chat.harness.llm_status import AgentState
from pico_chat.harness.debug import get_debug_stream

# Re-implementation based on minichat.py for maximum performance and simplicity
# Discarding complex Gateway logic in favor of direct AsyncOpenAI usage.

class Harness:
    def __init__(self, config_path: str | None = None):
        self.config = get_config(config_path)
        self.debug_stream = get_debug_stream(config_path)
        self.state = AgentState.IDLE
        self.history = []
        
        # Tools initialization (simulating minichat.py)
        self.tools_map = { } # TODO: currently empty
        self.tool_schemas = [tool.get_schema() for tool in self.tools_map.values()]
        
        # Direct Client Initialization (No Polling, No Gateway)
        self.client = AsyncOpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )
        self.debug_stream.log("INIT", f"Connected to {self.config.base_url}")

    async def start(self):
        """No-op: No background tasks needed."""
        pass

    async def stop(self):
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
        
        # Construct full message list with system prompt
        # Note: minichat.py keeps a running list of messages. We do the same via self.history.
        # Ensure system prompt is at the start (or just rely on clean history logic from outside if reset?)
        # For now, prepending system prompt if history doesn't have it (or just always prepending for context window mgmt later)
        # minichat.py initializes messages list once. We'll prepend system prompt for the API call if it's not in history.
        # But wait, self.history includes user/assistant turns.
        
        system_msg = {"role": "system", "content": "You are a helpful AI assistant with access to tools. Use them when necessary."}
        messages = [system_msg] + self.history

        # Agent Loop (Handle Multi-step Tool Calls)
        while True:
            self.state = AgentState.THINKING
            self.debug_stream.log("REQUEST", messages)
            
            try:
                stream = await self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=self.tool_schemas,
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
                
                self.history.append(assistant_msg)
                messages.append(assistant_msg) # Keep in sync for next loop iteration
                
                # If no tools, we are done
                if not tool_calls_buffer:
                    break
                    
                # Execute Tools (Inner Loop)
                self.state = AgentState.THINKING
                yield f"\n\033[90m[Executing {len(tool_calls_list)} tool calls...]\033[0m\n"
                
                for tc in tool_calls_list:
                    func_name = tc["function"]["name"]
                    args_str = tc["function"]["arguments"]
                    call_id = tc["id"]
                    
                    self.debug_stream.log("TOOL_EXEC", {"name": func_name, "args": args_str})
                    
                    result = ""
                    if func_name in self.tools_map:
                        try:
                            # Parse args
                            args = json.loads(args_str)
                            # Execute
                            result = self.tools_map[func_name].execute(**args)
                            if not isinstance(result, str):
                                result = str(result)
                        except json.JSONDecodeError:
                             result = f"Error: Invalid JSON arguments: {args_str}"
                        except Exception as e:
                            result = f"Error executing {func_name}: {str(e)}"
                    else:
                        result = f"Error: Tool '{func_name}' not found"
                        
                    # Append tool result to history
                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result
                    }
                    self.history.append(tool_msg)
                    messages.append(tool_msg)
                    
                    # Yield minimal feedback
                    yield f"\033[90m> {func_name} executed.\033[0m\n"

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
