"""Shared base for the input completion strategies.

The input component drives four completion strategies — commands,
subcommands, command arguments, and ``@`` context paths. Each has its own
trigger and candidate logic, but they all share the same lifecycle:

    update(text, cursor_pos)   -> refresh the menu
    accept_selection(...)      -> commit the highlighted candidate
    cancel(text, cursor_pos)   -> ESC: suppress the current word
    hide() / navigate_up() / navigate_down()

This module owns that shared lifecycle so the strategies only implement what
actually differs. It also centralises the "suppressed word" rule: after ESC,
the menu stays hidden while the user keeps typing the same prefix, and
reappears once the word changes.
"""

from __future__ import annotations

from typing import List, Optional

from pico_chat.ui.tui.components.menu import SelectionMenu


class Completer:
    """Base class for a menu-backed completion strategy."""

    def __init__(self, menu: SelectionMenu):
        self.menu = menu
        self.is_active = False
        # The word the user dismissed with ESC; the menu stays hidden while
        # the current word still starts with it.
        self.suppressed_word: Optional[str] = None

    # -- suppression ---------------------------------------------------

    def _refresh_suppression(self, current_word: Optional[str]) -> None:
        """Forget the suppressed word once the user has moved on."""
        if not self.suppressed_word:
            return
        if not current_word or not current_word.startswith(self.suppressed_word):
            self.suppressed_word = None

    def _is_suppressed(self, current_word: Optional[str]) -> bool:
        """True when the menu must stay hidden for the current word."""
        return bool(
            current_word
            and self.suppressed_word
            and current_word.startswith(self.suppressed_word)
        )

    def _suppress(self, current_word: Optional[str]) -> None:
        """Record the current word as dismissed and hide the menu."""
        if current_word:
            self.suppressed_word = current_word
        self.hide()

    # -- menu lifecycle ------------------------------------------------

    def hide(self) -> None:
        """Deactivate and hide the menu."""
        self.menu.hide()
        self.is_active = False

    def navigate_up(self) -> None:
        if self.is_active:
            self.menu.action_up()

    def navigate_down(self) -> None:
        if self.is_active:
            self.menu.action_down()

    def _show(self, items: List[str], search_term: str,
              display_prefix: str = "") -> None:
        """Push candidates to the menu and sync the active flag."""
        self.menu.update(items, search_term, display_prefix=display_prefix)
        self.is_active = self.menu.is_visible

    # -- interface -----------------------------------------------------

    def update(self, text: str, cursor_pos: int) -> None:
        raise NotImplementedError

    def accept_selection(self, text: str, cursor_pos: int):
        raise NotImplementedError

    def cancel(self, text: str, cursor_pos: int) -> None:
        raise NotImplementedError


__all__ = ["Completer"]
