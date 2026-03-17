from typing import Optional, Any
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.terminal import MouseEvent

class Box(Component):
    def __init__(self, child: Component, title: str = "", id: Optional[str] = None, bg=None, fg=None):
        super().__init__(id)
        self.child = child
        self.child.parent = self
        self.title = title
        self.bg = bg
        self.fg = fg

    @property
    def children(self):
        return [self.child]

    def set_layout(self, x: int, y: int, width: int, height: int):
        super().set_layout(x, y, width, height)
        self.child.set_layout(x + 1, y + 1, width - 2, height - 2)

    def get_preferred_height(self, width: int) -> int:
        """Box adds 2 rows of height for borders (top/bottom)."""
        if hasattr(self.child, 'get_preferred_height'):
            # Height of child inside the box plus top/bottom borders.
            # Child's width inside box is box_width - 2.
            inner_height = self.child.get_preferred_height(width - 2)
            return inner_height + 2
        # Otherwise fall back to a reasonable default or 0
        return 0

    def render(self, buffer: Buffer):
        """
        Renders a box with borders and an optional title.
        Implements a 'painter's algorithm' approach to ensure visual integrity:
        1. Top + Left borders are drawn first.
        2. Background is filled (if provided).
        3. Child content is rendered.
        4. Bottom + Right borders are drawn LAST to overwrite any content overflow.
        All drawing uses absolute coordinates.
        """
        if self.width < 2 or self.height < 2:
            return

        # 1. Top + Left borders
        # Top border (excluding right corner)
        buffer.set(self.x, self.y, "┌", fg=self.fg)
        for i in range(1, self.width - 1):
            buffer.set(self.x + i, self.y, "─", fg=self.fg)
        
        # Left border (excluding bottom corner)
        for i in range(1, self.height - 1):
            buffer.set(self.x, self.y + i, "│", fg=self.fg)

        # 2. Background (optional)
        if self.bg:
            for iy in range(1, self.height - 1):
                for ix in range(1, self.width - 1):
                    buffer.set(self.x + ix, self.y + iy, " ", bg=self.bg)

        # 3. Content (child components)
        # Content is rendered before right/bottom borders so borders can constrain it.
        self.child.render(buffer)

        # 4. Bottom + Right borders (overwrites any content overflow)
        # Right border
        for i in range(1, self.height - 1):
            buffer.set(self.x + self.width - 1, self.y + i, "│", fg=self.fg)
        
        # Bottom border
        for i in range(1, self.width - 1):
            buffer.set(self.x + i, self.y + self.height - 1, "─", fg=self.fg)

        # Corners
        buffer.set(self.x + self.width - 1, self.y, "┐", fg=self.fg)
        buffer.set(self.x, self.y + self.height - 1, "└", fg=self.fg)
        buffer.set(self.x + self.width - 1, self.y + self.height - 1, "┘", fg=self.fg)

        # Title (on top of top border)
        if self.title:
            title_str = f" {self.title[:self.width-4]} "
            buffer.write_str(self.x + 2, self.y, title_str, fg=self.fg)

    def handle_input(self, event: Any) -> bool:
        """Pass input to child, but check mouse bounds for the box area."""
        if isinstance(event, MouseEvent):
            if self.x <= event.x < self.x + self.width and \
               self.y <= event.y < self.y + self.height:
                return self.child.handle_input(event)
            return False
        return self.child.handle_input(event)
