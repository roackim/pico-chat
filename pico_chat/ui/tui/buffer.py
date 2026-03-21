from dataclasses import dataclass
from typing import Optional
from wcwidth import wcwidth

from pico_chat.ui.tui.colors import RGB

@dataclass
class Cell:
    char: str = " "
    fg: Optional[tuple[int, int, int]] = None
    bg: Optional[tuple[int, int, int]] = None
    bold: bool = False
    reverse: bool = False
    is_wide_char_continuation: bool = False  # Marks cells that are part of a wide character

class Buffer:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # Import theme and config to get default background color for empty cells
        from pico_chat.ui.tui.colors import theme
        from pico_chat import pico_cfg
        
        # Only use theme background if config allows it
        if pico_cfg.config.ui_use_bg_color:
            self.default_bg = (theme.BACKGROUND.r, theme.BACKGROUND.g, theme.BACKGROUND.b)
        else:
            self.default_bg = None  # Use terminal default background
        
        self.cells = [[Cell(bg=self.default_bg) for _ in range(width)] for _ in range(height)]
        self.cursor_pos: Optional[tuple[int, int]] = None  # (x, y)
        self.clip_rect: Optional[tuple[int, int, int, int]] = None # x, y, w, h

    def set_clip(self, x: int, y: int, w: int, h: int):
        self.clip_rect = (x, y, w, h)

    def clear_clip(self):
        self.clip_rect = None

    def _is_in_clip(self, x: int, y: int) -> bool:
        if self.clip_rect is None:
            return True
        cx, cy, cw, ch = self.clip_rect
        return cx <= x < cx + cw and cy <= y < cy + ch

    def set_cursor(self, x: int, y: int):
        self.cursor_pos = (x, y)

    def set(self, x: int, y: int, char: str, fg=None, bg=None, bold=False, reverse=False):
        if 0 <= x < self.width and 0 <= y < self.height:
            if not self._is_in_clip(x, y):
                return
            # Convert RGB objects to tuples
            if fg is not None and hasattr(fg, 'r'):
                fg = (fg.r, fg.g, fg.b)
            if bg is not None and hasattr(bg, 'r'):
                bg = (bg.r, bg.g, bg.b)
            # Important: Always create a fresh Cell instance to avoid sharing
            self.cells[y][x] = Cell(char, fg, bg, bold, reverse)

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
                
                # If this is a wide character (emoji), mark the next cell as continuation
                if char_width == 2:
                    if 0 <= curr_x < self.width and 0 <= y < self.height:
                        self.set(curr_x, y, pending_ansi + char, fg, bg, bold)
                    
                    if 0 <= curr_x + 1 < self.width and 0 <= y < self.height:
                        if self._is_in_clip(curr_x + 1, y):
                            # Convert RGB to tuple if needed
                            fg_tuple = (fg.r, fg.g, fg.b) if fg is not None and hasattr(fg, 'r') else fg
                            bg_tuple = (bg.r, bg.g, bg.b) if bg is not None and hasattr(bg, 'r') else bg
                            self.cells[y][curr_x + 1] = Cell(
                                char="",
                                fg=fg_tuple,
                                bg=bg_tuple,
                                bold=bold,
                                is_wide_char_continuation=True
                            )
                    curr_x += 2  # Skip over both the character cell and continuation cell
                else:
                    if 0 <= curr_x < self.width and 0 <= y < self.height:
                        self.set(curr_x, y, pending_ansi + char, fg, bg, bold)
                    curr_x += 1  # Single-width character
                
                pending_ansi = ""
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
                self.cells[y][x] = Cell(bg=self.default_bg)

    def render(self) -> str:
        """
        Renders the entire buffer to a single ANSI string.
        Always performs a full redraw from the top-left corner.
        Properly handles wide characters (emojis) that span multiple columns.
        """
        from pico_chat.ui.tui.terminal import ANSI
        
        res = [ANSI.MOVE_HOME]
        
        # Initialize background based on whether we're using theme colors
        if self.default_bg is None:
            # Reset to terminal default background
            res.append("\033[49m")
        else:
            # Set theme background color
            res.append(f"\033[48;2;{self.default_bg[0]};{self.default_bg[1]};{self.default_bg[2]}m")
        
        # Use a sentinel value to force first cell to emit colors
        curr_state = {"fg": object(), "bg": object(), "bold": False, "reverse": False}
        
        for y in range(self.height):
            # Move to start of line
            res.append(ANSI.move_to(y + 1, 1))
            terminal_col = 0  # Track actual terminal column position
            
            for x in range(self.width):
                cell: RGB = self.cells[y][x]
                
                # Skip continuation cells (they're covered by the wide char before them)
                if cell.is_wide_char_continuation:
                    terminal_col += 1  # Still counts as a cell position
                    continue
                
                # If there's a gap between our current terminal column and where we should be,
                # use ANSI positioning to jump to the correct position
                if terminal_col != x:
                    res.append(ANSI.move_to(y + 1, x + 1))
                    terminal_col = x
                
                # Update attributes if changed
                attr_changed = (
                    cell.fg != curr_state["fg"] or 
                    cell.bg != curr_state["bg"] or 
                    cell.bold != curr_state["bold"] or 
                    cell.reverse != curr_state["reverse"]
                )
                
                if attr_changed:
                    # If turning off bold/reverse, we often need a full reset in some terminals
                    # but we try to be surgical
                    if (curr_state["bold"] and not cell.bold) or (curr_state["reverse"] and not cell.reverse):
                        res.append("\033[0m")
                        curr_state = {"fg": None, "bg": None, "bold": False, "reverse": False}
                    
                    if cell.fg != curr_state["fg"]:
                        if cell.fg:
                            if isinstance(cell.fg, tuple):
                                res.append(f"\033[38;2;{cell.fg[0]};{cell.fg[1]};{cell.fg[2]}m")
                            else:
                                res.append(cell.fg.ansi_fg())
                        else:
                            res.append("\033[39m")
                        curr_state["fg"] = cell.fg

                    if cell.bg != curr_state["bg"]:
                        if cell.bg:
                            if isinstance(cell.bg, tuple):
                                res.append(f"\033[48;2;{cell.bg[0]};{cell.bg[1]};{cell.bg[2]}m")
                            else:
                                res.append(cell.bg.ansi_bg())
                        else:
                            res.append("\033[49m")
                        curr_state["bg"] = cell.bg

                    if cell.bold and not curr_state["bold"]:
                        res.append("\033[1m")
                        curr_state["bold"] = True

                    if cell.reverse and not curr_state["reverse"]:
                        res.append("\033[7m")
                        curr_state["reverse"] = True

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
