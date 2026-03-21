"""Cursor rendering with animation for input component."""

import math
import time
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import theme


class CursorRenderer:
    """Handles cursor rendering with pulsating animation."""
    
    def __init__(self, config_getter):
        self.get_config = config_getter  # Callable that returns config
        self.last_input_time = 0.0
    
    def mark_input(self):
        """Mark that input was received (for pulse delay)."""
        self.last_input_time = time.time()
    
    def render(self, buffer: Buffer, cursor_row: int, cursor_col: int, 
               x: int, y: int, scroll_y: int, height: int):
        """Render the cursor at the given position."""
        screen_cursor_row = cursor_row - scroll_y
        
        # Only render if cursor is visible in viewport
        if not (0 <= screen_cursor_row < height):
            return
        
        cx = x + cursor_col
        cy = y + screen_cursor_row
        
        # Bounds check
        if not (0 <= cx < buffer.width and 0 <= cy < buffer.height):
            return
        
        # Get cursor settings
        config = self.get_config()
        freq = config.ui_cursor_frequency if (config and hasattr(config, 'ui_cursor_frequency')) else 0.0
        cursor_color = theme.DEFAULT
        
        # Calculate pulse
        now = time.time()
        pulse_delay = config.ui_cursor_pulse_delay if (config and hasattr(config, 'ui_cursor_pulse_delay')) else 0.5
        
        if now - self.last_input_time < pulse_delay:
            pulse = 1.0
        else:
            # Sine wave pulse: 0 to 1 back to 0
            pulse = (math.sin(now * 2 * math.pi * freq) + 1) / 2
        
        # Render cursor if visible
        if pulse > 0.2:
            curr_cell = buffer.cells[cy][cx]
            char_to_show = curr_cell.char or " "
            
            # Use reverse video for cursor - works with any terminal background
            buffer.set(cx, cy, char_to_show, fg=cursor_color, bg=theme.get_bg(), bold=True, reverse=True)
