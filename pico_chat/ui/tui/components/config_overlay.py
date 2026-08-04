"""Config panel component — rendered as a real tab in the tab bar.

Unlike a floating overlay, this component is embedded in the root layout as a
tab's content. It renders whenever it is the active tab (the app swaps it into
the layout). It supports both mouse and keyboard interaction.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.events import KeyEvent, MouseEvent
from pico_chat.ui.tui.colors import theme


class ConfigOverlay(Component):
    """A config panel rendered as a tab's content."""

    def __init__(self, id: Optional[str] = None):
        super().__init__(id)
        self.sections: List[str] = ["servers"]
        self.active_section: int = 0

        # Server list state (populated by app before show)
        self.servers: List[Dict[str, Any]] = []  # [{name, type, is_active}]
        self._scroll_offset: int = 0

        # Callbacks wired by the app
        self.on_add_server: Optional[Callable[[], None]] = None
        self.on_edit_server: Optional[Callable[[str], None]] = None
        self.on_remove_server: Optional[Callable[[str], None]] = None
        self.on_use_server: Optional[Callable[[str], None]] = None

        # Hit regions for clickable rows/buttons
        self._row_regions: List[tuple[int, int, int]] = []  # (x_start, x_end, server_index)
        self._action_regions: List[tuple[int, int, str, int]] = []  # (x_start, x_end, action, server_index)

    # ── data ──────────────────────────────────────────────────

    def set_servers(self, servers: List[Dict[str, Any]]):
        """Update the server list and request a repaint."""
        self.servers = servers
        self._scroll_offset = 0
        self.mark_changed()

    # ── input ──────────────────────────────────────────────────

    def handle_input(self, event: Any) -> bool:
        # Keyboard
        if isinstance(event, (str, KeyEvent)):
            key = event.key if isinstance(event, KeyEvent) else event
            if key == '\x1b[A':  # Up
                if self._scroll_offset > 0:
                    self._scroll_offset -= 1
                    self.mark_changed()
                return True
            elif key == '\x1b[B':  # Down
                max_scroll = self._max_scroll()
                if self._scroll_offset < max_scroll:
                    self._scroll_offset += 1
                    self.mark_changed()
                return True
            # Keyboard shortcuts for server actions
            if key == 'a':
                if self.on_add_server:
                    self.on_add_server()
                return True
            if key == 'e':
                if self.servers and self.on_edit_server:
                    self.on_edit_server(self.servers[0]["name"])
                return True
            if key == 'r':
                if self.servers and self.on_remove_server:
                    self.on_remove_server(self.servers[0]["name"])
                return True
            if key == 'u':
                if self.servers and self.on_use_server:
                    self.on_use_server(self.servers[0]["name"])
                return True
            return False

        # Mouse
        if isinstance(event, MouseEvent):
            if event.pressed and not event.drag and event.button == 0:
                # Section tab click
                if self.y <= event.y < self.y + 1:
                    for i, sec in enumerate(self.sections):
                        start = self.x + 2 + i * (len(sec) + 3)
                        end = start + len(sec)
                        if start <= event.x < end:
                            self.active_section = i
                            self.mark_changed()
                            return True
                # Server action buttons
                for x_start, x_end, action, idx in self._action_regions:
                    if x_start <= event.x < x_end and event.y == self._row_y(idx):
                        self._dispatch_action(action, idx)
                        return True
                # Server row click → select (no-op for now)
                for x_start, x_end, idx in self._row_regions:
                    if x_start <= event.x < x_end and event.y == self._row_y(idx):
                        return True
            # Mouse scroll
            if event.button == 64:  # Scroll up
                if self._scroll_offset > 0:
                    self._scroll_offset = max(0, self._scroll_offset - 3 * event.scroll_delta)
                    self.mark_changed()
                return True
            elif event.button == 65:  # Scroll down
                max_scroll = self._max_scroll()
                if self._scroll_offset < max_scroll:
                    self._scroll_offset = min(max_scroll, self._scroll_offset + 3 * event.scroll_delta)
                    self.mark_changed()
                return True

        return False

    def _row_y(self, idx: int) -> int:
        # Rows start after the section tab line (y+1) and header (y+2)
        return self.y + 3 + idx - self._scroll_offset

    def _max_scroll(self) -> int:
        # Header rows: tab line (1) + column header (1) + action hint (1)
        header = 3
        content_h = max(0, self.height - header)
        return max(0, len(self.servers) - content_h)

    def _dispatch_action(self, action: str, idx: int):
        if idx < 0 or idx >= len(self.servers):
            return
        name = self.servers[idx]["name"]
        if action == "add" and self.on_add_server:
            self.on_add_server()
        elif action == "edit" and self.on_edit_server:
            self.on_edit_server(name)
        elif action == "remove" and self.on_remove_server:
            self.on_remove_server(name)
        elif action == "use" and self.on_use_server:
            self.on_use_server(name)

    # ── render ─────────────────────────────────────────────────

    def render(self, buffer: Buffer):
        # Fill background
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=theme.get_bg())

        self._row_regions = []
        self._action_regions = []

        # Section tabs (top line)
        x = self.x + 1
        for i, sec in enumerate(self.sections):
            label = f" {sec} "
            is_active = (i == self.active_section)
            fg = theme.DEFAULT if is_active else theme.MUTED
            buffer.write_str(x, self.y, label, fg=fg, bg=None, reverse=is_active, max_width=len(label))
            x += len(label) + 1

        # Title / hint line
        buffer.write_str(self.x + 1, self.y + 1, "Config — Esc to close", fg=theme.MUTED, max_width=self.width - 2)

        if self.active_section == 0:
            self._render_servers(buffer)

    def _render_servers(self, buffer: Buffer):
        # Column header
        header_y = self.y + 2
        buffer.write_str(self.x + 1, header_y, "Servers", fg=theme.DEFAULT, max_width=self.width - 2)

        # Action hint
        hint_y = self.y + 3
        buffer.write_str(self.x + 1, hint_y,
                         "  [a] add   [e] edit   [r] remove   [u] use",
                         fg=theme.MUTED, max_width=self.width - 2)

        # Server rows
        row_y = self.y + 4
        for i, srv in enumerate(self.servers):
            y = row_y + i - self._scroll_offset
            if y < self.y + 4 or y >= self.y + self.height:
                continue

            name = srv.get("name", "?")
            stype = srv.get("type", "unknown")
            active = srv.get("is_active", False)

            marker = "●" if active else "○"
            line = f" {marker} {name}  ({stype})"
            fg = theme.DEFAULT if active else theme.MUTED
            buffer.write_str(self.x + 1, y, line, fg=fg, max_width=self.width - 2)
            self._row_regions.append((self.x + 1, self.x + 1 + len(line), i))

            # Action buttons on the right
            btn_x = self.x + self.width - 1
            for action, label in (("edit", "edit"), ("remove", "rm"), ("use", "use")):
                btn_str = f" [{label}]"
                start = btn_x - len(btn_str)
                buffer.write_str(start, y, btn_str, fg=theme.MUTED, max_width=len(btn_str))
                self._action_regions.append((start, btn_x, action, i))
                btn_x = start
