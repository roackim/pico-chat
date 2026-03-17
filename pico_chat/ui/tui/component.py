import re
from abc import ABC, abstractmethod
from typing import Optional, Any
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.terminal import MouseEvent
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

    def get_preferred_height(self, width: int) -> int:
        """Calculate height needed for wrapped text."""
        # Note: If this TextComponent doesn't wrap itself (like ChatHistoryPanel currently does),
        # we still consider splitlines() count.
        lines = self.text.splitlines()
        return len(lines)

    def update(self, text: str):
        self.text = text

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

class InputComponent(Component):
    def __init__(self, prompt: str = "> ", id: Optional[str] = None, fg=None, bg=None):
        super().__init__(id)
        self.prompt = prompt
        self.text = ""
        self.fg = fg
        self.bg = bg
        self.on_submit = None  # Callback for when enter is pressed
        self.cursor_pos = 0
        self.scroll_y = 0
        self._last_cursor_pos = -1
        self._last_input_time = 0.0 # Track time of last user input
        self.config = None # Config object passed during initialization

    def _get_cursor_coords(self, pos: int) -> tuple[int, int]:
        """Convert a string index to (row, col) coordinates."""
        prompt_width = display_width(self.prompt)
        available_width = self.width - 2
        
        # If text is empty, cursor is after prompt
        if not self.text[:pos]:
            return 0, prompt_width

        paragraphs = self.text[:pos].split('\n')
        curr_r = 0
        
        for i, para in enumerate(paragraphs):
            is_first_para = (i == 0)
            
            # Use wrap_text to see how this paragraph is laid out
            wrapped = wrap_text(para, available_width, padding_width=prompt_width, first_line_padding=(not is_first_para))
            para_lines = wrapped.split('\n') if wrapped else [""]
            
            if i < len(paragraphs) - 1:
                # This paragraph is finished (we encountered a \n)
                curr_r += len(para_lines)
            else:
                # This is the last paragraph (where the cursor is)
                last_line = para_lines[-1]
                curr_r += len(para_lines) - 1
                curr_c = display_width(last_line)
                
                # Adjust for prompt if we are in the first paragraph's first line
                if i == 0 and len(para_lines) == 1:
                    curr_c += prompt_width
                
                # Handle the case where the very last character was a newline
                if pos > 0 and self.text[pos-1] == '\n':
                    curr_r += 1
                    curr_c = prompt_width
                
                return curr_r, curr_c
        
        return 0, prompt_width

    def _get_pos_from_coords(self, target_r: int, target_c: int) -> int:
        """Find the closest string index for given (row, col) coordinates."""
        prompt_width = display_width(self.prompt)
        available_width = self.width - 2
        r, c = 0, prompt_width
        
        # If targeting a row before the start, return 0
        if target_r < 0: return 0
        
        best_pos_in_row = 0
        
        for i, char in enumerate(self.text):
            if r == target_r:
                if c >= target_c:
                    return i
                best_pos_in_row = i + 1
            elif r > target_r:
                return best_pos_in_row
            
            if char == '\n':
                if r == target_r:
                    return i
                r += 1
                c = prompt_width
                continue
            
            w = display_width(char)
            if c + w > available_width:
                if r == target_r:
                    return i
                r += 1
                c = prompt_width + w
            else:
                c += w
        
        return len(self.text)

    def _get_lines(self) -> list[str]:
        """Wrap text into lines based on current width, preserving newlines and applying left padding for multiline."""
        prompt_width = display_width(self.prompt)
        available_width = self.width - 2
        
        if available_width <= prompt_width:
            return [""]
            
        paragraphs = self.text.split('\n')
        all_lines = []
        
        for i, para in enumerate(paragraphs):
            is_first_para = (i == 0)
            if is_first_para:
                wrapped = wrap_text(para, available_width, padding_width=prompt_width, first_line_padding=False)
            else:
                wrapped = wrap_text(para, available_width, padding_width=prompt_width, first_line_padding=True)
            
            para_lines = wrapped.split('\n') if wrapped else [""]
            # Handle empty continuation lines (e.g. trailing newline)
            if not para_lines:
                para_lines = [""]
            
            # If the paragraph ends in a newline (except the last one which is handled by paragraphs iterate),
            # or if it's an empty paragraph between newlines
            all_lines.extend(para_lines)
            
        return all_lines

    def get_preferred_height(self, width: int) -> int:
        """Calculate height needed for wrapped text, considering prompt indentation."""
        prompt_width = display_width(self.prompt)
        # Use the same safety margin during height calculation
        calc_width = width - 2
        if calc_width <= prompt_width:
            return 1
            
        paragraphs = self.text.split('\n')
        total_lines = 0
        
        for i, para in enumerate(paragraphs):
            is_first_para = (i == 0)
            if is_first_para:
                wrapped = wrap_text(para, calc_width, padding_width=prompt_width, first_line_padding=False)
            else:
                wrapped = wrap_text(para, calc_width, padding_width=prompt_width, first_line_padding=True)
            
            total_lines += len(wrapped.split('\n')) if wrapped else 1
            
        # Ensure trailing newline is accounted for in height calculation
        if self.text.endswith('\n'):
            total_lines += 1
            
        return total_lines

    def render(self, buffer: Buffer):
        """Render the input field with prompt, text, and scrolling."""
        # Clear background first (to prevent artifacts when scrolling/resizing)
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=self.bg)
        
        lines = self._get_lines()
        # Handle trailing empty line (cursor at very end of a newline)
        if self.text.endswith('\n'):
            lines.append(" " * display_width(self.prompt))

        prompt_width = display_width(self.prompt)
        
        # Calculate cursor position (row, col)
        cursor_row, cursor_col = self._get_cursor_coords(self.cursor_pos)
        
        # Adjust scroll_y if cursor is out of view (during typing/movement)
        # Note: Mouse wheel also modifies scroll_y, we only force visibility on cursor movement
        if self.cursor_pos != self._last_cursor_pos:
            if cursor_row < self.scroll_y:
                self.scroll_y = cursor_row
            elif cursor_row >= self.scroll_y + self.height:
                self.scroll_y = cursor_row - self.height + 1
            self._last_cursor_pos = self.cursor_pos

        # Render visible lines
        for i in range(self.scroll_y, min(len(lines), self.scroll_y + self.height)):
            line_idx = i - self.scroll_y
            line = lines[i]
            
            display_line = ""
            if i == 0:
                # First line starts with the prompt
                display_line = self.prompt + (line if not line.startswith(" " * prompt_width) else line[prompt_width:])
            else:
                display_line = line
                
            buffer.write_str(self.x, self.y + line_idx, display_line, fg=self.fg, bg=self.bg, max_width=self.width)
        
        # No longer setting hardware cursor, we render an emulated cursor below
        screen_cursor_row = cursor_row - self.scroll_y
        if 0 <= screen_cursor_row < self.height:
            # Emulated pulsating cursor
            cx = self.x + cursor_col
            cy = self.y + screen_cursor_row
            
            if 0 <= cx < buffer.width and 0 <= cy < buffer.height:
                import time
                import math
                
                # Get settings from config or use defaults
                cursor_char = self.config.ui_cursor_char if self.config else "█"
                freq = self.config.ui_cursor_frequency if self.config else 1.0
                cursor_color = self.config.ui_cursor_color if self.config else (200, 200, 200)
                pulse_delay = self.config.ui_cursor_pulse_delay if self.config else 0.5

                # Pulsate visibility according to time and frequency
                now = time.time()
                time_since_input = now - self._last_input_time
                
                # If we've recently typed, keep cursor solid (pulse max)
                if time_since_input:
                    # We always want max opacity immediately after typing
                    # but `time_since_input < pulse_delay` handles the *start* of the pulse
                    pass
                
                # Calculate pulse value (0.0 to 1.0)
                if time_since_input < pulse_delay:
                    pulse = 1.0
                else:
                    # Sine wave pulse: 0 to 1 back to 0
                    pulse = (math.sin(now * 2 * math.pi * freq) + 1) / 2
                
                # Render the cursor effect
                if 0 <= cx < buffer.width and 0 <= cy < buffer.height:
                    curr_cell = buffer.cells[cy][cx]
                    char_under_cursor = curr_cell.char or " "
                    
                    # Determine rendering strategy based on what's under the cursor
                    if char_under_cursor.isspace() or not char_under_cursor:
                        # Case 1: Cursor is on a space/empty cell (typical append mode)
                        # We use the configured cursor character (block, pipe, etc.)
                        # Opacity modulation for "pulsing" effect on the character itself
                        
                        # Only draw if pulse is "on" (> 50% duty cycle usually, or gradient)
                        # For block cursor, let's just use the character
                        if pulse > 0.5:
                           buffer.set(cx, cy, cursor_char, fg=(255, 255, 255), bg=curr_cell.bg)
                    else:
                        # Case 2: Cursor is overlapping a character (insert/overwrite mode)
                        # We switch to a "block" style by inverting background color
                        # This ensures the character remains legible
                        
                        if pulse > 0.5:
                            # High contrast: Black text on White background
                            # preserving the character
                            buffer.cells[cy][cx].fg = (0, 0, 0)
                            buffer.cells[cy][cx].bg = (255, 255, 255)
                            buffer.cells[cy][cx].bold = False

                            # Handle wide characters (emojis) - update the background of the continuation cell
                            if display_width(char_under_cursor) == 2 and cx + 1 < buffer.width:
                                buffer.cells[cy][cx + 1].bg = (255, 255, 255)

    def handle_input(self, event: Any) -> bool:
        """Update last input time for cursor pulse logic."""
        import time
        if isinstance(event, (str, MouseEvent)):
            self._last_input_time = time.time()

        """Handle mouse wheel for scrolling."""
        if isinstance(event, MouseEvent):
            # Use parent (Box) boundaries if available for a larger hit-box
            target = self.parent if self.parent else self
            if target.x <= event.x < target.x + target.width and \
               target.y <= event.y < target.y + target.height:
                
                # Button 64/65 are scroll wheels
                if event.button == 64: # Scroll Up
                    if self.scroll_y > 0:
                        self.scroll_y -= 1
                        # If cursor is at bottom boundary, push it up to stay in view
                        # (Using a simple heuristic: if it would be off-screen, push it)
                        # More precisely: if we scroll UP, the cursor row relative to view INCREASES.
                        # But wait, if we scroll up, we see earlier lines. 
                        pass 
                    return True
                elif event.button == 65: # Scroll Down
                    lines = self._get_lines()
                    max_scroll = max(0, len(lines) - self.height)
                    if self.scroll_y < max_scroll:
                        self.scroll_y += 1
                    return True
        
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
                    self.scroll_y = 0
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
                curr_r, curr_c = self._get_cursor_coords(self.cursor_pos)
                if curr_r > 0:
                    # Try to maintain the same column index if possible
                    self.cursor_pos = self._get_pos_from_coords(curr_r - 1, curr_c)
                return True
                
            if event == '\x1b[B': # Down
                curr_r, curr_c = self._get_cursor_coords(self.cursor_pos)
                self.cursor_pos = self._get_pos_from_coords(curr_r + 1, curr_c)
                return True
            
            # Default: insert character
            
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
