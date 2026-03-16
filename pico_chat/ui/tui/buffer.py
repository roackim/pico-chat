from dataclasses import dataclass
from typing import Optional
from wcwidth import wcwidth

@dataclass
class Cell:
    char: str = " "
    fg: Optional[tuple[int, int, int]] = None
    bg: Optional[tuple[int, int, int]] = None
    bold: bool = False
    is_wide_char_continuation: bool = False  # Marks cells that are part of a wide character

class Buffer:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells = [[Cell() for _ in range(width)] for _ in range(height)]
        self.cursor_pos: Optional[tuple[int, int]] = None  # (x, y)

    def set_cursor(self, x: int, y: int):
        self.cursor_pos = (x, y)

    def set(self, x: int, y: int, char: str, fg=None, bg=None, bold=False):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.cells[y][x] = Cell(char, fg, bg, bold)

    def fill(self, x: int, y: int, width: int, height: int, char: str = " ", fg=None, bg=None):
        """Fill a rectangular area with a character."""
        for iy in range(y, y + height):
            for ix in range(x, x + width):
                self.set(ix, iy, char, fg=fg, bg=bg)

    def write_str(self, x: int, y: int, s: str, fg=None, bg=None, bold=False, max_width: Optional[int] = None):
        """
        Writes a string to the buffer starting at (x, y).
        This method is ANSI-aware: escape sequences are stored alongside the next
        printable character in a single cell, ensuring they don't occupy extra
        horizontal space in the grid.
        Properly handles emoji and wide character widths using wcwidth.
        """
        import re
        # Regex for standard ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        
        curr_x = x
        pending_ansi = "" # Accumulates ANSI sequences to be attached to the next character
        i = 0
        count = 0 # Tracks visible character width (columns) for clipping
        
        while i < len(s):
            # Respect max_width if provided (clipping)
            if max_width is not None and count >= max_width:
                break
                
            match = ansi_escape.match(s, i)
            if match:
                # Found an ANSI sequence, buffer it without incrementing curr_x
                pending_ansi += match.group()
                i = match.end()
            else:
                char = s[i]
                if char == '\n':
                    break
                
                # Calculate the display width of this character
                char_width = wcwidth(char)
                if char_width < 0:  # Control characters return -1
                    char_width = 1
                
                # Check if this character would exceed max_width
                if max_width is not None and count + char_width > max_width:
                    break
                
                # Write the character plus any accumulated ANSI sequences to a single cell
                if 0 <= curr_x < self.width and 0 <= y < self.height:
                    self.set(curr_x, y, pending_ansi + char, fg, bg, bold)
                pending_ansi = ""
                
                # If this is a wide character (emoji), mark the next cell as continuation
                if char_width == 2 and curr_x + 1 < self.width:
                    self.cells[y][curr_x + 1] = Cell(
                        char="", 
                        fg=fg, 
                        bg=bg, 
                        bold=bold, 
                        is_wide_char_continuation=True
                    )
                    curr_x += 2  # Skip over both the character cell and continuation cell
                else:
                    curr_x += 1  # Single-width character
                
                i += 1
                count += char_width
        
        # Handle any trailing ANSI sequences (e.g., color resets)
        if pending_ansi and (max_width is None or count < max_width):
            if curr_x > x and 0 <= y < self.height:
                # Attach trailing ANSI to the last character written
                prev_cell = self.cells[y][curr_x - 1]
                prev_cell.char += pending_ansi
            elif 0 <= curr_x < self.width and 0 <= y < self.height:
                # If no characters were written, put ANSI in an empty cell
                self.set(curr_x, y, pending_ansi + " ", fg, bg, bold)

    def clear(self):
        for y in range(self.height):
            for x in range(self.width):
                self.cells[y][x] = Cell()

    def render(self) -> str:
        """
        Renders the entire buffer to a single ANSI string.
        Always performs a full redraw from the top-left corner.
        Properly handles wide characters (emojis) that span multiple columns.
        """
        from pico_chat.ui.tui.terminal import ANSI
        
        res = [ANSI.MOVE_HOME]
        curr_fg = None
        curr_bg = None
        
        for y in range(self.height):
            # Move to start of line
            res.append(ANSI.move_to(y + 1, 1))
            terminal_col = 0  # Track actual terminal column position
            
            for x in range(self.width):
                cell = self.cells[y][x]
                
                # Skip continuation cells (they're covered by the wide char before them)
                if cell.is_wide_char_continuation:
                    terminal_col += 1  # Still counts as a cell position
                    continue
                
                # If there's a gap between our current terminal column and where we should be,
                # use ANSI positioning to jump to the correct position
                if terminal_col != x:
                    res.append(ANSI.move_to(y + 1, x + 1))
                    terminal_col = x
                
                # Update colors if changed
                if cell.fg != curr_fg:
                    if cell.fg:
                        res.append(ANSI.color_rgb_fg(*cell.fg))
                    else:
                        res.append(ANSI.RESET)
                        curr_bg = None
                    curr_fg = cell.fg
                
                if cell.bg != curr_bg:
                    if cell.bg:
                        res.append(ANSI.color_rgb_bg(*cell.bg))
                    curr_bg = cell.bg
                    
                res.append(cell.char)
                
                # Check if next cell is marked as continuation (meaning this char is wide)
                if x + 1 < self.width and self.cells[y][x + 1].is_wide_char_continuation:
                    terminal_col += 2  # Wide character occupies 2 columns
                else:
                    terminal_col += 1  # Normal character occupies 1 column
        
        # Reset color and hide the hardware cursor at the end to avoid flickering.
        # We handle cursor display manually in components to prevent terminal cursor jitter.
        res.append(ANSI.HIDE_CURSOR)
        res.append(ANSI.RESET)
        return "".join(res)
