"""Chat workspace screen composition."""

from typing import Any

from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.components.tab_bar import TabBar
from pico_chat.ui.tui.container import Hsplit
from pico_chat.ui.tui.focus import FocusScope
from pico_chat.ui.tui.screen import Screen


class ChatScreen(Screen):
    """Own the chat workspace layout while the application owns its state."""

    def __init__(self, tab_bar: TabBar, history: Component, input_box: Component,
                 focus_scope: FocusScope, model: Any = None):
        self.tab_bar = tab_bar
        self.workspace = Hsplit([history, input_box], ["100%", 0])
        root = Hsplit([tab_bar, self.workspace], [0, "100%"])
        super().__init__(root, focus_scope=focus_scope, model=model)