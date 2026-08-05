"""Reusable text editing components for forms and small UI controls."""

import time
from typing import Any, Optional

from pico_chat import pico_cfg
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.events import KeyEvent, PasteEvent, TickEvent


class _CursorBlink:
    def __init__(self):
        self.visible = True
        self._last_input = 0.0
        self._last_blink = 0.0

    def mark_input(self):
        self._last_input = time.time()
        self.visible = True

    def tick(self) -> None:
        now = time.time()
        pulse = getattr(pico_cfg.config, "ui_cursor_pulse_delay", 0.5)
        interval = getattr(pico_cfg.config, "ui_cursor_blink_interval", 0.5)
        if now - self._last_input < pulse:
            self.visible = True
        elif now - self._last_blink >= interval:
            self._last_blink = now
            self.visible = not self.visible


class LineInput(Component):
    """A reusable single-line editor with placeholder and cursor rendering."""

    def __init__(self, value: str = "", placeholder: str = "", id: Optional[str] = None):
        super().__init__(id)
        self.value = value
        self.placeholder = placeholder
        self.cursor_pos = len(value)
        self.focused = False
        self._blink = _CursorBlink()

    def get_value(self) -> str:
        return self.value

    def set_value(self, value: str):
        self.value = str(value)
        self.cursor_pos = len(self.value)
        self.mark_changed()

    def set_focused(self, focused: bool):
        if self.focused == focused:
            return
        self.focused = focused
        if focused:
            self._blink.mark_input()
        self.mark_changed()

    def render(self, buffer: Buffer):
        # Clear the allocated row first.  Pasting newlines can make the value
        # shorter on a subsequent edit; without clearing, old spaces/chars
        # remain visible beyond the new value.
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=theme.get_bg())
        text = self.value if self.value else self.placeholder
        fg = theme.DEFAULT if self.value else theme.MUTED
        buffer.write_str(self.x, self.y, text, fg=fg, max_width=self.width)
        if self.focused:
            self._blink.tick()
            if self._blink.visible and self.width > 0:
                cursor_x = self.x + min(self.cursor_pos, len(self.value))
                if cursor_x < self.x + self.width:
                    char = self.value[self.cursor_pos] if self.cursor_pos < len(self.value) else " "
                    buffer.set(cursor_x, self.y, char, reverse=True)

    def handle_input(self, event: Any) -> bool:
        if isinstance(event, PasteEvent):
            pasted = event.text.replace("\r\n", "\n").replace("\r", "\n")
            self.value = self.value[:self.cursor_pos] + pasted + self.value[self.cursor_pos:]
            self.cursor_pos += len(pasted)
            self._blink.mark_input()
            self.mark_changed()
            return True
        if isinstance(event, TickEvent):
            before = self._blink.visible
            self._blink.tick()
            if before != self._blink.visible:
                self.mark_changed()
            return before != self._blink.visible
        if not isinstance(event, (KeyEvent, str)):
            return False
        key = event.key if isinstance(event, KeyEvent) else event
        text = event.text if isinstance(event, KeyEvent) else event
        handled = False
        if key in ("\x1b[1;5D", "\x1b[5D"):
            old = self.cursor_pos
            while self.cursor_pos > 0 and self.value[self.cursor_pos - 1].isspace():
                self.cursor_pos -= 1
            while self.cursor_pos > 0 and not self.value[self.cursor_pos - 1].isspace():
                self.cursor_pos -= 1
            handled = self.cursor_pos != old
        elif key in ("\x1b[1;5C", "\x1b[5C"):
            old = self.cursor_pos
            while self.cursor_pos < len(self.value) and self.value[self.cursor_pos].isspace():
                self.cursor_pos += 1
            while self.cursor_pos < len(self.value) and not self.value[self.cursor_pos].isspace():
                self.cursor_pos += 1
            handled = self.cursor_pos != old
        elif key in ("\x17", "\x08", "\x1b\x7f"):
            old = self.cursor_pos
            while self.cursor_pos > 0 and self.value[self.cursor_pos - 1].isspace():
                self.cursor_pos -= 1
            while self.cursor_pos > 0 and not self.value[self.cursor_pos - 1].isspace():
                self.cursor_pos -= 1
            self.value = self.value[:self.cursor_pos] + self.value[old:]
            handled = self.cursor_pos != old
        elif key == "\x1b[D" and self.cursor_pos > 0:
            self.cursor_pos -= 1
            handled = True
        elif key == "\x1b[C" and self.cursor_pos < len(self.value):
            self.cursor_pos += 1
            handled = True
        elif key == "\x1b[H":
            self.cursor_pos = 0
            handled = True
        elif key == "\x1b[F":
            self.cursor_pos = len(self.value)
            handled = True
        elif key == "\x7f" and self.cursor_pos > 0:
            self.value = self.value[:self.cursor_pos - 1] + self.value[self.cursor_pos:]
            self.cursor_pos -= 1
            handled = True
        elif key == "\x1b[3~" and self.cursor_pos < len(self.value):
            self.value = self.value[:self.cursor_pos] + self.value[self.cursor_pos + 1:]
            handled = True
        elif text is not None and len(text) == 1 and text.isprintable():
            self.value = self.value[:self.cursor_pos] + text + self.value[self.cursor_pos:]
            self.cursor_pos += 1
            handled = True
        if handled:
            self._blink.mark_input()
            self.mark_changed()
        return handled


