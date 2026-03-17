import math
import time
from typing import Optional, Any, List, Callable
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.components.menu import CommandMenu
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.terminal import MouseEvent, PasteEvent
from pico_chat.ui.tui.layout_utils import display_width, wrap_text

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
        self.config = None # Config object passed during initialization
        
        # New: Integrated Command/Context menus
        self.command_menu: Optional[CommandMenu] = None
        self.context_menu: Optional[CommandMenu] = None
        self.get_context_items_callback: Optional[Callable[[], List[str]]] = None

    def setup_menus(self, commands: List[str], get_context_items: Optional[Callable[[], List[str]]] = None):
        """Initialize built-in menus."""
        self.command_menu = CommandMenu(commands, fg=self.fg, bg=(0, 0, 0))
        self.command_menu.on_select = self._on_command_selected
        
        self.context_menu = CommandMenu([], fg=self.fg, bg=(0, 0, 0), trigger="@")
        self.context_menu.on_select = self._on_context_selected
        self.get_context_items_callback = get_context_items

    def _on_command_selected(self, command: str):
        self.text = command
        self.cursor_pos = len(command)
        if self.command_menu:
            self.command_menu.is_visible = False

    def _on_context_selected(self, item: str):
        last_at = self.text.rfind('@')
        if last_at != -1:
            new_text = self.text[:last_at] + item
            self.text = new_text
            self.cursor_pos = len(new_text)
        if self.context_menu:
            self.context_menu.is_visible = False

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
        """Render the input field with prompt, text, scrolling, and menus."""
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
                # Get settings from config or use defaults
                cursor_char = self.config.ui_cursor_char if self.config else "█"
                freq = self.config.ui_cursor_frequency if self.config else 1.0
                cursor_color = self.config.ui_cursor_color if self.config else (200, 200, 200)

                # Pulsate visibility according to time and frequency
                now = time.time()
                # Sine wave pulse: 0 to 1 back to 0
                pulse = (math.sin(now * 2 * math.pi * freq) + 1) / 2
                
                curr_cell = buffer.cells[cy][cx]
                
                # Only draw "extra" cursor char if the cell is empty or has a space
                # Otherwise we overlay/highlight the existing character
                char_to_show = curr_cell.char or " "
                if char_to_show.isspace() and pulse > 0.3: # Show cursor char for most of the cycle
                     char_to_show = cursor_char
                
                # If pulse is high enough, we show the cursor styling
                if pulse > 0.1:
                    buffer.set(cx, cy, char_to_show, fg=cursor_color, bg=self.bg, bold=True)

        # RENDER MENUS OVER THE INPUT AREA
        if self.command_menu and self.command_menu.is_visible:
            # Position menu relative to this component's top
            menu_height = len(self.command_menu.filtered_items) + 2
            self.command_menu.set_layout(
                self.x, 
                self.y - menu_height, 
                self.width - 2, # Subtract some margin to fit nicely inside current layouts
                menu_height
            )
            self.command_menu.render(buffer)
            
        if self.context_menu and self.context_menu.is_visible:
            menu_height = min(len(self.context_menu.filtered_items) + 2, 12)
            self.context_menu.set_layout(
                self.x, 
                self.y - menu_height, 
                self.width - 2, 
                menu_height
            )
            self.context_menu.render(buffer)

    def handle_input(self, event: Any) -> bool:
        """Handle mouse wheel, keyboard input, and menus."""
        # 1. Menu handling (intercept navigation keys)
        if self.command_menu and self.command_menu.is_visible:
            if self.command_menu.handle_input(event):
                return True
        if self.context_menu and self.context_menu.is_visible:
            if self.context_menu.handle_input(event):
                return True

        # 2. Mouse handling
        if isinstance(event, MouseEvent):
            # ... existing mouse scroll logic ...
            # Use parent (Box) boundaries if available for a larger hit-box
            target = self.parent if self.parent else self
            if target.x <= event.x < target.x + target.width and \
               target.y <= event.y < target.y + target.height:
                
                # Button 64/65 are scroll wheels
                if event.button == 64: # Scroll Up
                    if self.scroll_y > 0:
                        self.scroll_y -= 1
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
            if len(event) == 1 and ord(event) >= 32:
                self.text = self.text[:self.cursor_pos] + event + self.text[self.cursor_pos:]
                self.cursor_pos += 1
                
                # UPDATE MENU VISIBILITY
                full_text = self.text
                clean_text = full_text.lstrip()
                
                if self.command_menu:
                    if clean_text.startswith('/') and ' ' not in clean_text:
                        self.command_menu.filter(clean_text)
                    else:
                        self.command_menu.is_visible = False
                        
                if self.context_menu:
                    last_at = full_text.rfind('@')
                    if last_at != -1:
                        after_at = full_text[last_at+1:]
                        if ' ' not in after_at:
                            # Refresh items via callback if needed
                            if not self.context_menu.all_items and self.get_context_items_callback:
                                self.context_menu.all_items = self.get_context_items_callback()
                            self.context_menu.filter(full_text)
                        else:
                            self.context_menu.is_visible = False
                    else:
                        self.context_menu.is_visible = False

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
