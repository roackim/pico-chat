from dataclasses import dataclass
from typing import Optional

@dataclass
class Cell:
    char: str = " "
    fg: Optional[tuple[int, int, int]] = None
    bg: Optional[tuple[int, int, int]] = None
    bold: bool = False

class Buffer:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells = [[Cell() for _ in range(width)] for _ in range(height)]

    def set(self, x: int, y: int, char: str, fg=None, bg=None, bold=False):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.cells[y][x] = Cell(char, fg, bg, bold)

    def write_str(self, x: int, y: int, s: str, fg=None, bg=None, bold=False, max_width: Optional[int] = None):
        """
        Writes a string to the buffer starting at (x, y).
        This method is ANSI-aware: escape sequences are stored alongside the next
        printable character in a single cell, ensuring they don't occupy extra
        horizontal space in the grid.
        """
        import re
        # Regex for standard ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        
        curr_x = x
        pending_ansi = "" # Accumulates ANSI sequences to be attached to the next character
        i = 0
        count = 0 # Tracks visible character count for clipping
        
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
                
                # Write the character plus any accumulated ANSI sequences to a single cell
                self.set(curr_x, y, pending_ansi + char, fg, bg, bold)
                pending_ansi = ""
                curr_x += 1
                i += 1
                count += 1
        
        # Handle any trailing ANSI sequences (e.g., color resets)
        if pending_ansi and (max_width is None or count < max_width):
            if curr_x > x:
                # Attach trailing ANSI to the last character written
                prev_cell = self.cells[y][curr_x - 1]
                prev_cell.char += pending_ansi
            else:
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
        """
        from pico_chat.ui.tui.terminal import ANSI
        
        res = [ANSI.MOVE_HOME]
        curr_fg = None
        curr_bg = None
        
        for y in range(self.height):
            # Move to start of line
            res.append(ANSI.move_to(y + 1, 1))
            for x in range(self.width):
                cell = self.cells[y][x]
                
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
                
        res.append(ANSI.RESET)
        return "".join(res)
