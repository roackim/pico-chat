"""
Form field components for TUI forms.

Provides toggle, text input, textarea, checkbox-list, and radio-list fields
that can be composed into a FormPopup modal dialog.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import theme
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

    def __init__(self, label: str, *, required: bool = False):
        self.label = label
        self.required = required
        self.focused = False

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
# Cursor blink helper (shared by TextField and TextAreaField)
# ────────────────────────────────────────────────────────────────

class _CursorBlink:
    """Blinking cursor state machine, same logic as InputComponent."""

    def __init__(self):
        self.visible: bool = True
        self._last_input: float = 0.0
        self._last_blink: float = 0.0

    def mark_input(self):
        self._last_input = time.time()
        self.visible = True

    def tick(self) -> bool:
        """Advance timer. Returns True if visibility changed."""
        now = time.time()
        cfg = pico_cfg.config
        pulse = getattr(cfg, "ui_cursor_pulse_delay", 0.5)
        blink = getattr(cfg, "ui_cursor_blink_interval", 0.5)
        if now - self._last_input < pulse:
            if not self.visible:
                self.visible = True
                return True
            return False
        if now - self._last_blink >= blink:
            self._last_blink = now
            self.visible = not self.visible
            return True
        return False


# ────────────────────────────────────────────────────────────────
# Toggle field  —  ▸ [x] Label  /    [ ] Label
# ────────────────────────────────────────────────────────────────

class ToggleField(FormField):
    """Boolean toggle rendered as ``[x] Label`` / ``[ ] Label``."""

    def __init__(self, label: str, *, value: bool = False, **kw):
        super().__init__(label, **kw)
        self._value = value

    def get_value(self) -> bool:
        return self._value

    def set_value(self, value: bool):
        self._value = bool(value)

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
        if isinstance(event, str) and event in (" ", "\r", "\n"):
            self.toggle()
            return True
        return False


# ────────────────────────────────────────────────────────────────
# TextField — single-line text input with blinking cursor
# ────────────────────────────────────────────────────────────────

class TextField(FormField):
    """Single-line text input. Reuses TextBuffer / CursorRenderer patterns."""

    def __init__(self, label: str, *, value: str = "", placeholder: str = "", **kw):
        super().__init__(label, **kw)
        self._value = value
        self.placeholder = placeholder
        self.cursor_pos: int = len(value)
        self._blink = _CursorBlink()

    def get_value(self) -> str:
        return self._value

    def set_value(self, value: str):
        self._value = str(value)
        self.cursor_pos = len(self._value)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        m = _focus_marker(self.focused)
        label_str = f"{self.label}: "
        lc = _label_color() if self.focused else theme.DEFAULT

        # Focus marker (white/default)
        self._write(buffer, x, y, m, fg=theme.DEFAULT, max_width=width)
        # Label (orange)
        lx = x + len(m)
        self._write(buffer, lx, y, label_str, fg=lc, max_width=width - len(m))
        # Value or placeholder
        vx = lx + len(label_str)
        vw = width - len(m) - len(label_str)
        if vw <= 0:
            return
        if self._value:
            self._write(buffer, vx, y, self._value, fg=theme.DEFAULT, max_width=vw)
        elif self.placeholder:
            self._write(buffer, vx, y, self.placeholder, fg=theme.MUTED, max_width=vw)

        # Blinking cursor — reverse video, no background color
        if self.focused and vw > 0:
            self._blink.tick()
            if self._blink.visible:
                cx = vx + min(self.cursor_pos, len(self._value))
                if cx < x + width:
                    ch = self._value[self.cursor_pos] if self.cursor_pos < len(self._value) else " "
                    buffer.set(cx, y, ch, reverse=True)

    def handle_input(self, event: Any) -> bool:
        if not isinstance(event, str):
            return False
        handled = False
        if event == "\x1b[D":  # Left
            if self.cursor_pos > 0:
                self.cursor_pos -= 1
                handled = True
        elif event == "\x1b[C":  # Right
            if self.cursor_pos < len(self._value):
                self.cursor_pos += 1
                handled = True
        elif event == "\x1b[H":  # Home
            self.cursor_pos = 0
            handled = True
        elif event == "\x1b[F":  # End
            self.cursor_pos = len(self._value)
            handled = True
        elif event == "\x7f":  # Backspace
            if self.cursor_pos > 0:
                self._value = self._value[:self.cursor_pos-1] + self._value[self.cursor_pos:]
                self.cursor_pos -= 1
                handled = True
        elif event == "\x1b[3~":  # Delete
            if self.cursor_pos < len(self._value):
                self._value = self._value[:self.cursor_pos] + self._value[self.cursor_pos+1:]
                handled = True
        elif len(event) == 1 and event.isprintable():
            self._value = self._value[:self.cursor_pos] + event + self._value[self.cursor_pos:]
            self.cursor_pos += 1
            handled = True
        if handled:
            self._blink.mark_input()
        return handled


# ────────────────────────────────────────────────────────────────
# TextAreaField — multiline text input
# ────────────────────────────────────────────────────────────────

class TextAreaField(FormField):
    """Multiline text input (description / notes style)."""

    def __init__(self, label: str, *, value: str = "", placeholder: str = "",
                 min_lines: int = 3, **kw):
        super().__init__(label, **kw)
        self._value = value
        self.placeholder = placeholder
        self.min_lines = min_lines
        self.cursor_row: int = 0
        self.cursor_col: int = 0
        self._blink = _CursorBlink()

    def get_value(self) -> str:
        return self._value

    def set_value(self, value: str):
        self._value = str(value)
        self.cursor_row = 0
        self.cursor_col = 0

    def _lines(self) -> List[str]:
        return self._value.split("\n") if self._value else [""]

    def get_preferred_height(self, width: int) -> int:
        return max(self.min_lines, len(self._lines()) + 1)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        m = _focus_marker(self.focused)
        lc = _label_color() if self.focused else theme.DEFAULT

        self._write(buffer, x, y, f"{m}{self.label}:", fg=lc, max_width=width)

        lines = self._lines()
        for i, line in enumerate(lines):
            ly = y + 1 + i
            if ly >= y + height:
                break
            tc = theme.DEFAULT if self._value else theme.MUTED
            display = line if self._value else self.placeholder
            self._write(buffer, x + 1, ly, display, fg=tc, max_width=width - 1)

        # Blinking cursor
        if self.focused:
            self._blink.tick()
            if self._blink.visible:
                cy = y + 1 + min(self.cursor_row, len(lines) - 1)
                cx = x + 1 + min(self.cursor_col,
                                 len(lines[min(self.cursor_row, len(lines) - 1)]))
                if cy < y + height and cx < x + width:
                    line = lines[min(self.cursor_row, len(lines) - 1)]
                    ch = line[self.cursor_col] if self.cursor_col < len(line) else " "
                    buffer.set(cx, cy, ch, reverse=True)

    def handle_input(self, event: Any) -> bool:
        if not isinstance(event, str):
            return False
        lines = self._lines()
        handled = False
        if event in ("\r", "\n"):
            line = lines[self.cursor_row]
            lines[self.cursor_row] = line[:self.cursor_col]
            lines.insert(self.cursor_row + 1, line[self.cursor_col:])
            self._value = "\n".join(lines)
            self.cursor_row += 1
            self.cursor_col = 0
            handled = True
        elif event == "\x1b[A":
            if self.cursor_row > 0:
                self.cursor_row -= 1
                self.cursor_col = min(self.cursor_col, len(lines[self.cursor_row]))
                handled = True
        elif event == "\x1b[B":
            if self.cursor_row < len(lines) - 1:
                self.cursor_row += 1
                self.cursor_col = min(self.cursor_col, len(lines[self.cursor_row]))
                handled = True
        elif event == "\x1b[D":
            if self.cursor_col > 0:
                self.cursor_col -= 1
                handled = True
            elif self.cursor_row > 0:
                self.cursor_row -= 1
                self.cursor_col = len(lines[self.cursor_row])
                handled = True
        elif event == "\x1b[C":
            if self.cursor_col < len(lines[self.cursor_row]):
                self.cursor_col += 1
                handled = True
            elif self.cursor_row < len(lines) - 1:
                self.cursor_row += 1
                self.cursor_col = 0
                handled = True
        elif event == "\x7f":
            if self.cursor_col > 0:
                line = lines[self.cursor_row]
                lines[self.cursor_row] = line[:self.cursor_col-1] + line[self.cursor_col:]
                self._value = "\n".join(lines)
                self.cursor_col -= 1
                handled = True
            elif self.cursor_row > 0:
                prev_len = len(lines[self.cursor_row - 1])
                lines[self.cursor_row - 1] += lines[self.cursor_row]
                del lines[self.cursor_row]
                self._value = "\n".join(lines)
                self.cursor_row -= 1
                self.cursor_col = prev_len
                handled = True
        elif event == "\x1b[3~":
            line = lines[self.cursor_row]
            if self.cursor_col < len(line):
                lines[self.cursor_row] = line[:self.cursor_col] + line[self.cursor_col+1:]
                self._value = "\n".join(lines)
                handled = True
            elif self.cursor_row < len(lines) - 1:
                lines[self.cursor_row] += lines[self.cursor_row + 1]
                del lines[self.cursor_row + 1]
                self._value = "\n".join(lines)
                handled = True
        elif event == "\x1b[H":
            self.cursor_col = 0
            handled = True
        elif event == "\x1b[F":
            self.cursor_col = len(lines[self.cursor_row])
            handled = True
        elif len(event) == 1 and event.isprintable():
            line = lines[self.cursor_row]
            lines[self.cursor_row] = line[:self.cursor_col] + event + line[self.cursor_col:]
            self._value = "\n".join(lines)
            self.cursor_col += 1
            handled = True
        if handled:
            self._blink.mark_input()
        return handled


# ────────────────────────────────────────────────────────────────
# Checkbox list  —  [ ] / [x] per item
# ────────────────────────────────────────────────────────────────

class CheckboxListField(FormField):
    """Multi-select list rendered as ``[ ]`` / ``[x]`` per option."""

    def __init__(self, label: str, *, options: List[str],
                 value: Optional[List[int]] = None, **kw):
        super().__init__(label, **kw)
        self.options = options
        self._selected: set = set(value or [])
        self._cursor: int = 0

    def get_value(self) -> List[int]:
        return sorted(self._selected)

    def set_value(self, value):
        self._selected = set(value) if value else set()

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
        if not isinstance(event, str):
            return False
        if event == "\x1b[A":
            if self._cursor > 0:
                self._cursor -= 1
                return True
        elif event == "\x1b[B":
            if self._cursor < len(self.options) - 1:
                self._cursor += 1
                return True
        elif event in (" ", "\r", "\n"):
            if self._cursor in self._selected:
                self._selected.discard(self._cursor)
            else:
                self._selected.add(self._cursor)
            return True
        return False


# ────────────────────────────────────────────────────────────────
# Radio list  —  ( ) / (x) per item
# ────────────────────────────────────────────────────────────────

class RadioListField(FormField):
    """Single-select list rendered as ``()`` / ``(x)`` per option."""

    def __init__(self, label: str, *, options: List[str],
                 value: Optional[int] = None, **kw):
        super().__init__(label, **kw)
        self.options = options
        self._selected: Optional[int] = value
        self._cursor: int = value if value is not None else 0

    def get_value(self) -> Optional[int]:
        return self._selected

    def set_value(self, value):
        self._selected = int(value) if value is not None else None
        if self._selected is not None:
            self._cursor = self._selected

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
        if not isinstance(event, str):
            return False
        if event == "\x1b[A":
            if self._cursor > 0:
                self._cursor -= 1
                return True
        elif event == "\x1b[B":
            if self._cursor < len(self.options) - 1:
                self._cursor += 1
                return True
        elif event in (" ", "\r", "\n"):
            self._selected = self._cursor
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
        self._focus_index: int = 0
        self._scroll_offset: int = 0
        self._field_heights: List[int] = []
        self._field_offsets: List[int] = []
        if self.fields:
            self.fields[0].focused = True

    def _set_focus(self, index: int):
        if self.fields:
            self.fields[self._focus_index].focused = False
        self._focus_index = max(0, min(index, len(self.fields) - 1))
        if self.fields:
            self.fields[self._focus_index].focused = True
        self.mark_changed()

    def focus_next(self):
        self._set_focus((self._focus_index + 1) % len(self.fields))
        self._ensure_focus_visible()

    def focus_prev(self):
        self._set_focus((self._focus_index - 1) % len(self.fields))
        self._ensure_focus_visible()

    def get_focused_field(self) -> Optional[FormField]:
        if 0 <= self._focus_index < len(self.fields):
            return self.fields[self._focus_index]
        return None

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

        if isinstance(event, str):
            if event == "\t":
                self.focus_next()
                self._ensure_focus_visible()
                return True
            if event == "\x1b[Z":  # Shift+Tab
                self.focus_prev()
                self._ensure_focus_visible()
                return True

        if field.handle_input(event):
            self.mark_changed()  # text changed → re-render
            return True

        if isinstance(event, str):
            if event == "\x1b[A":
                self.focus_prev()
                self._ensure_focus_visible()
                return True
            elif event == "\x1b[B":
                self.focus_next()
                self._ensure_focus_visible()
                return True
        return False
