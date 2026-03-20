from typing import Optional
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer

from pico_chat.ui.tui.colors import theme

class TextComponent(Component):
    def __init__(self, text: str, id: Optional[str] = None, fg=None, bg=None, auto_scroll_bottom: bool = False):
        super().__init__(id)
        self.text = text
        self.fg = fg
        self.bg = bg
        self.auto_scroll_bottom = auto_scroll_bottom
        
        if self.fg is None: self.fg = theme.DEFAULT
        if self.bg is None: self.bg = theme.get_bg()

    def render(self, buffer: Buffer):
        """
        Renders text lines with ANSI-aware clipping.
        Uses Buffer.write_str which handles absolute positioning and ensures
        ANSI sequences don't corrupt the grid layout.
        """
        lines = self.text.splitlines()
        
        # If auto_scroll_bottom is enabled and there are more lines than height,
        # show the last lines that fit
        start_line = 0
        if self.auto_scroll_bottom and len(lines) > self.height:
            start_line = len(lines) - self.height
        
        for i in range(start_line, min(len(lines), start_line + self.height)):
            line_index = i - start_line
            buffer.write_str(self.x, self.y + line_index, lines[i], fg=self.fg, bg=self.bg, max_width=self.width)

    def get_preferred_height(self, width: int) -> int:
        """Calculate height needed for wrapped text."""
        # Note: If this TextComponent doesn't wrap itself (like ChatHistoryPanel currently does),
        # we still consider splitlines() count.
        lines = self.text.splitlines()
        return len(lines)

    def update(self, text: str):
        self.text = text
