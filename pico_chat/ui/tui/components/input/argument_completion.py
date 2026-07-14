"""Generic argument completion for any command that has Param definitions.

Replaces the specialised ServerCompletion and PathCompletion modules with a
single data-driven completer that reads completion candidates from the
Command.params schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from pico_chat.ui.commands import Command

from pico_chat.ui.tui.components.menu import SelectionMenu


class ArgumentCompletion:
    """Provides fuzzy autocomplete for command arguments based on Param definitions.

    Works for both top-level commands and nested subcommands.  The caller
    (InputComponent) is responsible for only calling update() when a deeper
    completer (CommandCompletion, SubcommandCompletion) is not active.
    """

    def __init__(self, menu: SelectionMenu, commands: Dict[str, Command]):
        self.menu = menu
        self.commands = commands  # The COMMANDS registry
        self.is_active = False
        self.suppressed_word: Optional[str] = None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _resolve(self, text: str) -> Optional[tuple[Command, int, str]]:
        """Parse the input text and resolve to (command, arg_index, current_arg_text).

        Returns None if no argument completion is applicable.
        """
        clean = text.lstrip()
        if not clean.startswith('/'):
            return None

        parts = clean.split()
        if not parts:
            return None

        cmd_name = parts[0][1:]  # strip leading '/'
        if cmd_name not in self.commands:
            return None

        root_cmd = self.commands[cmd_name]

        # Walk subcommands to find the deepest resolved command
        cmd, offset = root_cmd.resolve_command(parts[1:])

        # The arg_index is relative to the resolved command's own params
        # parts = ["/cmd", "sub1", "sub2", "arg0", "arg1", ...]
        # offset counts how many subcommands were consumed from parts[1:]
        # So the args start at parts[1 + offset]
        args_start = 1 + offset  # index in `parts` where cmd's own args begin
        rest = clean.split(' ', args_start)
        # rest has args_start+1 elements; the last element is everything after the consumed parts
        if len(rest) <= args_start:
            # Nothing typed for args yet — but check if there's a trailing space
            if clean.endswith(' '):
                arg_index = 0
                current_text = ''
            else:
                return None  # still typing subcommand
        else:
            after = rest[args_start]
            # Count how many complete args precede the current one
            after_parts = after.split()
            # Determine if user is between args (trailing space) or on one
            if after.endswith(' ') or not after_parts:
                # Between args or empty — completing the NEXT arg
                arg_index = len(after_parts)
                current_text = ''
            else:
                # On an arg — completing the CURRENT arg
                arg_index = len(after_parts) - 1
                current_text = after_parts[-1]

        return cmd, arg_index, current_text

    # ------------------------------------------------------------------
    # Completion interface
    # ------------------------------------------------------------------

    def update(self, text: str, cursor_pos: int):
        """Auto-update menu based on current text and cursor position."""
        result = self._resolve(text)
        if not result:
            self.hide()
            return

        cmd, arg_index, current_text = result

        # Get completions from the resolved command
        items = cmd.get_completions(arg_index)
        if not items:
            self.hide()
            return

        # Suppression
        if self.suppressed_word is not None:
            if current_text.startswith(self.suppressed_word):
                self.hide()
                return
            self.suppressed_word = None

        # Hide if exact match already typed
        if current_text in items:
            self.hide()
            return

        # Fuzzy filter and show
        self.menu.update(items, current_text, display_prefix="")
        self.is_active = self.menu.is_visible

    def accept_selection(self, text: str) -> Optional[str]:
        """Accept current selection, return completed text."""
        selected = self.menu.get_selected()
        if not selected:
            return None

        result = self._resolve(text)
        if not result:
            return None

        cmd, arg_index, current_text = result
        clean = text.lstrip()
        parts = clean.split()

        # Rebuild the command prefix (everything up to and including subcommands)
        cmd_name = parts[0][1:]
        root_cmd = self.commands[cmd_name]
        _, offset = root_cmd.resolve_command(parts[1:])

        # Prefix = "/cmd sub1 sub2 ..."
        prefix_parts = parts[:1 + offset]
        prefix = ' '.join(prefix_parts)

        # Rebuild the args portion, replacing the current arg with the selection
        args_start = 1 + offset
        after = clean.split(' ', args_start)
        if len(after) <= args_start:
            existing_args: List[str] = []
        else:
            # Split existing args but drop the last (incomplete) one
            existing_args = after[args_start].split()
            if not clean.endswith(' '):
                existing_args = existing_args[:-1]  # drop the partial arg

        # Build final text
        all_args = existing_args + [selected]
        # Add trailing space if selection looks complete (for further args)
        return f"{prefix} {' '.join(all_args)} "

    def hide(self):
        """Deactivate and hide menu."""
        self.menu.hide()
        self.is_active = False

    def cancel(self, text: str, cursor_pos: int):
        """User pressed ESC — suppress menu for current word."""
        result = self._resolve(text)
        if result:
            _, _, current_text = result
            if current_text:
                self.suppressed_word = current_text
        self.hide()

    def navigate_up(self):
        if self.is_active:
            self.menu.action_up()

    def navigate_down(self):
        if self.is_active:
            self.menu.action_down()
