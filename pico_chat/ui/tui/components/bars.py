from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import RGB, theme
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.events import KeyEvent, MouseEvent


@dataclass(frozen=True)
class BarStyle:
    """Shared visual defaults for one-line status and action bars."""

    fg: RGB
    bg: Optional[RGB]
    focused_fg: RGB
    padding: int = 1

    @classmethod
    def default(cls) -> "BarStyle":
        return cls(theme.DEFAULT, theme.get_bg(), theme.FOCUSED)


class StatusBar(Component):
    """One-line status display with left and right aligned text."""

    def __init__(self, left: str = "", right: str = "", *, style: Optional[BarStyle] = None,
                 id: Optional[str] = None):
        super().__init__(id)
        self.left = left
        self.right = right
        self.style = style or BarStyle.default()

    def get_preferred_height(self, width: int) -> int:
        return 1

    def set_text(self, left: str, right: Optional[str] = None):
        self.left = left
        if right is not None:
            self.right = right
        self.mark_changed()

    def render(self, buffer: Buffer):
        if self.width <= 0 or self.height <= 0:
            return
        buffer.fill(self.x, self.y, self.width, 1, " ", bg=self.style.bg)
        left = self.left[:max(0, self.width - self.style.padding * 2)]
        right = self.right[:max(0, self.width - self.style.padding * 2)]
        buffer.write_str(self.x + self.style.padding, self.y, left,
                         fg=self.style.fg, bg=self.style.bg, max_width=self.width)
        if right:
            right_x = self.x + max(self.style.padding, self.width - self.style.padding - len(right))
            buffer.write_str(right_x, self.y, right, fg=self.style.fg,
                             bg=self.style.bg, max_width=self.width - (right_x - self.x))


@dataclass(frozen=True)
class ActionItem:
    key: str
    label: str
    callback: Optional[Callable[[], Any]] = None


class ActionBar(Component):
    """One-line keyboard and mouse action bar."""

    focusable = True

    def __init__(self, actions: Sequence[ActionItem] = (), *, style: Optional[BarStyle] = None,
                 id: Optional[str] = None):
        super().__init__(id)
        self.actions = list(actions)
        self.style = style or BarStyle.default()
        self.enabled = True
        self.focused = False
        self._hit_regions: list[tuple[int, int, ActionItem]] = []

    def set_focused(self, focused: bool):
        if self.focused != focused:
            self.focused = focused
            self.mark_changed()

    def get_preferred_height(self, width: int) -> int:
        return 1

    def set_actions(self, actions: Sequence[ActionItem]):
        self.actions = list(actions)
        self._hit_regions = []
        self.mark_changed()

    def _activate(self, item: ActionItem) -> bool:
        if not self.enabled:
            return False
        if item.callback is not None:
            item.callback()
        return True

    def handle_input(self, event: Any) -> bool:
        if not self.enabled:
            return False
        if isinstance(event, (str, KeyEvent)):
            key = event.key if isinstance(event, KeyEvent) else event
            for item in self.actions:
                if key.lower() == item.key.lower():
                    return self._activate(item)
        if isinstance(event, MouseEvent) and event.pressed and event.button == 0:
            for start, end, item in self._hit_regions:
                if start <= event.x < end and self.y <= event.y < self.y + self.height:
                    return self._activate(item)
        return False

    def render(self, buffer: Buffer):
        if self.width <= 0 or self.height <= 0:
            return
        self._hit_regions = []
        buffer.fill(self.x, self.y, self.width, 1, " ", bg=self.style.bg)
        x = self.x + self.style.padding
        for index, item in enumerate(self.actions):
            text = f"[{item.key}] {item.label}"
            if x >= self.x + self.width:
                break
            end = min(self.x + self.width, x + len(text))
            self._hit_regions.append((x, end, item))
            buffer.write_str(x, self.y, text,
                             fg=self.style.focused_fg if self.focused else self.style.fg,
                             bg=self.style.bg, reverse=self.focused,
                             max_width=end - x)
            x = end + self.style.padding