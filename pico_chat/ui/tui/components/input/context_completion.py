"""Context (@file) completion system for InputComponent."""

from typing import List, Optional, Callable
from pico_chat.ui.tui.components.menu import SelectionMenu


class ContextCompletion:
    """Manages @file/folder completion with auto-show menu."""
    
    def __init__(self, menu: SelectionMenu, get_items_callback: Callable[[], List[str]]):
        self.menu = menu
        self.get_items = get_items_callback
        self.is_active = False
        self.suppressed_word: Optional[str] = None  # Word that user ESC'd
    
    def find_trigger_position(self, text: str, cursor_pos: int) -> Optional[int]:
        """Find the last @ before cursor position."""
        # Only look up to cursor position
        text_before_cursor = text[:cursor_pos]
        last_at = text_before_cursor.rfind('@')
        
        if last_at == -1:
            return None
        
        # Check if there's a space after the @ (means context is complete)
        text_after_at = text[last_at + 1:cursor_pos]
        if ' ' in text_after_at:
            return None
        
        return last_at
    
    def get_current_context_word(self, text: str, cursor_pos: int) -> Optional[str]:
        """Extract the word after @ at cursor position (without @)."""
        trigger_pos = self.find_trigger_position(text, cursor_pos)
        if trigger_pos is None:
            return None
        
        # Extract text from @ to cursor
        text_after_at = text[trigger_pos + 1:cursor_pos]
        
        # Word ends at space or cursor
        if ' ' in text_after_at:
            return None
        
        return text_after_at
    
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
        
        # Get available items
        items = self.get_items()
        if not items:
            self.hide()
            return
        
        # Filter out exact matches (path is already complete and valid)
        if current_word in items:
            self.hide()
            return
        
        # Update menu with fuzzy filtering
        self.menu.update(items, current_word, display_prefix="@")
        self.is_active = self.menu.is_visible
    
    def accept_selection(self, text: str, cursor_pos: int) -> Optional[tuple[str, int]]:
        """Accept current selection, return (new_text, new_cursor_pos)."""
        selected = self.menu.get_selected()
        if not selected:
            return None
        
        trigger_pos = self.find_trigger_position(text, cursor_pos)
        if trigger_pos is None:
            return None
        
        # Replace from @ to cursor with selected item
        new_text = text[:trigger_pos] + "@" + selected + text[cursor_pos:]
        new_cursor_pos = trigger_pos + 1 + len(selected)
        
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
