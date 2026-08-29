"""Context completion system for InputComponent.

Provides fuzzy file/folder completion with a configurable trigger prefix.
"""

from typing import List, Optional, Callable
from pico_chat.ui.tui.components.menu import SelectionMenu


class ContextCompletion:
    """Manages file/folder completion with auto-show menu.
    
    Args:
        menu: SelectionMenu instance for displaying completions
        get_items_callback: Callable returning list of available items
        trigger: Trigger prefix string (default: "./")
    """
    
    def __init__(self, menu: SelectionMenu, get_items_callback: Callable[[], List[str]], trigger: str = "./"):
        self.menu = menu
        self.get_items = get_items_callback
        self.trigger = trigger
        self.trigger_len = len(trigger)
        self.is_active = False
        self.suppressed_word: Optional[str] = None  # Word that user ESC'd
    
    def find_trigger_position(self, text: str, cursor_pos: int) -> Optional[int]:
        """Find the last trigger before cursor position."""
        # Only look up to cursor position
        text_before_cursor = text[:cursor_pos]
        
        # Look for trigger pattern
        last_trigger = text_before_cursor.rfind(self.trigger)
        
        if last_trigger == -1:
            return None
        
        # Check if there's a space after the trigger (means context is complete)
        text_after_trigger = text[last_trigger + self.trigger_len:cursor_pos]
        if ' ' in text_after_trigger:
            return None
        
        return last_trigger
    
    def get_current_context_word(self, text: str, cursor_pos: int) -> Optional[str]:
        """Extract the word after trigger at cursor position (without trigger)."""
        trigger_pos = self.find_trigger_position(text, cursor_pos)
        if trigger_pos is None:
            return None
        
        # Extract text from trigger to cursor
        text_after_trigger = text[trigger_pos + self.trigger_len:cursor_pos]
        
        # Word ends at space or cursor
        if ' ' in text_after_trigger:
            return None
        
        return text_after_trigger
    
    def _resolve_items(self, current_word: str) -> List[str]:
        """Resolve the file list for the current word.

        If ``current_word`` ends with ``/`` and points at an existing
        directory, list that directory's contents (relative to the workspace
        root) so the user can build a path folder-by-folder. Otherwise return
        the top-level listing.
        """
        items = self.get_items()
        if not current_word:
            return items
        # A trailing slash means the user is drilling into a directory.
        if current_word.endswith('/'):
            prefix = current_word
            # Match items that live under this directory prefix.
            children = [it for it in items if it.startswith(prefix) and it != prefix]
            if children:
                # Strip the prefix and keep only immediate children (no
                # further "/" beyond a trailing dir slash), so we show one
                # level at a time.
                stripped = [it[len(prefix):] for it in children]
                return [it for it in stripped if '/' not in it.rstrip('/')]
        return items
    
    def update(self, text: str, cursor_pos: int):
        """Auto-update menu based on current text and cursor position."""
        # Get current word at cursor
        current_word = self.get_current_context_word(text, cursor_pos)
        
        # Clear suppression memory if we've moved to a different word
        if self.suppressed_word and current_word:
            # Only clear if current word doesn't start with suppressed prefix
            if not current_word.startswith(self.suppressed_word):
                self.suppressed_word = None
        elif self.suppressed_word and not current_word:
            # Moved away from context word entirely
            self.suppressed_word = None
        
        # Don't show menu if current word starts with suppressed prefix
        if current_word is not None and self.suppressed_word and current_word.startswith(self.suppressed_word):
            self.hide()
            return
        
        # No trigger found
        if current_word is None:
            self.hide()
            return
        
        # Get available items (resolved for subdirectory drilling)
        items = self._resolve_items(current_word)
        if not items:
            self.hide()
            return
        
        # Filter out exact matches (path is already complete and valid)
        if current_word in items:
            self.hide()
            return
        
        # When drilling into a directory (current_word ends with "/"), the fuzzy
        # search term is the text after the last slash — which is empty, so
        # all immediate children are shown. Otherwise use the whole word.
        if current_word.endswith('/'):
            search_term = ""
        else:
            search_term = current_word
        
        # Update menu with fuzzy filtering
        self.menu.update(items, search_term, display_prefix=self.trigger)
        self.is_active = self.menu.is_visible
    
    def accept_selection(self, text: str, cursor_pos: int) -> Optional[tuple[str, int]]:
        """Accept current selection, return (new_text, new_cursor_pos)."""
        selected = self.menu.get_selected()
        if not selected:
            return None
        
        trigger_pos = self.find_trigger_position(text, cursor_pos)
        if trigger_pos is None:
            return None
        
        # Preserve any directory prefix already typed (e.g. "./src/").
        current_word = self.get_current_context_word(text, cursor_pos) or ""
        prefix = current_word if current_word.endswith('/') else ""
        
        # Replace from trigger to cursor with selected item
        new_text = text[:trigger_pos] + self.trigger + prefix + selected + text[cursor_pos:]
        new_cursor_pos = trigger_pos + self.trigger_len + len(prefix) + len(selected)
        
        return (new_text, new_cursor_pos)
    
    def hide(self):
        """Deactivate and hide menu."""
        self.menu.hide()
        self.is_active = False
    
    def cancel(self, text: str, cursor_pos: int):
        """User pressed ESC - suppress menu for current word prefix."""
        current_word = self.get_current_context_word(text, cursor_pos)
        if current_word is not None:
            self.suppressed_word = current_word
        self.hide()
    
    def navigate_up(self):
        """Move selection up in menu."""
        if self.is_active:
            self.menu.action_up()
    
    def navigate_down(self):
        """Move selection down in menu."""
        if self.is_active:
            self.menu.action_down()
