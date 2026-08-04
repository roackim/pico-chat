from typing import Any, Callable, Optional

from pico_chat.ui.tui.actions import Action, Actions
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.events import KeyEvent, MouseEvent


class Button(Component):
    """Focusable button activated by Enter, Space, or a mouse click."""

    focusable = True

    def __init__(self, label: str, on_activate: Optional[Callable[[], Any]] = None,
                 action_sink: Optional[Callable[[Action], bool]] = None,
                 id: Optional[str] = None):
        super().__init__(id)
        self.label = label
        self.enabled = True
        self.focused = False
        self.on_activate = on_activate
        self.action_sink = action_sink

    def set_focused(self, focused: bool):
        if self.focused != focused:
            self.focused = focused
            self.mark_changed()

    def get_preferred_width(self) -> int:
        return len(self.label) + 4

    def get_preferred_height(self, width: int) -> int:
        return 1

    def _activate(self) -> bool:
        if not self.enabled:
            return False
        if self.action_sink is not None and self.action_sink(Action(Actions.ACTIVATE, self.id)):
            return True
        if self.on_activate is not None:
            self.on_activate()
        return True

    def handle_input(self, event: Any) -> bool:
        if not self.enabled:
            return False
        key = event.key if isinstance(event, KeyEvent) else event
        if isinstance(event, (str, KeyEvent)) and key in ("\r", "\n", " "):
            return self._activate()
        if isinstance(event, MouseEvent) and event.pressed and event.button == 0:
            if self.x <= event.x < self.x + self.width and self.y <= event.y < self.y + self.height:
                return self._activate()
        return False

    def render(self, buffer: Buffer):
        if self.width <= 0 or self.height <= 0:
            return
        text = f"[ {self.label} ]"
        fg = theme.FOCUSED if self.focused else theme.DEFAULT
        if not self.enabled:
            fg = theme.MUTED
        buffer.write_str(self.x, self.y, text, fg=fg, bg=theme.get_bg(),
                         reverse=self.focused and self.enabled, max_width=self.width)