"""Command completion system for InputComponent."""

from typing import List, Optional
from pico_chat.ui.tui.components.menu import SelectionMenu


class CommandCompletion:
    """Manages /command completion with auto-show menu."""
    
    def __init__(self, menu: SelectionMenu, commands: List[str]):
        self.menu = menu
        self.commands = commands
        self.is_active = False
        self.suppressed_word: Optional[str] = None  # Word that user ESC'd
    
    def should_trigger(self, text: str) -> bool:
        """Check if command completion should be active."""
        clean = text.lstrip()
        # Trigger: starts with '/', no space (not a complete command)
        return clean.startswith('/') and ' ' not in clean
    
    def get_current_command_word(self, text: str, cursor_pos: int) -> Optional[str]:
        """Extract the /command word at cursor position (without /)."""
        clean = text.lstrip()
        
        # Must start with /
        if not clean.startswith('/'):
            return None
        
        # Find word boundaries (no space allowed in commands)
        if ' ' in clean:
            word_part = clean.split(' ', 1)[0]
        else:
            word_part = clean
        
        # Return without the leading /
        return word_part[1:] if len(word_part) > 1 else ""
    
    def update(self, text: str, cursor_pos: int):
        """Auto-update menu based on current text and cursor position."""
        # Get current word at cursor
        current_word = self.get_current_command_word(text, cursor_pos)
        
        # Clear suppression memory if we've moved to a different word (not starting with suppressed prefix)
        if self.suppressed_word and current_word:
            # Only clear if current word doesn't start with suppressed prefix
            if not current_word.startswith(self.suppressed_word):
                self.suppressed_word = None
        elif self.suppressed_word and not current_word:
            # Moved away from command word entirely
            self.suppressed_word = None
        
        # Don't show menu if current word starts with suppressed prefix
        if current_word and self.suppressed_word and current_word.startswith(self.suppressed_word):
            self.hide()
            return
        
        if not self.should_trigger(text):
            self.hide()
            return
        
        clean = text.lstrip()
        search_term = clean[1:]  # Remove leading '/'
        
        # Filter out exact matches (command is already complete)
        if search_term.lower() in [cmd.lower() for cmd in self.commands]:
            self.hide()
            return
        
        # Update menu (it will auto-show if items match)
        self.menu.update(self.commands, search_term, display_prefix="/")
        self.is_active = self.menu.is_visible
    
    def accept_selection(self, current_text: str) -> Optional[str]:
        """Accept current selection, return completed text."""
        selected = self.menu.get_selected()
        if selected:
            return f"/{selected}"
        return None
    
    def hide(self):
        """Deactivate and hide menu."""
        self.menu.hide()
        self.is_active = False
    
    def cancel(self, text: str, cursor_pos: int):
        """User pressed ESC - suppress menu for current word."""
        current_word = self.get_current_command_word(text, cursor_pos)
        if current_word:
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
