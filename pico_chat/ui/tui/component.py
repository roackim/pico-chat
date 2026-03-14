import re
from abc import ABC, abstractmethod
from typing import Optional, Any
from pico_chat.ui.tui.buffer import Buffer

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(s: str) -> str:
    return ANSI_ESCAPE.sub('', s)

class Component(ABC):
    def __init__(self, id: Optional[str] = None):
        self.id = id
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.parent: Optional['Component'] = None

    def set_layout(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    @abstractmethod
    def render(self, buffer: Buffer):
        pass

    def handle_input(self, event: Any) -> bool:
        """Return True if event was handled."""
        return False

    def update(self, data: Any):
        """Update component state with new data."""
        pass

class TextComponent(Component):
    def __init__(self, text: str, id: Optional[str] = None, fg=None, bg=None):
        super().__init__(id)
        self.text = text
        self.fg = fg
        self.bg = bg

    def render(self, buffer: Buffer):
        """
        Renders text lines with ANSI-aware clipping.
        Uses Buffer.write_str which handles absolute positioning and ensures
        ANSI sequences don't corrupt the grid layout.
        """
        lines = self.text.splitlines()
        for i, line in enumerate(lines):
            if i < self.height:
                buffer.write_str(self.x, self.y + i, line, fg=self.fg, bg=self.bg, max_width=self.width)

    def update(self, text: str):
        self.text = text

class Box(Component):
    def __init__(self, child: Component, title: str = "", id: Optional[str] = None, bg=None):
        super().__init__(id)
        self.child = child
        self.child.parent = self
        self.title = title
        self.bg = bg

    @property
    def children(self):
        return [self.child]

    def set_layout(self, x: int, y: int, width: int, height: int):
        super().set_layout(x, y, width, height)
        self.child.set_layout(x + 1, y + 1, width - 2, height - 2)

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
        buffer.set(self.x, self.y, "┌")
        for i in range(1, self.width - 1):
            buffer.set(self.x + i, self.y, "─")
        
        # Left border (excluding bottom corner)
        for i in range(1, self.height - 1):
            buffer.set(self.x, self.y + i, "│")

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
            buffer.set(self.x + self.width - 1, self.y + i, "│")
        
        # Bottom border
        for i in range(1, self.width - 1):
            buffer.set(self.x + i, self.y + self.height - 1, "─")

        # Corners
        buffer.set(self.x + self.width - 1, self.y, "┐")
        buffer.set(self.x, self.y + self.height - 1, "└")
        buffer.set(self.x + self.width - 1, self.y + self.height - 1, "┘")

        # Title (on top of top border)
        if self.title:
            title_str = f" {self.title[:self.width-4]} "
            buffer.write_str(self.x + 2, self.y, title_str)

    def handle_input(self, event) -> bool:
        return self.child.handle_input(event)

class InputComponent(Component):
    def __init__(self, prompt: str = "> ", id: Optional[str] = None, fg=None, bg=None):
        super().__init__(id)
        self.prompt = prompt
        self.text = ""
        self.fg = fg
        self.bg = bg
        self.on_submit = None  # Callback for when enter is pressed
        self.cursor_pos = 0

    def render(self, buffer: Buffer):
        """Render the input field with prompt and text."""
        display_text = self.prompt + self.text
        if self.height > 0:
            # Show cursor at the end
            cursor_display = display_text + "█"
            buffer.write_str(self.x, self.y, cursor_display, fg=self.fg, bg=self.bg, max_width=self.width)

    def handle_input(self, event: Any) -> bool:
        """Handle keyboard input for the text field."""
        if isinstance(event, str):
            if event == '\r' or event == '\n':  # Enter key
                if self.on_submit and self.text.strip():
                    self.on_submit(self.text)
                    self.text = ""
                    self.cursor_pos = 0
                return True
            elif event == '\x7f':  # Backspace
                if self.text:
                    self.text = self.text[:-1]
                    self.cursor_pos = len(self.text)
                return True
            elif len(event) == 1 and event.isprintable():
                self.text += event
                self.cursor_pos = len(self.text)
                return True
        return False

    def update(self, text: str):
        """Update the input field text programmatically."""
        self.text = text
        self.cursor_pos = len(text)

    def clear(self):
        """Clear the input field."""
        self.text = ""
        self.cursor_pos = 0
