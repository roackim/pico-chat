"""Open files in the user's editor, suspending the TUI while it runs.

Configuration is edited as files: ``/config``, ``/edit`` and ``/role edit``
shell out to ``$VISUAL``/``$EDITOR`` (falling back to nano/vim/vi) rather than
building in-TUI forms.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Optional


def resolve_editor() -> List[str]:
    """Command used to edit a file: ``$VISUAL``, ``$EDITOR``, then a fallback."""
    for variable in ("VISUAL", "EDITOR"):
        value = os.environ.get(variable)
        if value:
            return shlex.split(value)
    for candidate in ("nano", "vim", "vi"):
        if shutil.which(candidate):
            return [candidate]
    return []


def edit_file(path: Path) -> bool:
    """Open ``path`` in the resolved editor. Returns False if none was found."""
    command = resolve_editor()
    if not command:
        return False
    return subprocess.call(command + [str(path)]) == 0


def open_editor(ui: Any, path: Path) -> bool:
    """Edit ``path``, temporarily releasing the TUI's terminal.

    Restores the TUI afterwards even if the editor fails or is interrupted.
    """
    terminal = getattr(getattr(ui, "compositor", None), "terminal", None)
    if terminal is not None:
        terminal.suspend()
    try:
        return edit_file(Path(path))
    finally:
        if terminal is not None:
            terminal.resume()


__all__ = ["resolve_editor", "edit_file", "open_editor"]
