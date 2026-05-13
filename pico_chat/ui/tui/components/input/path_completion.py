"""Filesystem path completion for /cd and similar commands."""

import os
from typing import Callable, List, Optional
from pico_chat.ui.tui.components.menu import SelectionMenu


class PathCompletion:
    """Manages filesystem path completion for commands like /cd.

    Triggers on: /<command> <partial_path>
    Lists directories from the filesystem based on what the user has typed.
    Preserves the original prefix (e.g. ~/...) in the completed text.
    """

    def __init__(
        self,
        menu: SelectionMenu,
        path_commands: List[str],
        get_workspace: Callable[[], str],
    ):
        self.menu = menu
        self.path_commands = path_commands  # e.g. ["cd"]
        self.get_workspace = get_workspace
        self.is_active = False
        self.suppressed_prefix: Optional[str] = None
        self._last_base_prefix: str = ""  # cached for accept_selection

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self, text: str) -> Optional[tuple[str, str]]:
        """Return (command, path_text) or None."""
        clean = text.lstrip()
        if not clean.startswith('/') or ' ' not in clean:
            return None
        parts = clean.split(' ', 1)
        cmd = parts[0][1:]
        if cmd not in self.path_commands:
            return None
        return (cmd, parts[1])

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------

    def _get_completions(self, path_text: str) -> tuple[List[str], str, str]:
        """Return (entry_names, base_prefix, partial).

        base_prefix  — the part of path_text before the last '/' (kept verbatim
                       so ~/... prefixes are preserved in the accepted text).
        partial      — the filename fragment being completed.
        entry_names  — list of directory names (with trailing '/') to show.
        """
        # Split original text into prefix + partial (verbatim, no expansion yet)
        if not path_text or path_text.endswith('/'):
            base_prefix = path_text
            partial = ""
        else:
            last_slash = path_text.rfind('/')
            if last_slash == -1:
                base_prefix = ""
                partial = path_text
            else:
                base_prefix = path_text[: last_slash + 1]
                partial = path_text[last_slash + 1 :]

        # Resolve the directory to list
        workspace = self.get_workspace()
        if base_prefix:
            dir_to_list = os.path.expanduser(base_prefix)
            if not os.path.isabs(dir_to_list):
                dir_to_list = os.path.join(workspace, dir_to_list)
        else:
            dir_to_list = workspace

        # List directory contents (directories only, no dot-entries)
        try:
            entries: List[str] = []
            with os.scandir(dir_to_list) as it:
                for entry in sorted(it, key=lambda e: e.name.lower()):
                    if entry.name.startswith('.'):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=True):
                            entries.append(entry.name + '/')
                    except OSError:
                        pass
            return entries, base_prefix, partial
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            return [], base_prefix, partial

    # ------------------------------------------------------------------
    # Completion interface
    # ------------------------------------------------------------------

    def update(self, text: str, cursor_pos: int):
        """Update the menu based on the current input text."""
        parsed = self._parse(text)
        if not parsed:
            self.hide()
            return

        _, path_text = parsed
        items, base_prefix, partial = self._get_completions(path_text)

        # Suppression: user ESC'd this exact path_text prefix
        if self.suppressed_prefix is not None:
            if path_text.startswith(self.suppressed_prefix):
                self.hide()
                return
            else:
                self.suppressed_prefix = None

        if not items:
            self.hide()
            return

        # Cache for accept_selection
        self._last_base_prefix = base_prefix

        self.menu.update(items, partial, display_prefix="")
        self.is_active = self.menu.is_visible

    def accept_selection(self, text: str) -> Optional[str]:
        """Accept current selection; return the completed input text."""
        selected = self.menu.get_selected()
        if not selected:
            return None

        parsed = self._parse(text)
        if not parsed:
            return None

        cmd, _ = parsed
        return f"/{cmd} {self._last_base_prefix}{selected}"

    def cancel(self, text: str, cursor_pos: int):
        """User pressed ESC — suppress menu for the current path_text."""
        parsed = self._parse(text)
        if parsed:
            _, path_text = parsed
            if path_text:
                self.suppressed_prefix = path_text
        self.hide()

    def navigate_up(self):
        if self.is_active:
            self.menu.action_up()

    def navigate_down(self):
        if self.is_active:
            self.menu.action_down()

    def hide(self):
        self.menu.hide()
        self.is_active = False
