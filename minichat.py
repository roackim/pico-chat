#!/usr/bin/env python3
"""
Minimal chat agent CLI for pico-chat.
Logs all API interactions to 'minichat_debug.txt'.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any, List, Dict

from openai import AsyncOpenAI
from pico_chat.config import get_config

DEBUG_FILE = os.path.abspath("minichat_debug.txt")
REDUCE_DEBUG_LOGS = True

def debug_log(prefix: str, content: Any):
    """Log to debug file."""
    timestamp = datetime.now().isoformat()
    try:
        with open(DEBUG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n[{timestamp}] --- {prefix} ---\n")
            if isinstance(content, (dict, list)):
                f.write(json.dumps(content, indent=2, ensure_ascii=False))
            else:
                f.write(str(content))
            f.write("\n")
    except Exception as e:
        print(f"Debug logging failed: {e}")

async def chat_loop():
    # Load default config
    config = get_config()
    
    # Initialize tools
    tools_map = { } # TODO: currently empty, can add tools here if desired
    
    tool_schemas = [tool.get_schema() for tool in tools_map.values()]
    
    # Initialize client
    client = AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
    )
    
    print(f"Connecting to {config.base_url}...")
    print(f"Logging debug info to {DEBUG_FILE}")
    print("Type 'exit' or 'quit' to stop.\n")

    # Clear debug file
    with open(DEBUG_FILE, "w") as f:
        f.write("=== Minichat Debug Log ===\n")

    messages = [
        {"role": "system", "content": "You are a helpful AI assistant with access to tools. Use them when necessary."}
    ]

    while True:
        try:
            user_input = input("\n\033[92myou:\033[0m ")
        except EOFError:
            break
            
        if user_input.strip().lower() in ("exit", "quit"):
            break
            
        messages.append({"role": "user", "content": user_input})

        # Agent loop (handle tool calls)
        while True:
            debug_log("REQUEST", messages)
            
            # Call LLM
            stream = await client.chat.completions.create(
                model=config.model,
                messages=messages,
                tools=tool_schemas,
                stream=True
            )
            
            print("\n\033[94mllm:\033[0m ", end="", flush=True)
            
            full_content = ""
            tool_calls_buffer: Dict[int, Dict[str, Any]] = {}

            # Cache for stream metadata to avoid redundant logging
            last_meta = {}

            async for chunk in stream:
                # Log the raw chunk
                try:
                    chunk_data = chunk.model_dump(exclude_none=True)
                    
                    if REDUCE_DEBUG_LOGS and isinstance(chunk_data, dict):
                        # Fields that are typically static in a stream
                        # Note: usage usually only appears in the last chunk
                        meta_keys = ["id", "model", "created", "object", "system_fingerprint", "service_tier", "usage"]
                        
                        # Extract current metadata
                        current_meta = {k: chunk_data.get(k) for k in meta_keys if k in chunk_data}
                        
                        # If metadata is identical to previous chunk, strip it from the log output
                        if current_meta == last_meta:
                            for k in meta_keys:
                                chunk_data.pop(k, None)
                        else:
                            last_meta = current_meta

                except AttributeError:
                    chunk_data = str(chunk)
                
                debug_log("CHUNK", chunk_data)
                
                if not chunk.choices:
                    continue
                    
                delta = chunk.choices[0].delta
                
                if delta.content:
                    print(delta.content, end="", flush=True)
                    full_content += delta.content
                    
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

            print() # Newline
            
            # Construct message
            assistant_msg = {"role": "assistant", "content": full_content if full_content else None}
            
            if tool_calls_buffer:
                tool_calls_list = []
                for idx in sorted(tool_calls_buffer.keys()):
                    # Reconstruct tool call object
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
            
            messages.append(assistant_msg)
            debug_log("RESPONSE MESSAGE", assistant_msg)

            # If no tool calls, break inner loop to get user input
            if not tool_calls_buffer:
                break
                
            # Process tool calls
            print(f"\n\033[90mExecuting {len(tool_calls_buffer)} tool calls...\033[0m")
            
            for tc in tool_calls_list:
                func_name = tc["function"]["name"]
                args_str = tc["function"]["arguments"]
                call_id = tc["id"]
                
                print(f"  > {func_name}({args_str[:50]}...)")
                
                if func_name in tools_map:
                    try:
                        args = json.loads(args_str)
                        # The tools execute method might differ. Standardizing to execute(**args)
                        # We need to map tool.execute to match args
                        # Based on typical tool implementation
                        result = tools_map[func_name].execute(**args)
                        
                        # Handle potential non-string returns
                        if not isinstance(result, str):
                            result = str(result)
                            
                    except json.JSONDecodeError:
                        result = f"Error: Invalid JSON arguments: {args_str}"
                    except Exception as e:
                        result = f"Error executing {func_name}: {str(e)}"
                else:
                    result = f"Error: Tool '{func_name}' not found"

                debug_log("TOOL RESULT", {"name": func_name, "args": args_str, "result": result})
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result
                })

if __name__ == "__main__":
    try:
        asyncio.run(chat_loop())
    except KeyboardInterrupt:
        print("\nGoodbye!")
