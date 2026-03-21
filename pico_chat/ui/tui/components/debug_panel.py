from collections import deque
from typing import Optional
from pico_chat.ui.tui.components.text import TextComponent
from pico_chat.ui.tui.colors import theme

class DebugLogPanel(TextComponent):
    """
    A scrolling debug log panel.
    """
    def __init__(self, max_lines: int = 1000, id: Optional[str] = None):
        super().__init__("", id=id, auto_scroll_bottom=True, fg=theme.MUTED)
        self.max_lines = max_lines
        self.lines = deque(maxlen=max_lines)
        
    def log(self, message: str):
        """Add a message to the log."""
        # Handle multiline messages
        for line in message.splitlines():
            self.lines.append(line)
        
        self.update("\n".join(self.lines))
        
    def clear(self):
        """Clear the log."""
        self.lines.clear()
        self.update("")
