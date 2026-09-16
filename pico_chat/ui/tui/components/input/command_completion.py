"""Command completion system for InputComponent."""

from typing import List, Optional

from .completion import Completer


class CommandCompletion(Completer):
    """Manages /command completion with auto-show menu."""

    def __init__(self, menu, commands: List[str]):
        super().__init__(menu)
        self.commands = commands

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
        current_word = self.get_current_command_word(text, cursor_pos)
        self._refresh_suppression(current_word)

        if self._is_suppressed(current_word):
            self.hide()
            return

        if not self.should_trigger(text):
            self.hide()
            return

        search_term = text.lstrip()[1:]  # Remove leading '/'

        # Filter out exact matches (command is already complete)
        if search_term.lower() in [cmd.lower() for cmd in self.commands]:
            self.hide()
            return

        self._show(self.commands, search_term, display_prefix="/")

    def accept_selection(self, current_text: str) -> Optional[str]:
        """Accept current selection, return completed text."""
        selected = self.menu.get_selected()
        if selected:
            return f"/{selected}"
        return None

    def cancel(self, text: str, cursor_pos: int):
        """User pressed ESC - suppress menu for current word."""
        self._suppress(self.get_current_command_word(text, cursor_pos))


__all__ = ["CommandCompletion"]
