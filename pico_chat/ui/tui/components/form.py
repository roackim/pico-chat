"""
Form field components for TUI forms.

Provides toggle, text input, textarea, checkbox-list, and radio-list fields
that can be composed into a FormPopup modal dialog.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.focus import FocusScope
from pico_chat.ui.tui.events import KeyEvent
from pico_chat.ui.tui.components.input import LineInput, BoxInput
from pico_chat.ui.tui.components.field_models import (
    BoolFieldModel, ChoiceFieldModel, FieldModel, TextFieldModel,
)
from pico_chat import pico_cfg


# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────

def _label_color():
    """Orange/amber for field labels."""
    return theme.WARNING

def _focus_marker(focused: bool) -> str:
    return "▸ " if focused else "  "


# ────────────────────────────────────────────────────────────────
# Base class
# ────────────────────────────────────────────────────────────────

class FormField(ABC):
    """Base class for all form fields."""

    def __init__(self, label: str, *, required: bool = False,
                 model: Optional[FieldModel] = None):
        self.label = label
        self.required = required
        self.focused = False
        self.model = model

    def validate(self) -> bool:
        return self.model.validate() if self.model is not None else True

    @property
    def dirty(self) -> bool:
        return self.model.dirty if self.model is not None else False

    def reset(self):
        if self.model is not None:
            self.model.reset()
            self.set_value(self.model.value)

    @abstractmethod
    def get_value(self) -> Any: ...
    @abstractmethod
    def set_value(self, value: Any): ...
    @abstractmethod
    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int): ...
    def get_preferred_height(self, width: int) -> int:
        return 1
    @abstractmethod
    def handle_input(self, event: Any) -> bool: ...

    def _write(self, buffer: Buffer, x: int, y: int, text: str,
               fg=None, max_width: int = 0):
        if max_width <= 0:
            return
        buffer.write_str(x, y, text, fg=fg or theme.DEFAULT, max_width=max_width)


# ────────────────────────────────────────────────────────────────
# Toggle field  —  ▸ [x] Label  /    [ ] Label
# ────────────────────────────────────────────────────────────────

class ToggleField(FormField):
    """Boolean toggle rendered as ``[x] Label`` / ``[ ] Label``."""

    def __init__(self, label: str, *, value: bool = False,
                 model: Optional[BoolFieldModel] = None, **kw):
        model = model or BoolFieldModel(value, required=kw.get("required", False))
        super().__init__(label, model=model, **kw)
        self._value = model.value

    def get_value(self) -> bool:
        return self._value

    def set_value(self, value: bool):
        self._value = bool(value)
        self.model.set_value(self._value)

    def toggle(self):
        self._value = not self._value

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        mark = "[x]" if self._value else "[ ]"
        lc = _label_color() if self.focused else theme.DEFAULT
        m = _focus_marker(self.focused)
        # ▸ [x] Label  or    [ ] Label
        check = f"{mark} "
        self._write(buffer, x, y, m, fg=theme.DEFAULT, max_width=width)
        self._write(buffer, x + len(m), y, check, fg=theme.DEFAULT,
                    max_width=width - len(m))
        self._write(buffer, x + len(m) + len(check), y, self.label, fg=lc,
                    max_width=width - len(m) - len(check))

    def handle_input(self, event: Any) -> bool:
        key = event.key if isinstance(event, KeyEvent) else event
        if isinstance(event, (str, KeyEvent)) and key in (" ", "\r", "\n"):
            self.toggle()
            return True
        return False


# ────────────────────────────────────────────────────────────────
# TextField — single-line text input with blinking cursor
# ────────────────────────────────────────────────────────────────

class TextField(FormField):
    """Single-line text input. Reuses TextBuffer / CursorRenderer patterns."""

    def __init__(self, label: str, *, value: str = "", placeholder: str = "", **kw):
        model = kw.pop("model", None) or TextFieldModel(
            value, required=kw.get("required", False))
        super().__init__(label, model=model, **kw)
        self._editor = LineInput(model.value, placeholder)

    @property
    def _value(self):
        return self._editor.value

    @_value.setter
    def _value(self, value):
        self._editor.value = str(value)

    @property
    def cursor_pos(self):
        return self._editor.cursor_pos

    @cursor_pos.setter
    def cursor_pos(self, value):
        self._editor.cursor_pos = value

    def get_value(self) -> str:
        return self._editor.get_value()

    def set_value(self, value: str):
        self._editor.set_value(value)
        self.model.set_value(value)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        m = _focus_marker(self.focused)
        label_str = f"{self.label}: "
        lc = _label_color() if self.focused else theme.DEFAULT

        # Focus marker (white/default)
        self._write(buffer, x, y, m, fg=theme.DEFAULT, max_width=width)
        # Label (orange)
        lx = x + len(m)
        self._write(buffer, lx, y, label_str, fg=lc, max_width=width - len(m))
        # Value or placeholder and the shared cursor-aware editor
        vx = lx + len(label_str)
        vw = width - len(m) - len(label_str)
        if vw <= 0:
            return
        self._editor.set_focused(self.focused)
        self._editor.set_layout(vx, y, vw, 1)
        self._editor.render(buffer)

    def handle_input(self, event: Any) -> bool:
        handled = self._editor.handle_input(event)
        if handled:
            self.model.set_value(self.get_value())
        return handled


# ────────────────────────────────────────────────────────────────
# TextAreaField — multiline text input
# ────────────────────────────────────────────────────────────────

class TextAreaField(FormField):
    """Multiline text input (description / notes style)."""

    def __init__(self, label: str, *, value: str = "", placeholder: str = "",
                 min_lines: int = 3, **kw):
        model = kw.pop("model", None) or TextFieldModel(
            value, required=kw.get("required", False))
        super().__init__(label, model=model, **kw)
        self._editor = BoxInput(model.value, placeholder)
        self.min_lines = min_lines

    @property
    def _value(self):
        return self._editor.value

    @_value.setter
    def _value(self, value):
        self._editor.value = str(value)

    @property
    def cursor_row(self):
        return self._editor.cursor_row

    @cursor_row.setter
    def cursor_row(self, value):
        self._editor.cursor_row = value

    @property
    def cursor_col(self):
        return self._editor.cursor_col

    @cursor_col.setter
    def cursor_col(self, value):
        self._editor.cursor_col = value

    def get_value(self) -> str:
        return self._editor.get_value()

    def set_value(self, value: str):
        self._editor.set_value(value)
        self.model.set_value(value)

    def _lines(self) -> List[str]:
        return self._editor._lines()

    def get_preferred_height(self, width: int) -> int:
        return max(self.min_lines, len(self._lines()) + 1)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        m = _focus_marker(self.focused)
        lc = _label_color() if self.focused else theme.DEFAULT

        self._write(buffer, x, y, f"{m}{self.label}:", fg=lc, max_width=width)

        self._editor.set_focused(self.focused)
        self._editor.set_layout(x + 1, y + 1, width - 1, max(0, height - 1))
        self._editor.render(buffer)

    def handle_input(self, event: Any) -> bool:
        handled = self._editor.handle_input(event)
        if handled:
            self.model.set_value(self.get_value())
        return handled


# ────────────────────────────────────────────────────────────────
# Checkbox list  —  [ ] / [x] per item
# ────────────────────────────────────────────────────────────────

class CheckboxListField(FormField):
    """Multi-select list rendered as ``[ ]`` / ``[x]`` per option."""

    def __init__(self, label: str, *, options: List[str],
                 value: Optional[List[int]] = None, **kw):
        model = kw.pop("model", None) or FieldModel(
            list(value or []), required=kw.get("required", False))
        super().__init__(label, model=model, **kw)
        self.options = options
        self._selected: set = set(value or [])
        self._cursor: int = 0

    def get_value(self) -> List[int]:
        return sorted(self._selected)

    def set_value(self, value):
        self._selected = set(value) if value else set()
        self.model.set_value(self.get_value())

    def get_preferred_height(self, width: int) -> int:
        return 1 + len(self.options)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        lc = _label_color() if self.focused else theme.DEFAULT
        m = _focus_marker(self.focused)
        self._write(buffer, x, y, f"{m}{self.label}:", fg=lc, max_width=width)
        for i, opt in enumerate(self.options):
            ly = y + 1 + i
            if ly >= y + height:
                break
            mark = "[x]" if i in self._selected else "[ ]"
            is_c = self.focused and i == self._cursor
            oc = theme.FOCUSED if is_c else theme.DEFAULT
            cm = "▸" if is_c else " "
            text = f"  {cm}{mark} {opt}"
            self._write(buffer, x + 1, ly, text, fg=oc, max_width=width - 1)

    def handle_input(self, event: Any) -> bool:
        if not isinstance(event, (str, KeyEvent)):
            return False
        key = event.key if isinstance(event, KeyEvent) else event
        if key == "\x1b[A":
            if self._cursor > 0:
                self._cursor -= 1
                return True
        elif key == "\x1b[B":
            if self._cursor < len(self.options) - 1:
                self._cursor += 1
                return True
        elif key in (" ", "\r", "\n"):
            if self._cursor in self._selected:
                self._selected.discard(self._cursor)
            else:
                self._selected.add(self._cursor)
            self.model.set_value(self.get_value())
            return True
        return False


# ────────────────────────────────────────────────────────────────
# Radio list  —  ( ) / (x) per item
# ────────────────────────────────────────────────────────────────

class RadioListField(FormField):
    """Single-select list rendered as ``()`` / ``(x)`` per option."""

    def __init__(self, label: str, *, options: List[str],
                 value: Optional[int] = None, **kw):
        model = kw.pop("model", None) or ChoiceFieldModel(
            value, required=kw.get("required", False))
        super().__init__(label, model=model, **kw)
        self.options = options
        self._selected: Optional[int] = model.value
        self._cursor: int = model.value if model.value is not None else 0

    def get_value(self) -> Optional[int]:
        return self._selected

    def set_value(self, value):
        self._selected = int(value) if value is not None else None
        if self._selected is not None:
            self._cursor = self._selected
        self.model.set_value(self._selected)

    def get_preferred_height(self, width: int) -> int:
        return 1 + len(self.options)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        lc = _label_color() if self.focused else theme.DEFAULT
        m = _focus_marker(self.focused)
        self._write(buffer, x, y, f"{m}{self.label}:", fg=lc, max_width=width)
        for i, opt in enumerate(self.options):
            ly = y + 1 + i
            if ly >= y + height:
                break
            mark = "(x)" if i == self._selected else "( )"
            is_c = self.focused and i == self._cursor
            oc = theme.FOCUSED if is_c else theme.DEFAULT
            cm = "▸" if is_c else " "
            text = f"  {cm}{mark} {opt}"
            self._write(buffer, x + 1, ly, text, fg=oc, max_width=width - 1)

    def handle_input(self, event: Any) -> bool:
        if not isinstance(event, (str, KeyEvent)):
            return False
        key = event.key if isinstance(event, KeyEvent) else event
        if key == "\x1b[A":
            if self._cursor > 0:
                self._cursor -= 1
                return True
        elif key == "\x1b[B":
            if self._cursor < len(self.options) - 1:
                self._cursor += 1
                return True
        elif key in (" ", "\r", "\n"):
            self._selected = self._cursor
            self.model.set_value(self._selected)
            return True
        return False


# ────────────────────────────────────────────────────────────────
# FormContainer — vertical layout of fields
# ────────────────────────────────────────────────────────────────

class FormContainer(Component):
    """Manages vertical layout, focus, and input routing for a list of fields."""

    def __init__(self, fields: List[FormField], id: Optional[str] = None):
        super().__init__(id)
        self.fields = fields
        for field in self.fields:
            field.parent = self
        self._focus_scope = FocusScope(self.fields)
        self._scroll_offset: int = 0
        self._field_heights: List[int] = []
        self._field_offsets: List[int] = []

    @property
    def _focus_index(self) -> int:
        return self._focus_scope.focused_index or 0

    @property
    def focus_scope(self) -> FocusScope:
        return self._focus_scope

    def _set_focus(self, index: int):
        self._focus_scope.manager.focus(max(0, min(index, len(self.fields) - 1)))
        self.mark_changed()

    def focus_next(self):
        if self.fields:
            self._focus_scope.focus_next()
            self.mark_changed()
        self._ensure_focus_visible()

    def focus_prev(self):
        if self.fields:
            self._focus_scope.focus_previous()
            self.mark_changed()
        self._ensure_focus_visible()

    def get_focused_field(self) -> Optional[FormField]:
        if 0 <= self._focus_index < len(self.fields):
            return self.fields[self._focus_index]
        return None

    @property
    def dirty(self) -> bool:
        return any(field.dirty for field in self.fields)

    def reset(self):
        for field in self.fields:
            field.reset()
        self.mark_changed()

    def _compute_layout(self):
        self._field_heights = []
        self._field_offsets = []
        y = 0
        for field in self.fields:
            h = field.get_preferred_height(self.width)
            if self._field_offsets:
                y += 1  # 1 row spacing
            self._field_offsets.append(y)
            self._field_heights.append(h)
            y += h
        self._total_height = y

    def get_preferred_height(self, width: int) -> int:
        self.width = width
        self._compute_layout()
        return self._total_height

    def set_layout(self, x: int, y: int, width: int, height: int):
        super().set_layout(x, y, width, height)
        self._compute_layout()
        self._ensure_focus_visible()

    def _ensure_focus_visible(self):
        if not self._field_offsets or not self.fields:
            return
        fy = self._field_offsets[self._focus_index]
        fh = self._field_heights[self._focus_index]
        if fy + fh > self._scroll_offset + self.height:
            self._scroll_offset = fy + fh - self.height
        if fy < self._scroll_offset:
            self._scroll_offset = fy

    def render(self, buffer: Buffer):
        if not self.fields:
            return
        for i, field in enumerate(self.fields):
            fy = self._field_offsets[i] - self._scroll_offset
            fh = self._field_heights[i]
            if fy + fh <= 0 or fy >= self.height:
                continue
            clipped_h = min(fh, self.height - fy)
            if clipped_h <= 0:
                continue
            field.render(buffer, self.x, self.y + fy, self.width, clipped_h)

    def handle_input(self, event: Any) -> bool:
        if not self.fields:
            return False
        field = self.fields[self._focus_index]

        if isinstance(event, (str, KeyEvent)):
            key = event.key if isinstance(event, KeyEvent) else event
            if key == "\t":
                self.focus_next()
                self._ensure_focus_visible()
                return True
            if key == "\x1b[Z":  # Shift+Tab
                self.focus_prev()
                self._ensure_focus_visible()
                return True

        if field.handle_input(event):
            self.mark_changed()  # text changed → re-render
            return True

        if isinstance(event, (str, KeyEvent)):
            key = event.key if isinstance(event, KeyEvent) else event
            if key == "\x1b[A":
                self.focus_prev()
                self._ensure_focus_visible()
                return True
            elif key == "\x1b[B":
                self.focus_next()
                self._ensure_focus_visible()
                return True
        return False
