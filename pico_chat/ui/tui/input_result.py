"""Explicit outcomes for composable TUI input routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FocusIntent = Literal["next", "previous"]


@dataclass(frozen=True)
class InputResult:
    """The result of delivering an input event to a component.

    ``handled`` controls event propagation. ``focus`` is an optional request
    for the nearest owning container to move to a sibling; a leaf never needs
    to know which sibling that is. ``redraw`` permits a component to request a
    repaint even when it did not mutate a field model.
    """

    handled: bool = False
    focus: FocusIntent | None = None
    redraw: bool = False

    @classmethod
    def from_legacy(cls, handled: bool) -> "InputResult":
        """Adapt the existing boolean field-handler protocol."""
        return cls(handled=handled, redraw=handled)
