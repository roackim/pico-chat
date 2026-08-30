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

        If ``current_word`` points into a directory (e.g. ``src/`` or a partial
        ``src/fo``), list that directory's immediate children as full relative
        paths (e.g. ``src/a.py``, ``src/sub/``) so the user sees the aggregated
        path. Otherwise return the top-level listing.
        """
        items = self.get_items()
        if not current_word:
            return items
        # Determine the directory prefix the user is drilling into. For
        # "src/" it's "src/"; for a partial "src/fo" it's "src/".
        if current_word.endswith('/'):
            prefix = current_word
        elif '/' in current_word:
            prefix = current_word.rsplit('/', 1)[0] + '/'
        else:
            # No slash: still at the top level.
            return items
        # Match items that live under this directory prefix.
        children = [it for it in items if it.startswith(prefix) and it != prefix]
        if children:
            # Keep only immediate children (no further "/" beyond a trailing
            # dir slash), so we show one level at a time — but keep the full
            # relative path so the user sees the aggregated path.
            immediate = [it for it in children if '/' not in it[len(prefix):].rstrip('/')]
            # Offer a ".." entry to navigate back up a level. It goes LAST so
            # it is never the default highlight — the user must explicitly
            # select it.
            return immediate + ["../"]
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
        
        # When drilling into a directory, the fuzzy search term is the text after
        # the last slash. For "src/" that's empty (show all children); for a
        # partial "src/fo" it's "fo" (filter within the directory).
        if '/' in current_word:
            search_term = current_word.rsplit('/', 1)[-1]
        else:
            search_term = current_word
        
        # Keep the "../" navigation entry always visible when drilling, even
        # while the user types a partial name that would fuzzy-filter it out.
        # It stays at the END so it is never the default highlight.
        has_parent = "../" in items
        if has_parent:
            rest = [it for it in items if it != "../"]
        else:
            rest = items
        
        # Update menu with fuzzy filtering. No display prefix: the items are
        # already relative paths (or bare names when drilling), so showing
        # "./" would be redundant.
        self.menu.update(rest, search_term, display_prefix="")
        if has_parent:
            self.menu.items = self.menu.items + ["../"]
            self.menu.is_visible = len(self.menu.items) > 0
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
        
        # The ".." entry navigates up one level: drop the last path segment.
        if selected == "../":
            if prefix:
                stripped = prefix.rstrip('/')
                if '/' in stripped:
                    parent = stripped.rsplit('/', 1)[0] + '/'
                else:
                    # Single-level dir (e.g. "src/") — going up returns to root.
                    parent = ""
                new_text = text[:trigger_pos] + self.trigger + parent + text[cursor_pos:]
                new_cursor_pos = trigger_pos + self.trigger_len + len(parent)
            else:
                new_text = text[:trigger_pos] + self.trigger + text[cursor_pos:]
                new_cursor_pos = trigger_pos + self.trigger_len
            return (new_text, new_cursor_pos)

        # _resolve_items returns full relative paths (e.g. "notes/doc.md"), so
        # we must NOT re-prepend the directory prefix — that would double it
        # ("./notes/notes/doc.md"). Just insert the selected path as-is.
        new_text = text[:trigger_pos] + self.trigger + selected + text[cursor_pos:]
        new_cursor_pos = trigger_pos + self.trigger_len + len(selected)

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
