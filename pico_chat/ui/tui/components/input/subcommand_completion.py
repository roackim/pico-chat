"""Subcommand completion system for InputComponent."""

from typing import List, Optional, Callable
from pico_chat.ui.tui.components.menu import SelectionMenu


class SubcommandCompletion:
    """Manages /command subcommand completion with auto-show menu."""
    
    def __init__(self, menu: SelectionMenu, get_subcommands_callback: Callable[[str], List[str]]):
        self.menu = menu
        self.get_subcommands = get_subcommands_callback
        self.is_active = False
        self.suppressed_word: Optional[str] = None  # Subcommand word that user ESC'd
        self.current_parent_command: Optional[str] = None  # Track which command we're completing for
    
    def parse_command_line(self, text: str) -> Optional[tuple[str, str]]:
        """Parse /command subcommand format. Returns (command, subcommand_text) or None."""
        clean = text.lstrip()
        
        # Must start with / and have a space
        if not clean.startswith('/') or ' ' not in clean:
            return None
        
        # Split into command and rest
        parts = clean.split(' ', 1)
        command = parts[0][1:]  # Remove leading /
        subcommand_text = parts[1] if len(parts) > 1 else ""
        
        return (command, subcommand_text)
    
    def should_trigger(self, text: str) -> bool:
        """Check if subcommand completion should be active."""
        parsed = self.parse_command_line(text)
        if not parsed:
            return False
        
        command, subcommand_text = parsed
        
        # Check if this command has subcommands
        subcommands = self.get_subcommands(command)
        return len(subcommands) > 0
    
    def update(self, text: str, cursor_pos: int):
        """Auto-update menu based on current text and cursor position."""
        parsed = self.parse_command_line(text)
        
        if not parsed:
            self.hide()
            self.current_parent_command = None
            return
        
        command, subcommand_text = parsed
        
        # Get available subcommands for this command
        subcommands = self.get_subcommands(command)
        if not subcommands:
            self.hide()
            self.current_parent_command = None
            return
        
        # Track which parent command we're completing for
        # If parent changed, clear suppression memory
        if self.current_parent_command != command:
            self.suppressed_word = None
            self.current_parent_command = command
        
        # Clear suppression memory if subcommand text changes
        if self.suppressed_word and subcommand_text:
            # Only clear if current text doesn't start with suppressed prefix
            if not subcommand_text.startswith(self.suppressed_word):
                self.suppressed_word = None
        elif self.suppressed_word and not subcommand_text:
            # Moved away from subcommand entirely (back to just command)
            self.suppressed_word = None
        
        # Don't show menu if current word starts with suppressed prefix
        if subcommand_text and self.suppressed_word and subcommand_text.startswith(self.suppressed_word):
            self.hide()
            return
        
        # Strip trailing whitespace for exact match check
        subcommand_trimmed = subcommand_text.rstrip()
        
        # Filter out exact matches (subcommand is already complete and valid)
        # Also hide if there's trailing space after a valid subcommand
        if subcommand_trimmed in subcommands:
            self.hide()
            return
        
        # Check if user has completed subcommand and is typing arguments
        # (e.g., "fps 5" where "fps" is a valid subcommand)
        first_word = subcommand_text.split()[0] if subcommand_text.split() else ""
        if first_word in subcommands and ' ' in subcommand_text:
            # User has typed a valid subcommand followed by space and more text (arguments)
            self.hide()
            return
        
        # Update menu with fuzzy filtering (no prefix, just subcommand names)
        self.menu.update(subcommands, subcommand_trimmed, display_prefix="")
        self.is_active = self.menu.is_visible
    
    def accept_selection(self, text: str) -> Optional[str]:
        """Accept current selection, return completed text."""
        selected = self.menu.get_selected()
        if not selected:
            return None
        
        parsed = self.parse_command_line(text)
        if not parsed:
            return None
        
        command, _ = parsed
        
        # Return full command with selected subcommand
        return f"/{command} {selected}"
    
    def hide(self):
        """Deactivate and hide menu."""
        self.menu.hide()
        self.is_active = False
    
    def cancel(self, text: str, cursor_pos: int):
        """User pressed ESC - suppress menu for current subcommand prefix."""
        parsed = self.parse_command_line(text)
        if parsed:
            _, subcommand_text = parsed
            if subcommand_text:
                self.suppressed_word = subcommand_text
        self.hide()
    
    def navigate_up(self):
        """Move selection up in menu."""
        if self.is_active:
            self.menu.action_up()
    
    def navigate_down(self):
        """Move selection down in menu."""
        if self.is_active:
            self.menu.action_down()
