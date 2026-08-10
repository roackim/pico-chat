"""Chat workspace screen composition."""

from typing import Any

from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.components.tab_bar import TabBar
from pico_chat.ui.tui.components.bars import StatusBar
from pico_chat.ui.tui.container import Content, Hsplit
from pico_chat.ui.tui.focus import FocusScope
from pico_chat.ui.tui.screen import Screen


class _ChatWorkspace(Hsplit):
    """Workspace with a compatibility-preserving status-bar slot."""

    def __init__(self, history: Component, input_box: Component, status_bar: StatusBar):
        super().__init__([history, input_box], ["100%", 0])
        self.status_bar = status_bar
        self.status_bar.parent = self

    def layout(self):
        status_height = min(1, self.height)
        content_height = max(0, self.height - status_height)
        # Mirror Hsplit.layout(): a 0 size means "use the child's preferred
        # height" (Content), not "fill". Without this the input box collapses
        # to 0 height because history takes the full 100%.
        original_sizes = self.sizes
        self.sizes = [Content() if size == 0 else size for size in original_sizes]
        content_sizes = self._calculate_actual_sizes(content_height, [
            child.get_preferred_height(self.width) if hasattr(child, "get_preferred_height") else 0
            for child in self.children
        ])
        self.sizes = original_sizes
        current_y = self.y
        for child, child_height in zip(self.children, content_sizes):
            child.set_layout(self.x, current_y, self.width, child_height)
            child.layout()
            current_y += child_height
        self.status_bar.set_layout(self.x, self.y + content_height, self.width, status_height)

    def render(self, buffer):
        super().render(buffer)
        self.status_bar.render(buffer)

    def collect_dirty_rects(self, rects):
        super().collect_dirty_rects(rects)
        self.status_bar.collect_dirty_rects(rects)

    def clear_dirty(self):
        super().clear_dirty()
        self.status_bar.clear_dirty()


class ChatScreen(Screen):
    """Own the chat workspace layout while the application owns its state."""

    def __init__(self, tab_bar: TabBar, history: Component, input_box: Component,
                 focus_scope: FocusScope, model: Any = None,
                 status_bar: StatusBar | None = None):
        self.tab_bar = tab_bar
        self.status_bar = status_bar or StatusBar()
        self.workspace = _ChatWorkspace(history, input_box, self.status_bar)
        root = Hsplit([tab_bar, self.workspace], [0, "100%"])
        super().__init__(root, focus_scope=focus_scope, model=model)