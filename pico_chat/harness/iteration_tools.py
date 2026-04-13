"""
Unified iteration tools for systematic processing.

Provides loop/iteration capabilities for LLM agents to:
- Process files (glob patterns or explicit lists)
- Execute plan steps
- Iterate any list of items
- Reference previous tool outputs
"""
import glob
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable


class IterationTools:
    """Unified iteration tools (loop, loop_next, loop_itr_done, loop_abort)"""
    
    def __init__(
        self, 
        workspace_path: str | Path, 
        iteration_state: Dict[str, Any],
        get_tool_output: Optional[Callable[[str], Optional[str]]] = None
    ):
        """
        Args:
            workspace_path: Root directory for file operations
            iteration_state: Reference to the harness's iteration dictionary
            get_tool_output: Callback to get last run() output (@)
        """
        self.workspace = Path(workspace_path).resolve()
        self.iteration = iteration_state
        self.get_tool_output = get_tool_output
    
    def loop(self, items: str | List[str]) -> str:
        """
        Start iteration over files, tasks, or any list.
        
        Args:
            items: 
                - "@" - Use last tool output
                - "@{run}" - Use last run() output specifically
                - Glob pattern: "*.py" or "auth/**/*.py"
                - Newline string: "file1\\nfile2\\nfile3" (auto-split)
                - List: ["file1", "file2", "task1"]
                
        Returns:
            File/item list preview with first item
            
        Examples:
            >>> loop("*.py")
            'Starting iteration of 8 files...'
            
            >>> loop(["Review code", "Fix bugs", "Test"])
            'Starting iteration of 3 items...'
            
            >>> run("git diff --name-only")
            >>> loop("@")
            'Starting iteration of 3 files...'
        """
        # Resolve references to previous tool outputs
        if isinstance(items, str):
            items = self._resolve_reference(items)
        
        # Convert to list
        items_list = self._parse_items(items)
        
        if not items_list:
            return "[ERROR] No items to iterate. Provide a valid pattern, list, or reference."
        
        # Start iteration
        return self._start_iteration(items_list, source=str(items)[:50])
    
    def _resolve_reference(self, items: str) -> str:
        """Resolve @ references to previous tool outputs."""
        if items == "@":
            # Get last run() output
            if self.get_tool_output:
                result = self.get_tool_output("@")
                if result:
                    return result
            return "[ERROR:NO_PREV]"  # Will be caught later
        
        return items  # Not a reference
    
    def _parse_items(self, items: str | List[str]) -> List[str]:
        """Parse items into a list, handling different input formats."""
        if isinstance(items, list):
            # Already a list - filter empty strings
            return [str(item).strip() for item in items if str(item).strip()]
        
        # Check for error markers from reference resolution
        if items.startswith("[ERROR:"):
            if "NO_PREV" in items:
                raise ValueError("No previous tool output to reference with '@'")
            elif "NO_RUN" in items:
                raise ValueError("No previous run() output found")
            else:
                raise ValueError(items)
        
        # String input - check if newline-separated
        if '\n' in items:
            # Multi-line string - split and filter
            lines = [line.strip() for line in items.split('\n') if line.strip()]
            return lines
        
        # Single line - check if it's a glob pattern
        if any(char in items for char in ['*', '?', '[', ']']):
            # Glob pattern - expand
            return self._expand_glob(items)
        
        # Single item
        return [items] if items.strip() else []
    
    def _expand_glob(self, pattern: str) -> List[str]:
        """Expand glob pattern to file list."""
        # Resolve pattern relative to workspace
        if Path(pattern).is_absolute():
            search_pattern = pattern
        else:
            search_pattern = str(self.workspace / pattern)
        
        # Find matching files
        matched_files = sorted(glob.glob(search_pattern, recursive=True))
        
        # Filter out directories
        files = [f for f in matched_files if Path(f).is_file()]
        
        # Convert to relative paths
        try:
            relative_files = [
                str(Path(f).relative_to(self.workspace))
                for f in files
            ]
        except ValueError:
            # Files outside workspace
            relative_files = files
        
        return relative_files
    
    def _start_iteration(self, items: List[str], source: str = "items") -> str:
        """
        Internal helper to start iteration with a list of items.
        
        Args:
            items: List of items to iterate
            source: Description of where items came from (for display)
            
        Returns:
            Formatted start message
        """
        # Warn on large scopes
        if len(items) > 100:
            preview = '\n'.join(f" {i+1}. {item}" for i, item in enumerate(items[:10]))
            return f"""WARNING: {len(items)} items to iterate. This is a lot!

Preview (first 10):
{preview}
...and {len(items) - 10} more items.

Consider narrowing the scope, or call loop_next() to proceed anyway."""
        
        # Initialize iteration state
        self.iteration.clear()
        self.iteration.update({
            "active": True,
            "source": source,
            "items": items,
            "current_index": 0,  # Start at first item
            "total": len(items),
            "done_called": False  # Track if loop_itr_done was called
        })
        
        # Format item list
        if len(items) <= 20:
            # Show all items
            item_list = '\n'.join(f" {i+1}. {item}" for i, item in enumerate(items))
        else:
            # Show first 10 and last 5
            first_10 = '\n'.join(f" {i+1}. {item}" for i, item in enumerate(items[:10]))
            last_5 = '\n'.join(f" {i+1}. {item}" for i, item in enumerate(items[-5:], start=len(items)-4))
            item_list = f"{first_10}\n ...\n{last_5}"
        
        # Auto-start with first item
        first_item = items[0]
        
        return f"""Starting iteration of {len(items)} items:
{item_list}

First item [01/{len(items):02d}]: {first_item}"""
    
    def loop_next(self) -> str:
        """
        Get next item in the iteration.
        
        Returns:
            Next item with progress indicator, or completion message
            
        Example:
            >>> loop_next()
            'pico_chat/ui/app.py [02/08]'
            
            [After processing all items:]
            >>> loop_next()
            'Iteration complete! Processed 8/8 items.'
        """
        if not self.iteration.get("active"):
            return "[ERROR] No active iteration. Call loop() first to start."
        
        # Reset done_called flag when advancing
        self.iteration["done_called"] = False
        
        # Advance to next item
        self.iteration["current_index"] += 1
        current = self.iteration["current_index"]
        total = self.iteration["total"]
        
        # Check if iteration complete
        if current >= total:
            # Clear iteration state
            items_processed = self.iteration["items"]
            self.iteration.clear()
            
            return f"""Iteration complete! Processed {total}/{total} items.

Review your conversation history for findings from each item."""
        
        # Return current item with progress for UI display
        current_item = self.iteration["items"][current]
        
        # Format: item [progress]
        return f"{current_item} [{current+1:02d}/{total:02d}]"
    
    def loop_itr_done(self) -> str:
        """
        Trigger reflection checkpoint on current item (optional).
        
        Returns:
            Reflection prompt asking if current item is complete
            
        Example:
            >>> loop_itr_done()
            'Current item: auth.py
             
             Reflect: Did you complete work on this item?
             - Did you do everything needed?
             - Are you confident in the quality?
             
             ✓ If yes → Call loop_next() to advance
             ✗ If no/unsure → Continue working or ask user'
        """
        if not self.iteration.get("active"):
            return "[ERROR] No active iteration."
        
        current = self.iteration.get("current_index", 0)
        total = self.iteration.get("total", 0)
        current_item = self.iteration["items"][current]
        
        # Mark that done was called
        self.iteration["done_called"] = True
        
        return f"""Current item: {current_item}
Progress: {current+1}/{total}

Reflect: Did you complete work on this item?
- Did you do everything needed?
- Are you confident in the quality?
- Any doubts or incomplete work?

✓ If yes → Call loop_next() to advance
✗ If no/unsure → Continue working or ask user"""
    
    def loop_abort(self) -> str:
        """
        Abort the current iteration.
        
        Returns:
            Confirmation message with progress at abort point
            
        Example:
            >>> loop_abort()
            'Iteration aborted. Processed 3/8 items.'
        """
        if not self.iteration.get("active"):
            return "[ERROR] No active iteration to abort."
        
        current = self.iteration.get("current_index", 0)
        total = self.iteration.get("total", 0)
        
        # Clear iteration state
        self.iteration.clear()
        
        return f"Iteration aborted. Processed {current}/{total} items."
