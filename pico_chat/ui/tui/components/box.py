from dataclasses import dataclass
from typing import Optional, Any
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.terminal import MouseEvent

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme

class Box(Component):
    def __init__(self, child: Component, title: str = "", id: Optional[str] = None, bg=None, fg=None, focused: bool = False):
        super().__init__(id)
        self.child = child
        self.child.parent = self
        self.title = title
        self.bg = bg
        self.fg = fg
        self.focused = focused
        
        if self.bg is None: self.bg = theme.get_bg()
        if self.fg is None: self.fg = theme.DEFAULT

    @property
    def children(self):
        return [self.child]
    
    def set_focused(self, focused: bool):
        """Set the focused state of this box."""
        self.focused = focused

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
        fg, bg = self.fg, self.bg
        
        if self.focused:
            fg = theme.FOCUSED

        if self.width < 2 or self.height < 2:
            return


        
        @dataclass(frozen=True)
        class BorderStyle:
            tl: str  # top-left
            tr: str  # top-right
            bl: str  # bottom-left
            br: str  # bottom-right
            h: str   # horizontal
            v: str   # vertical
            
        STYLES = {
            "single":  BorderStyle("┌", "┐", "└", "┘", "─", "│"),
            "double":  BorderStyle("╔", "╗", "╚", "╝", "═", "║"),
            "ascii":   BorderStyle("+", "+", "+", "+", "-", "|"),
            "rounded": BorderStyle("╭", "╮", "╰", "╯", "─", "│"),
        }

        # Use focused style if box is focused, otherwise use normal style
        style_name = pico_cfg.config.ui_box_style_focused if self.focused else pico_cfg.config.ui_box_style
        style = STYLES[style_name]

        # 1. Top + Left borders
        buffer.set(self.x, self.y, style.tl, fg=fg, bg=bg)

        for i in range(1, self.width - 1):
            buffer.set(self.x + i, self.y, style.h, fg=fg, bg=bg)

        for i in range(1, self.height - 1):
            buffer.set(self.x, self.y + i, style.v, fg=fg, bg=bg)

        # 2. Background
        if self.bg:
            for iy in range(1, self.height - 1):
                for ix in range(1, self.width - 1):
                    buffer.set(self.x + ix, self.y + iy, " ", bg=bg)

        # 3. Content
        self.child.render(buffer)

        # 4. Bottom + Right borders
        for i in range(1, self.height - 1):
            buffer.set(self.x + self.width - 1, self.y + i, style.v, fg=fg, bg=bg)

        for i in range(1, self.width - 1):
            buffer.set(self.x + i, self.y + self.height - 1, style.h, fg=fg, bg=bg)

        # Corners
        buffer.set(self.x + self.width - 1, self.y, style.tr, fg=fg, bg=bg)
        buffer.set(self.x, self.y + self.height - 1, style.bl, fg=fg, bg=bg)
        buffer.set(self.x + self.width - 1, self.y + self.height - 1, style.br, fg=fg, bg=bg)

        # Title
        if self.title:
            title_str = f" {self.title[:self.width-4]} "
            buffer.write_str(self.x + 2, self.y, title_str, fg=fg, bg=bg)

    def handle_input(self, event: Any) -> bool:
        """Pass input to child, but check mouse bounds for the box area."""
        if isinstance(event, MouseEvent):
            if self.x <= event.x < self.x + self.width and \
               self.y <= event.y < self.y + self.height:
                return self.child.handle_input(event)
            return False
        return self.child.handle_input(event)
