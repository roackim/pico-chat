"""Chat workspace screen composition."""

from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.components.bars import StatusBar
from pico_chat.ui.tui.focus import FocusScope
from pico_chat.ui.tui.scaffold import AppScaffold
from pico_chat.ui.tui.screen import Screen


class ChatScreen(Screen):
    """Own the chat workspace layout while the application owns its state.

    Uses the shared ``AppScaffold``: history + input as the body, status bar
    pinned to the bottom.
    """

    def __init__(self, history: Component, input_box: Component,
                 focus_scope: FocusScope, status_bar: StatusBar | None = None):
        self.status_bar = status_bar or StatusBar()
        self.status_bar.parent = self
        from pico_chat.ui.tui.container import Hsplit, Content, Fill
        # History fills the body; the input box takes its preferred height.
        body = Hsplit([history, input_box], [Fill(), Content()])
        self.scaffold = AppScaffold(body, bottom=self.status_bar)
        super().__init__(self.scaffold, focus_scope=focus_scope)

    @property
    def workspace(self):
        """Compatibility alias: previously the body container itself."""
        return self.scaffold.body
