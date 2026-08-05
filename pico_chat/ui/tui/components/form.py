"""
Form field components for TUI forms.

Provides toggle, text input, textarea, checkbox-list, and radio-list fields
that can be composed into a FormPopup modal dialog.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional

from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.focus import FocusScope
from pico_chat.ui.tui.events import KeyEvent, MouseEvent
from pico_chat.ui.tui.input_result import InputResult
from pico_chat.ui.tui.components.input import LineInput, BoxInput
from pico_chat.ui.tui.components.button import Button
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
    return "▸ " if focused else ""


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
        self.suppress_focus_marker = False
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
    def activate(self) -> bool:
        """Activate this field, if it exposes an action."""
        return False

    def focus_marker(self) -> str:
        return "" if self.suppress_focus_marker else _focus_marker(self.focused)
    @abstractmethod
    def handle_input(self, event: Any) -> bool: ...

    def handle_input_result(self, event: Any) -> InputResult:
        """Handle input using the composable routing protocol.

        Existing fields continue to implement ``handle_input()`` while new
        composite fields can override this method to request sibling focus at
        a local navigation edge.
        """
        return InputResult.from_legacy(self.handle_input(event))

    def _write(self, buffer: Buffer, x: int, y: int, text: str,
               fg=None, max_width: int = 0, reverse: bool = False):
        if max_width <= 0:
            return
        buffer.write_str(
            x, y, text, fg=fg or theme.DEFAULT,
            reverse=reverse, max_width=max_width,
        )


class FormSectionTitle(FormField):
    """Non-focusable heading used to visually group form fields."""

    focusable = False

    def get_value(self) -> None:
        return None

    def set_value(self, value) -> None:
        return None

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        self._write(buffer, x, y, self.label, fg=_label_color(), max_width=width)

    def handle_input(self, event: Any) -> bool:
        return False


# ────────────────────────────────────────────────────────────────
# Toggle field  —  ▸ [x] Label  /    [ ] Label
# ────────────────────────────────────────────────────────────────

class ToggleField(FormField):
    """Boolean toggle rendered as ``[x] Label`` / ``[ ] Label``."""

    def __init__(self, label: str, *, value: bool = False,
                 model: Optional[BoolFieldModel] = None, **kw):
        self._on_change = kw.pop("on_change", None)
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
        self.model.set_value(self._value)
        if self._on_change:
            self._on_change(self._value)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        mark = "[x]" if self._value else "[ ]"
        lc = _label_color() if self.focused else theme.DEFAULT
        m = self.focus_marker()
        self._write(buffer, x, y, m, fg=theme.DEFAULT, max_width=width)
        self._write(buffer, x + len(m), y, self.label, fg=lc,
                    max_width=max(0, width - len(m) - 4))
        self._write(buffer, x + max(len(m), width - 3), y, mark,
                    fg=theme.FOCUSED if self.focused else theme.DEFAULT,
                    max_width=min(3, width))

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
        m = self.focus_marker()
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
        m = self.focus_marker()
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
        m = self.focus_marker()
        self._write(buffer, x, y, f"{m}{self.label}:", fg=lc, max_width=width)
        for i, opt in enumerate(self.options):
            ly = y + 1 + i
            if ly >= y + height:
                break
            mark = "[x]" if i in self._selected else "[ ]"
            is_c = self.focused and i == self._cursor
            oc = theme.FOCUSED if is_c else theme.DEFAULT
            cm = "▸" if is_c else " "
            text = f"{cm}{mark} {opt}"
            self._write(buffer, x, ly, text, fg=oc, max_width=width)

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
        self._on_change = kw.pop("on_change", None)
        model = kw.pop("model", None) or ChoiceFieldModel(
            value, required=kw.get("required", False))
        super().__init__(label, model=model, **kw)
        self.options = options
        self._selected: Optional[int] = model.value
        self._cursor: int = model.value if model.value is not None else 0

    def get_value(self) -> Optional[int]:
        return self._selected

    def set_value(self, value):
        value = int(value)
        if not 0 <= value < len(self.options):
            raise ValueError("radio selection index is out of range")
        changed = self._selected != value
        self._selected = value
        if self._selected is not None:
            self._cursor = self._selected
        self.model.set_value(self._selected)
        if changed and self._on_change:
            self._on_change(self._selected)

    def get_preferred_height(self, width: int) -> int:
        return 1 + len(self.options)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        lc = _label_color() if self.focused else theme.DEFAULT
        m = self.focus_marker()
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
            self.set_value(self._cursor)
            return True
        return False


class ProfileListField(RadioListField):
    """Profile list with inline duplicate/delete actions and a create row."""

    def __init__(self, label: str, *, options: List[str], on_create=None,
                 on_rename=None, on_duplicate=None, on_delete=None, **kw):
        self.on_create = on_create
        self.on_rename = on_rename
        self.on_duplicate = on_duplicate
        self.on_delete = on_delete
        self._action_cursor = 0  # 0 = row, 1 = rename, 2 = duplicate, 3 = delete
        self._renaming = False
        self._rename_text = ""
        super().__init__(label, options=options, **kw)

    def get_preferred_height(self, width: int) -> int:
        return 2 + len(self.options)

    def get_value(self) -> str:
        """Return the selected profile name, never the radio-list index."""
        if self._selected is None:
            return ""
        return self.options[self._selected]

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        self._write(buffer, x, y, f"{self.focus_marker()}{self.label}:",
                    fg=_label_color() if self.focused else theme.DEFAULT, max_width=width)
        rename_x = max(0, width - 37)
        duplicate_x = max(0, width - 27)
        delete_x = max(0, width - 14)
        for i, option in enumerate(self.options):
            row_y = y + 1 + i
            if row_y >= y + height:
                break
            selected = i == self._selected
            focused = i == self._cursor
            mark = "(x)" if selected else "( )"
            color = theme.FOCUSED if focused else theme.DEFAULT
            arrow = "▸" if focused else " "
            if option == "+ create new":
                # Deliberately render this as a single primary action rather
                # than another radio option: it creates a profile, it does not
                # select one.
                self._write(buffer, x, row_y, f"{arrow}  ── + Create profile ──",
                            fg=theme.FOCUSED if focused else theme.SUCCESS,
                            max_width=width)
                continue
            name_width = max(1, rename_x - 7)
            name = f"{self._rename_text}▏" if self._renaming and focused else option
            self._write(buffer, x, row_y, f"{arrow} {mark} {name[:name_width]}",
                        fg=color,
                        max_width=name_width + 7)
            self._write(buffer, x + rename_x, row_y, "[rename]",
                        fg=theme.FOCUSED if focused and self._action_cursor == 1 else theme.MUTED,
                        max_width=8)
            self._write(buffer, x + duplicate_x, row_y, "[duplicate]",
                        fg=theme.FOCUSED if focused and self._action_cursor == 2 else theme.MUTED,
                        max_width=11)
            self._write(buffer, x + delete_x, row_y, "[remove]",
                        fg=theme.FOCUSED if focused and self._action_cursor == 3 else theme.ERROR,
                        max_width=8)

    def handle_input(self, event: Any) -> bool:
        key = event.key if isinstance(event, KeyEvent) else event
        if isinstance(event, (str, KeyEvent)):
            if self._renaming:
                if key in ("\x7f", "\b"):
                    self._rename_text = self._rename_text[:-1]
                    return True
                if isinstance(key, str) and len(key) == 1 and key.isprintable():
                    self._rename_text += key
                    return True
                return True
            if key == "\x1b[A":
                if self._cursor > 0:
                    self._cursor -= 1
                    self._action_cursor = 0
                    if self.parent:
                        self.parent.mark_changed()
                    return True
                return False
            if key == "\x1b[B":
                if self._cursor < len(self.options) - 1:
                    self._cursor += 1
                    self._action_cursor = 0
                    if self.parent:
                        self.parent.mark_changed()
                    return True
                # Let FormContainer move to the next form field once the
                # cursor has reached the Create profile action.
                return False
            if key in ("\x1b[C", "l"):
                if self._cursor < len(self.options) - 1 and self.options[self._cursor] != "+ create new":
                    self._action_cursor = min(3, self._action_cursor + 1)
                if self.parent:
                    self.parent.mark_changed()
                return True
            if key in ("\x1b[D", "h"):
                if self.options[self._cursor] != "+ create new":
                    self._action_cursor = max(0, self._action_cursor - 1)
                if self.parent:
                    self.parent.mark_changed()
                return True
            if key in ("r", "R") and self.options[self._cursor] != "+ create new":
                self._action_cursor = 1
                self._renaming = True
                self._rename_text = self.options[self._cursor]
                return True
            if key in ("\r", "\n", " "):
                if self.options[self._cursor] == "+ create new":
                    if self.on_create:
                        self.on_create()
                elif self._action_cursor == 1:
                    self._renaming = True
                    self._rename_text = self.options[self._cursor]
                elif self._action_cursor == 2 and self.on_duplicate:
                    self.on_duplicate(self.options[self._cursor])
                elif self._action_cursor == 3 and self.on_delete:
                    self.on_delete(self.options[self._cursor])
                else:
                    self.set_value(self._cursor)
                return True
        if isinstance(event, MouseEvent) and event.pressed and event.button == 0:
            row = event.y - self.y - 1
            if not 0 <= row < len(self.options):
                return False
            if self.options[row] == "+ create new":
                if self.on_create:
                    self.on_create()
            elif event.x >= self.x + self.width - 14:
                if self.on_delete:
                    self.on_delete(self.options[row])
            elif event.x >= self.x + self.width - 27:
                if self.on_duplicate:
                    self.on_duplicate(self.options[row])
            elif event.x >= self.x + self.width - 37:
                self._cursor = row
                self._action_cursor = 1
                self._renaming = True
                self._rename_text = self.options[row]
            else:
                self._cursor = row
                self._action_cursor = 0
                self.set_value(row)
            return True
        if key in ("d", "D") and self.options[self._cursor] != "+ create new":
            if self.on_duplicate:
                self.on_duplicate(self.options[self._cursor])
            return True
        if key in ("x", "X") and self.options[self._cursor] != "+ create new":
            if self.on_delete:
                self.on_delete(self.options[self._cursor])
            return True
        return super().handle_input(event)

    def handle_input_result(self, event: Any) -> InputResult:
        """Bubble vertical navigation only at the profile-list boundaries."""
        key = event.key if isinstance(event, KeyEvent) else event
        if not self._renaming and isinstance(event, (str, KeyEvent)):
            if key == "\x1b[A" and self._cursor == 0:
                return InputResult(handled=True, focus="previous")
            if key == "\x1b[B" and self._cursor == len(self.options) - 1:
                return InputResult(handled=True, focus="next")
        return super().handle_input_result(event)

    def activate(self) -> bool:
        """Activate the currently focused row or right-side action."""
        if self._renaming:
            old_name = self.options[self._cursor]
            if self.on_rename and self.on_rename(old_name, self._rename_text):
                self._renaming = False
            return True
        if self.options[self._cursor] == "+ create new":
            if self.on_create:
                self.on_create()
            return True
        name = self.options[self._cursor]
        if self._action_cursor == 1:
            self._renaming = True
            self._rename_text = name
        elif self._action_cursor == 2 and self.on_duplicate:
            self.on_duplicate(name)
        elif self._action_cursor == 3 and self.on_delete:
            self.on_delete(name)
        else:
            self.set_value(self._cursor)
        return True


class ProfileRow(Component):
    """A profile label composed with explicit action buttons."""

    def __init__(self, name: str, *, on_select=None, on_rename=None,
                 on_duplicate=None, on_remove=None):
        super().__init__()
        self.name = name
        self.selected = False
        self.external_focus_marker = False
        self._buttons = [
            Button(name, on_activate=lambda: on_select and on_select(name)),
                 Button("rename", on_activate=lambda: on_rename and on_rename(name),
                     show_brackets=False, muted_when_unfocused=True),
                 Button("duplicate", on_activate=lambda: on_duplicate and on_duplicate(name),
                     show_brackets=False, muted_when_unfocused=True),
                 Button("remove", on_activate=lambda: on_remove and on_remove(name),
                     show_brackets=False, muted_when_unfocused=True),
        ]
        for button in self._buttons:
            button.parent = self

    @property
    def buttons(self):
        return self._buttons

    def set_layout(self, x: int, y: int, width: int, height: int):
        super().set_layout(x, y, width, height)
        # The name button gets the flexible area; actions retain full labels.
        action_widths = [button.get_preferred_width() for button in self._buttons[1:]]
        action_total = sum(action_widths) + len(action_widths)
        self._buttons[0].set_layout(x, y, max(1, width - action_total), 1)
        cursor = x + max(1, width - action_total)
        for button, button_width in zip(self._buttons[1:], action_widths):
            button.set_layout(cursor, y, button_width + 1, 1)
            cursor += button_width + 1

    def render(self, buffer: Buffer):
        # Selection is intentionally rendered separately from edit actions.
        # The profile name is not a button-shaped value; it is a radio item.
        select = self._buttons[0]
        marker = "(x)" if self.selected else "( )"
        focus_marker = "▸ " if select.focused and not self.external_focus_marker else ""
        fg = theme.FOCUSED if select.focused else theme.DEFAULT
        buffer.write_str(select.x, select.y, f"{focus_marker}{marker} {self.name}",
                         fg=fg, max_width=select.width)
        separator_x = select.x + select.width
        if separator_x < self.x + self.width:
            buffer.write_str(separator_x, self.y, "│", fg=theme.MUTED, max_width=1)
        for button in self._buttons[1:]:
            button.render(buffer)

    def handle_input(self, event: Any) -> bool:
        for button in reversed(self._buttons):
            if button.handle_input(event):
                return True
        return False


class ProfileList(FormField):
    """Composable profile list with rows and a real create button.

    This is the replacement control for the legacy ``ProfileListField``.
    Selection and action focus are separate, while each visible action is a
    normal ``Button`` with shared keyboard/mouse activation semantics.
    """

    def __init__(self, label: str, *, options: List[str], value: int = 0,
                 on_select=None, on_create=None, on_rename=None,
                 on_duplicate=None, on_remove=None, **kw):
        super().__init__(label, model=kw.pop("model", None) or ChoiceFieldModel(value), **kw)
        self.options = options
        self._selected = value
        self._cursor = value
        self._action_cursor = 0
        self._renaming_index: Optional[int] = None
        self._rename_text = ""
        self._on_select = on_select
        self._on_create = on_create
        self._on_rename = on_rename
        self._on_duplicate = on_duplicate
        self._on_remove = on_remove
        self._create = Button("New profile", on_activate=self._create_profile,
                      show_brackets=False)
        self._rows: list[ProfileRow] = []
        self._rebuild_rows()

    def _rebuild_rows(self):
        self._rows = [ProfileRow(
            name,
            on_select=self._select_profile,
            on_rename=self._rename_profile,
            on_duplicate=self._duplicate_profile,
            on_remove=self._remove_profile,
        ) for name in self.options]

    def _select_profile(self, name: str):
        index = self.options.index(name)
        self.set_value(index)
        if self._on_select:
            self._on_select(name)

    def _create_profile(self):
        if self._on_create:
            self._on_create()

    def _rename_profile(self, name: str):
        self._renaming_index = self.options.index(name)
        self._cursor = self._renaming_index
        self._action_cursor = 1
        self._rename_text = name

    def _duplicate_profile(self, name: str):
        if self._on_duplicate:
            self._on_duplicate(name)

    def _remove_profile(self, name: str):
        if self._on_remove:
            self._on_remove(name)

    def get_value(self) -> str:
        return self.options[self._selected]

    def set_value(self, value):
        self._selected = max(0, min(int(value), len(self.options) - 1))
        self._cursor = self._selected
        self.model.set_value(self._selected)
        self._rebuild_rows()

    def get_preferred_height(self, width: int) -> int:
        # Label + rows + New profile + one visual separator before Settings.
        return 1 + len(self._rows) + 2

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        self._write(buffer, x, y, f"{self.focus_marker()}{self.label}:",
                    fg=_label_color(),
                    max_width=width)
        for index, row in enumerate(self._rows):
            row_y = y + index + 1
            if row_y >= y + height:
                break
            row.selected = index == self._selected
            row.external_focus_marker = self.suppress_focus_marker
            if self._renaming_index == index:
                row.name = self._rename_text
            for button in row.buttons:
                button.focused = self.focused and index == self._cursor and button is row.buttons[self._action_cursor]
            # Keep the radio controls visually nested under the profile
            # heading while leaving the action row aligned with the form.
            row.set_layout(x + 2, row_y, max(1, width - 2), 1)
            row.render(buffer)
            if self._renaming_index == index:
                row_prefix = ("▸ " if row.buttons[0].focused and not row.external_focus_marker else "")
                row_prefix += "(x) " if row.selected else "( ) "
                cursor_x = row.x + len(row_prefix) + len(self._rename_text)
                if cursor_x < row.x + row.width:
                    buffer.set(cursor_x, row.y, " ", fg=theme.DEFAULT, reverse=True)
        create_y = y + len(self._rows) + 1
        if create_y < y + height:
            self._create.focused = self.focused and self._cursor == len(self._rows)
            self._create.set_layout(x, create_y,
                                    min(width, self._create.get_preferred_width()), 1)
            self._create.render(buffer)

    def handle_input_result(self, event: Any) -> InputResult:
        key = event.key if isinstance(event, KeyEvent) else event
        last = len(self._rows)
        if self._renaming_index is not None:
            if key in ("\x1b",):
                self._renaming_index = None
                self._rename_text = ""
                return InputResult(True, redraw=True)
            if key in ("\x7f", "\b"):
                self._rename_text = self._rename_text[:-1]
                return InputResult(True, redraw=True)
            if key in ("\r", "\n", " "):
                index = self._renaming_index
                old_name = self.options[index]
                new_name = self._rename_text.strip()
                committed = bool(self._on_rename and new_name and
                                 self._on_rename(old_name, new_name))
                if committed:
                    self._renaming_index = None
                    self._rename_text = ""
                return InputResult(True, redraw=True)
            if isinstance(key, str) and len(key) == 1 and key.isprintable():
                self._rename_text += key
                return InputResult(True, redraw=True)
            return InputResult(True)
        if isinstance(event, (str, KeyEvent)):
            if key == "\x1b[A":
                if self._cursor > 0:
                    self._cursor -= 1
                    self._action_cursor = 0
                    return InputResult(True, redraw=True)
                return InputResult(True, focus="previous")
            if key == "\x1b[B":
                if self._cursor < last:
                    self._cursor += 1
                    self._action_cursor = 0
                    return InputResult(True, redraw=True)
                return InputResult(True, focus="next")
            if key in ("\x1b[D", "h") and self._cursor < last:
                self._action_cursor = max(0, self._action_cursor - 1)
                return InputResult(True, redraw=True)
            if key in ("\x1b[C", "l") and self._cursor < last:
                self._action_cursor = min(3, self._action_cursor + 1)
                return InputResult(True, redraw=True)
            if key in ("\r", "\n", " "):
                if self._cursor == last:
                    self._create.activate()
                else:
                    self._rows[self._cursor].buttons[self._action_cursor].activate()
                return InputResult(True, redraw=True)
        if isinstance(event, MouseEvent) and event.pressed and event.button == 0:
            row = event.y - self.y - 1
            if row == last:
                return InputResult.from_legacy(self._create.handle_input(event))
            if 0 <= row < last:
                self._cursor = row
                self._action_cursor = 0
                return InputResult.from_legacy(self._rows[row].handle_input(event))
        return InputResult(False)

    def handle_input(self, event: Any) -> bool:
        return self.handle_input_result(event).handled


class InlineChoiceField(FormField):
    """Compact single-line choice selector."""

    def __init__(self, label: str, *, options: List[str], value: int = 0, **kw):
        self.options = options
        self._selected = int(value)
        self._on_change = kw.pop("on_change", None)
        super().__init__(label, model=kw.pop("model", None) or FieldModel(self._selected), **kw)

    def get_value(self) -> str:
        return self.options[self._selected]

    def get_index(self) -> int:
        return self._selected

    def set_value(self, value):
        self._selected = int(value)
        self.model.set_value(self._selected)

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        marker = self.focus_marker()
        self._write(buffer, x, y, f"{marker}{self.label}:",
                    fg=_label_color() if self.focused else theme.DEFAULT, max_width=width)
        # Keep colons attached to their labels while aligning all choices at
        # one shared column when the form assigns one.
        value_column = getattr(self, "value_column", len(marker) + len(self.label) + 2)
        cursor_x = x + max(value_column, len(marker) + len(self.label) + 2)
        for index, option in enumerate(self.options):
            part = f"[{option}]" if index == self._selected else f" {option} "
            part = part.center(9)
            self._write(buffer, cursor_x, y, part,
                        fg=theme.FOCUSED if index == self._selected else theme.MUTED,
                        max_width=max(0, width - (cursor_x - x)))
            cursor_x += len(part)

    def handle_input(self, event: Any) -> bool:
        key = event.key if isinstance(event, KeyEvent) else event
        if isinstance(event, (str, KeyEvent)):
            if key in ("\x1b[D", "h"):
                new_value = max(0, self._selected - 1)
            elif key in ("\x1b[C", "l", " ", "\r", "\n"):
                new_value = (self._selected + 1) % len(self.options)
            else:
                return False
        elif isinstance(event, MouseEvent) and event.pressed and event.button == 0:
            marker = self.focus_marker()
            value_column = getattr(self, "value_column", len(marker) + len(self.label) + 2)
            option_x = self.x + max(value_column, len(marker) + len(self.label) + 2)
            new_value = None
            for index, option in enumerate(self.options):
                part = f"[{option}]" if index == self._selected else f" {option} "
                part = part.center(9)
                if option_x <= event.x < option_x + len(part):
                    new_value = index
                    break
                option_x += len(part)
            if new_value is None:
                return False
        else:
            return False
        if new_value != self._selected:
            self.set_value(new_value)
            if self._on_change:
                self._on_change(new_value)
        return True


class FormActionField(FormField):
    """Clickable/keyboard-activatable action rendered inside a form."""

    def __init__(self, label: str, on_activate: Optional[Callable[[], Any]] = None, **kw):
        super().__init__(label, **kw)
        self.on_activate = on_activate

    def get_value(self):
        return None

    def set_value(self, value):
        return None

    def render(self, buffer: Buffer, x: int, y: int, width: int, height: int):
        text = f"[ {self.label} ]"
        button_x = x + max(0, (width - len(text)) // 2)
        self._write(buffer, button_x, y, text,
                fg=theme.FOCUSED if self.focused else theme.WARNING,
                reverse=self.focused, max_width=width)

    def handle_input(self, event: Any) -> bool:
        key = event.key if isinstance(event, KeyEvent) else event
        activated = (
            isinstance(event, (str, KeyEvent)) and key in (" ", "\r", "\n")
        ) or (
            isinstance(event, MouseEvent) and event.pressed and event.button == 0
            and self.x <= event.x < self.x + self.width
            and self.y <= event.y < self.y + self.height
        )
        if activated and self.on_activate:
            self.on_activate()
        return activated

    def activate(self) -> bool:
        if self.on_activate:
            self.on_activate()
        return True


# Public compositional names.  These are intentionally aliases for now so
# existing callers keep the established FormField API while new forms can
# describe their structure in terms of selectors and buttons.
HorizontalSelector = InlineChoiceField
ButtonField = FormActionField


# ────────────────────────────────────────────────────────────────
# FormContainer — vertical layout of fields
# ────────────────────────────────────────────────────────────────

class FormContainer(Component):
    """Manages vertical layout, focus, and input routing for a list of fields."""

    def __init__(self, fields: List[FormField], id: Optional[str] = None, field_spacing: int = 1):
        super().__init__(id)
        self.fields = fields
        self.field_spacing = field_spacing
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

    def activate_focused(self) -> bool:
        """Activate the focused actionable field without changing focus."""
        field = self.get_focused_field()
        if field is None:
            return False
        activated = field.activate()
        if activated:
            self.mark_changed()
        return activated

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
                y += self.field_spacing
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
        # Fields such as profile lists may add/remove rows in response to an
        # action.  Rebuild offsets before every paint so following fields never
        # render at stale positions.
        self._compute_layout()
        self._ensure_focus_visible()
        for i, field in enumerate(self.fields):
            fy = self._field_offsets[i] - self._scroll_offset
            fh = self._field_heights[i]
            if fy + fh <= 0 or fy >= self.height:
                continue
            clipped_h = min(fh, self.height - fy)
            if clipped_h <= 0:
                continue
            indent = getattr(field, "indent", 0)
            field.x = self.x + indent
            field.y = self.y + fy
            field.width = max(1, self.width - indent)
            field.height = fh
            field.render(buffer, field.x, self.y + fy, field.width, clipped_h)

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
            if key in ("\r", "\n", " "):
                if self.activate_focused():
                    return True

        result = field.handle_input_result(event)
        if result.focus == "next":
            self.focus_next()
            return True
        if result.focus == "previous":
            self.focus_prev()
            return True
        if result.handled:
            if result.redraw:
                self.mark_changed()  # field changed → re-render
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