class BoxInput(Component):
    """A reusable multiline editor rendered inside its allocated rectangle."""

    def __init__(self, value: str = "", placeholder: str = "", id: Optional[str] = None):
        super().__init__(id)
        self.value = value
        self.placeholder = placeholder
        self.cursor_row = 0
        self.cursor_col = 0
        self.focused = False
        self._blink = _CursorBlink()

    def get_value(self) -> str:
        return self.value

    def set_value(self, value: str):
        self.value = str(value)
        self.cursor_row = self.cursor_col = 0
        self.mark_changed()

    def set_focused(self, focused: bool):
        if self.focused == focused:
            return
        self.focused = focused
        if focused:
            self._blink.mark_input()
        self.mark_changed()

    def _lines(self):
        return self.value.split("\n") if self.value else [""]

    def _flat_cursor(self) -> int:
        return sum(len(line) + 1 for line in self._lines()[:self.cursor_row]) + self.cursor_col

    def _set_flat_cursor(self, position: int) -> None:
        lines = self._lines()
        position = max(0, min(position, len(self.value)))
        offset = 0
        for row, line in enumerate(lines):
            if position <= offset + len(line):
                self.cursor_row = row
                self.cursor_col = position - offset
                return
            offset += len(line) + 1
        self.cursor_row = len(lines) - 1
        self.cursor_col = len(lines[-1])

    def render(self, buffer: Buffer):
        # Clear all allocated rows before drawing.  This is important when a
        # multiline paste leaves empty lines or removes content: rendering
        # only the new lines cannot erase cells from the previous frame.
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=theme.get_bg())
        lines = self._lines()
        for row, line in enumerate(lines):
            if row >= self.height:
                break
            buffer.write_str(self.x, self.y + row, line if self.value else self.placeholder,
                             fg=theme.DEFAULT if self.value else theme.MUTED,
                             max_width=self.width)
        if self.focused:
            self._blink.tick()
            if self._blink.visible:
                row = min(self.cursor_row, len(lines) - 1)
                col = min(self.cursor_col, len(lines[row]))
                if self.y + row < self.y + self.height and self.x + col < self.x + self.width:
                    char = lines[row][col] if col < len(lines[row]) else " "
                    buffer.set(self.x + col, self.y + row, char, reverse=True)

    def handle_input(self, event: Any) -> bool:
        if isinstance(event, PasteEvent):
            pasted = event.text.replace("\r\n", "\n").replace("\r", "\n")
            position = self._flat_cursor()
            self.value = self.value[:position] + pasted + self.value[position:]
            self._set_flat_cursor(position + len(pasted))
            self._blink.mark_input()
            self.mark_changed()
            return True
        if isinstance(event, TickEvent):
            before = self._blink.visible
            self._blink.tick()
            if before != self._blink.visible:
                self.mark_changed()
            return before != self._blink.visible
        if not isinstance(event, (KeyEvent, str)):
            return False
        key = event.key if isinstance(event, KeyEvent) else event
        text = event.text if isinstance(event, KeyEvent) else event
        lines = self._lines()
        handled = False
        if key in ("\x17", "\x08", "\x1b\x7f"):
            position = self._flat_cursor()
            target = position
            while target > 0 and self.value[target - 1].isspace():
                target -= 1
            while target > 0 and not self.value[target - 1].isspace():
                target -= 1
            self.value = self.value[:target] + self.value[position:]
            self._set_flat_cursor(target)
            handled = target != position
        elif key in ("\x1b[1;5D", "\x1b[5D", "\x1b[1;5C", "\x1b[5C"):
            position = self._flat_cursor()
            if key in ("\x1b[1;5D", "\x1b[5D"):
                while position > 0 and self.value[position - 1].isspace():
                    position -= 1
                while position > 0 and not self.value[position - 1].isspace():
                    position -= 1
            else:
                while position < len(self.value) and self.value[position].isspace():
                    position += 1
                while position < len(self.value) and not self.value[position].isspace():
                    position += 1
            self._set_flat_cursor(position)
            handled = True
        elif key in ("\r", "\n"):
            line = lines[self.cursor_row]
            lines[self.cursor_row:self.cursor_row + 1] = [line[:self.cursor_col], line[self.cursor_col:]]
            self.value = "\n".join(lines)
            self.cursor_row += 1
            self.cursor_col = 0
            handled = True
        elif key == "\x1b[A" and self.cursor_row > 0:
            self.cursor_row -= 1
            self.cursor_col = min(self.cursor_col, len(lines[self.cursor_row]))
            handled = True
        elif key == "\x1b[B" and self.cursor_row < len(lines) - 1:
            self.cursor_row += 1
            self.cursor_col = min(self.cursor_col, len(lines[self.cursor_row]))
            handled = True
        elif key == "\x1b[H":
            self.cursor_col = 0
            handled = True
        elif key == "\x1b[F":
            self.cursor_col = len(lines[self.cursor_row])
            handled = True
        elif key == "\x1b[D":
            if self.cursor_col > 0:
                self.cursor_col -= 1
            elif self.cursor_row > 0:
                self.cursor_row -= 1
                self.cursor_col = len(lines[self.cursor_row])
            else:
                return False
            handled = True
        elif key == "\x1b[C":
            if self.cursor_col < len(lines[self.cursor_row]):
                self.cursor_col += 1
            elif self.cursor_row < len(lines) - 1:
                self.cursor_row += 1
                self.cursor_col = 0
            else:
                return False
            handled = True
        elif key == "\x7f":
            if self.cursor_col > 0:
                line = lines[self.cursor_row]
                lines[self.cursor_row] = line[:self.cursor_col - 1] + line[self.cursor_col:]
                self.cursor_col -= 1
            elif self.cursor_row > 0:
                self.cursor_col = len(lines[self.cursor_row - 1])
                lines[self.cursor_row - 1] += lines[self.cursor_row]
                del lines[self.cursor_row]
                self.cursor_row -= 1
            else:
                return False
            self.value = "\n".join(lines)
            handled = True
        elif key == "\x1b[3~":
            line = lines[self.cursor_row]
            if self.cursor_col < len(line):
                lines[self.cursor_row] = line[:self.cursor_col] + line[self.cursor_col + 1:]
            elif self.cursor_row < len(lines) - 1:
                lines[self.cursor_row] += lines[self.cursor_row + 1]
                del lines[self.cursor_row + 1]
            else:
                return False
            self.value = "\n".join(lines)
            handled = True
        elif text is not None and len(text) == 1 and text.isprintable():
            line = lines[self.cursor_row]
            lines[self.cursor_row] = line[:self.cursor_col] + text + line[self.cursor_col:]
            self.value = "\n".join(lines)
            self.cursor_col += 1
            handled = True
        if handled:
            self._blink.mark_input()
            self.mark_changed()
        return handled