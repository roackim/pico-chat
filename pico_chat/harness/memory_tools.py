"""
Memory management tools for LLM agents.

Provides persistent storage for important information across conversation turns.
Memory is automatically snapshot on each user message for rollback support.
"""
from datetime import datetime
from typing import Dict, Any

from pico_chat.harness.token_estimation import estimate_tokens


class MemoryTools:
    """Memory storage tools (memorize, forget)"""
    
    def __init__(self, memory_store: Dict[str, Dict[str, Any]]):
        """
        Args:
            memory_store: Reference to the harness's memory dictionary
        """
        self.memory = memory_store
    
    def memorize(self, key: str, content: str) -> str:
        """
        Store or update a memory item.
        
        Args:
            key: Unique identifier for the memory item
            content: Content to store (can be text or structured data)
            
        Returns:
            Success message
            
        Example:
            >>> tools.memorize("project_goal", "Build a chat UI with TUI components")
            '[OK] Memorized: project_goal (45 tokens)'
        """
        # Create memory item with metadata
        timestamp = datetime.now().strftime("%H:%M:%S")
        token_size = estimate_tokens(content)
        
        self.memory[key] = {
            "key": key,
            "content": content,
            "metadata": {
                "timestamp": timestamp,
                "token_size": token_size
            }
        }
        
        return f"[OK] Memorized: {key} ({token_size} tokens)"
    
    def forget(self, key: str) -> str:
        """
        Remove a memory item.
        
        Args:
            key: Unique identifier of the memory item to remove
            
        Returns:
            Success or error message
            
        Example:
            >>> tools.forget("old_task")
            '[OK] Forgot: old_task'
        """
        if key not in self.memory:
            return f"[ERROR] Memory key not found: {key}"
        
        del self.memory[key]
        return f"[OK] Forgot: {key}"
