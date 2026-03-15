import re
from abc import ABC, abstractmethod
from typing import Optional, Any
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.layout_utils import display_width, wrap_text, strip_ansi

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
    def __init__(self, text: str, id: Optional[str] = None, fg=None, bg=None, auto_scroll_bottom: bool = False):
        super().__init__(id)
        self.text = text
        self.fg = fg
        self.bg = bg
        self.auto_scroll_bottom = auto_scroll_bottom

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

    def _get_lines(self) -> list[str]:
        """Wrap text into lines based on current width."""
        prompt_width = display_width(self.prompt)
        available_width = self.width
        
        if available_width <= prompt_width:
            return [""] # Too narrow
            
        full_text = self.text
        # Use our new wrap_text utility
        wrapped = wrap_text(full_text, available_width, padding_width=0, first_line_padding=False)
        lines = wrapped.split('\n')
        return lines

    def get_preferred_height(self, width: int) -> int:
        """Calculate height needed for wrapped text."""
        prompt_width = display_width(self.prompt)
        if width <= prompt_width:
            return 1
            
        wrapped = wrap_text(self.text, width, padding_width=0, first_line_padding=False)
        return len(wrapped.split('\n'))

    def render(self, buffer: Buffer):
        """Render the input field with prompt and text."""
        lines = self._get_lines()
        
        # We need to re-calculate cursor position based on lines
        # Basically repeat the wrapping logic but stop at cursor_pos
        curr_r = 0
        curr_c = display_width(self.prompt)
        for i in range(self.cursor_pos):
            char = self.text[i]
            if char == '\n':
                curr_r += 1
                curr_c = 0
                continue
            
            w = display_width(char)
            if curr_c + w > self.width:
                curr_r += 1
                curr_c = w
            else:
                curr_c += w
        
        cursor_row = curr_r
        cursor_col = curr_c

        for i, line in enumerate(lines):
            if i >= self.height:
                break
            
            display_line = ""
            if i == 0:
                display_line = self.prompt + line
            else:
                display_line = line
                
            buffer.write_str(self.x, self.y + i, display_line, fg=self.fg, bg=self.bg, max_width=self.width)
        
        # Set hardware cursor position in buffer
        if 0 <= cursor_row < self.height:
            buffer.set_cursor(self.x + cursor_col, self.y + cursor_row)

    def handle_input(self, event: Any) -> bool:
        """Handle keyboard input for the text field."""
        if isinstance(event, str):
            # Key constants
            KEY_ENTER = '\r'
            KEY_NEWLINE = '\n'
            KEY_BACKSPACE = '\x7f'
            
            # 1. SPECIAL COMBINATIONS
            
            # Ctrl+Left (Word back)
            if event == '\x1b[1;5D':
                if self.cursor_pos > 0:
                    i = self.cursor_pos - 1
                    while i > 0 and self.text[i-1].isspace(): i -= 1
                    while i > 0 and not self.text[i-1].isspace(): i -= 1
                    self.cursor_pos = i
                return True
                
            # Ctrl+Right (Word forward)
            if event == '\x1b[1;5C':
                if self.cursor_pos < len(self.text):
                    i = self.cursor_pos
                    while i < len(self.text) and self.text[i].isspace(): i += 1
                    while i < len(self.text) and not self.text[i].isspace(): i += 1
                    self.cursor_pos = i
                return True

            # Ctrl+W (Delete word back) or Ctrl+Backspace (\x1b\x7f or \x08)
            if event in ('\x17', '\x1b\x7f', '\x08'):
                if self.cursor_pos > 0:
                    i = self.cursor_pos
                    while i > 0 and self.text[i-1].isspace(): i -= 1
                    while i > 0 and not self.text[i-1].isspace(): i -= 1
                    self.text = self.text[:i] + self.text[self.cursor_pos:]
                    self.cursor_pos = i
                return True

            # Alt+Enter (\x1b\r) or Ctrl+Enter/Ctrl+J (\x0a) -> Newline
            if event in ('\x1b\r', '\x0a'):
                self.text = self.text[:self.cursor_pos] + "\n" + self.text[self.cursor_pos:]
                self.cursor_pos += 1
                return True

            # Regular Enter -> Submit
            if event == KEY_ENTER or event == KEY_NEWLINE:
                if self.on_submit and self.text.strip():
                    self.on_submit(self.text)
                    self.text = ""
                    self.cursor_pos = 0
                return True
            
            # 2. STANDARD KEYS
            
            if event == KEY_BACKSPACE:
                if self.cursor_pos > 0:
                    self.text = self.text[:self.cursor_pos-1] + self.text[self.cursor_pos:]
                    self.cursor_pos -= 1
                return True
            
            # Arrow Keys
            if event == '\x1b[D': # Left
                self.cursor_pos = max(0, self.cursor_pos - 1)
                return True
            if event == '\x1b[C': # Right
                self.cursor_pos = min(len(self.text), self.cursor_pos + 1)
                return True
            
            if event == '\x1b[A': # Up
                curr_r, curr_c = 0, display_width(self.prompt)
                for i in range(self.cursor_pos):
                    char = self.text[i]
                    if char == '\n': curr_r += 1; curr_c = 0; continue
                    w = display_width(char); curr_c += w
                    if curr_c > self.width: curr_r += 1; curr_c = w
                
                if curr_r > 0:
                    target_row, target_col = curr_r - 1, curr_c
                    new_pos, r, c = 0, 0, display_width(self.prompt)
                    for i, char in enumerate(self.text):
                        if r == target_row and c >= target_col: break
                        new_pos = i + 1
                        if char == '\n': r += 1; c = 0; continue
                        w = display_width(char); c += w
                        if c > self.width: r += 1; c = w
                    self.cursor_pos = new_pos
                return True
                
            if event == '\x1b[B': # Down
                curr_r, curr_c = 0, display_width(self.prompt)
                for i in range(self.cursor_pos):
                    char = self.text[i]
                    if char == '\n': curr_r += 1; curr_c = 0; continue
                    w = display_width(char); curr_c += w
                    if curr_c > self.width: curr_r += 1; curr_c = w
                
                target_row, target_col = curr_r + 1, curr_c
                new_pos, r, c = 0, 0, display_width(self.prompt)
                for i, char in enumerate(self.text):
                    if r == target_row and c >= target_col: break
                    new_pos = i + 1
                    if char == '\n': r += 1; c = 0; continue
                    w = display_width(char); c += w
                    if c > self.width: r += 1; c = w
                self.cursor_pos = new_pos
                return True
            
            # Default: insert character
            if len(event) == 1 and ord(event) >= 32:
                self.text = self.text[:self.cursor_pos] + event + self.text[self.cursor_pos:]
                self.cursor_pos += 1
                return True
        return False
        return False

    def update(self, text: str):
        """Update the input field text programmatically."""
        self.text = text
        self.cursor_pos = len(text)

    def clear(self):
        """Clear the input field."""
        self.text = ""
        self.cursor_pos = 0
