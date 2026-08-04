from typing import Callable, Optional

from pico_chat.ui.tui.actions import Action, ActionMap, Actions
from pico_chat.ui.tui.components.button import Button
from pico_chat.ui.tui.components.text import Label
from pico_chat.ui.tui.container import Hsplit
from pico_chat.ui.tui.focus import FocusScope
from pico_chat.ui.tui.screen import Screen


class ExampleScreen(Screen):
    """Small library-only screen demonstrating composition and actions."""

    def __init__(self, on_activate: Optional[Callable[[], None]] = None):
        self.label = Label("TUI library example", horizontal="center", vertical="center")
        self.button = Button("Activate", id="activate", on_activate=on_activate)
        root = Hsplit([self.label, self.button], ["100%", 0])
        focus_scope = FocusScope([self.button])
        action_map = ActionMap()
        action_map.bind(Actions.ACTIVATE, self._activate)
        super().__init__(root, focus_scope=focus_scope, action_map=action_map)

    def _activate(self, action: Action) -> bool:
        if action.payload != self.button.id:
            return False
        return self.button._activate()
