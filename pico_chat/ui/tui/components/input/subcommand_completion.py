"""Subcommand completion system for InputComponent."""

from typing import Callable, List, Optional

from .completion import Completer


class SubcommandCompletion(Completer):
    """Manages /command subcommand completion with auto-show menu."""

    def __init__(self, menu, get_subcommands_callback: Callable[[str], List[str]]):
        super().__init__(menu)
        self.get_subcommands = get_subcommands_callback
        # Track which command we're completing for, so suppression memory is
        # cleared when the parent command changes.
        self.current_parent_command: Optional[str] = None

    def parse_command_line(self, text: str) -> Optional[tuple[str, str]]:
        """Parse /command subcommand format. Returns (command, subcommand_text) or None."""
        clean = text.lstrip()

        # Must start with / and have a space
        if not clean.startswith('/') or ' ' not in clean:
            return None

        parts = clean.split(' ', 1)
        command = parts[0][1:]  # Remove leading /
        subcommand_text = parts[1] if len(parts) > 1 else ""

        return (command, subcommand_text)

    def should_trigger(self, text: str) -> bool:
        """Check if subcommand completion should be active."""
        parsed = self.parse_command_line(text)
        if not parsed:
            return False

        command, _ = parsed
        return len(self.get_subcommands(command)) > 0

    def update(self, text: str, cursor_pos: int):
        """Auto-update menu based on current text and cursor position."""
        parsed = self.parse_command_line(text)

        if not parsed:
            self.hide()
            self.current_parent_command = None
            return

        command, subcommand_text = parsed
        subcommands = self.get_subcommands(command)
        if not subcommands:
            self.hide()
            self.current_parent_command = None
            return

        # If the parent command changed, forget the suppressed word.
        if self.current_parent_command != command:
            self.suppressed_word = None
            self.current_parent_command = command

        self._refresh_suppression(subcommand_text)
        if self._is_suppressed(subcommand_text):
            self.hide()
            return

        subcommand_trimmed = subcommand_text.rstrip()

        # Hide when the subcommand is already complete and valid.
        if subcommand_trimmed in subcommands:
            self.hide()
            return

        # Hide once the user is typing arguments after a valid subcommand
        # (e.g. "fps 5" where "fps" is a valid subcommand).
        first_word = subcommand_text.split()[0] if subcommand_text.split() else ""
        if first_word in subcommands and ' ' in subcommand_text:
            self.hide()
            return

        self._show(subcommands, subcommand_trimmed)

    def accept_selection(self, text: str) -> Optional[str]:
        """Accept current selection, return completed text."""
        selected = self.menu.get_selected()
        if not selected:
            return None

        parsed = self.parse_command_line(text)
        if not parsed:
            return None

        command, _ = parsed
        return f"/{command} {selected}"

    def cancel(self, text: str, cursor_pos: int):
        """User pressed ESC - suppress menu for current subcommand prefix."""
        parsed = self.parse_command_line(text)
        if parsed:
            _, subcommand_text = parsed
            self._suppress(subcommand_text)
        else:
            self.hide()


__all__ = ["SubcommandCompletion"]
