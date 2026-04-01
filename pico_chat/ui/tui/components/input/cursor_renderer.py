"""Cursor rendering with animation for input component."""

import time
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import theme


class CursorRenderer:
    """Handles cursor rendering with pulsating animation."""
    
    def __init__(self, config_getter):
        self.get_config = config_getter  # Callable that returns config
        self.last_input_time = time.time()  # Start with solid cursor
        self.last_blink_time = time.time()  # Initialize to now
        self.cursor_visible = True
    
    def mark_input(self):
        """Mark that input was received (for pulse delay)."""
        self.last_input_time = time.time()
        self.cursor_visible = True
    
    def render(self, buffer: Buffer, cursor_row: int, cursor_col: int, 
               x: int, y: int, scroll_y: int, height: int, parent_box=None) -> bool:
        """Render the cursor at the given position.
        
        Returns:
            bool: True if cursor state changed (for marking parent dirty)
        """
        screen_cursor_row = cursor_row - scroll_y
        
        # Only render if cursor is visible in viewport
        if not (0 <= screen_cursor_row < height):
            return False
        
        cx = x + cursor_col
        cy = y + screen_cursor_row
        
        # Bounds check
        if not (0 <= cx < buffer.width and 0 <= cy < buffer.height):
            return False
        
        # Get cursor settings
        config = self.get_config()
        blink_interval = 0.5  # Default 0.5 seconds
        if config and hasattr(config, 'ui_cursor_pulse_delay'):
            blink_interval = config.ui_cursor_pulse_delay
        
        # Check if we should toggle cursor visibility
        now = time.time()
        pulse_delay = 0.5
        if config and hasattr(config, 'ui_cursor_pulse_delay'):
            pulse_delay = config.ui_cursor_pulse_delay
        
        state_changed = False
        
        # Keep cursor solid for a moment after input
        if now - self.last_input_time < pulse_delay:
            if not self.cursor_visible:
                self.cursor_visible = True
                state_changed = True
        else:
            # Blink the cursor
            if now - self.last_blink_time >= blink_interval:
                self.cursor_visible = not self.cursor_visible
                self.last_blink_time = now
                state_changed = True
        
        # Render cursor if visible
        if self.cursor_visible:
            curr_cell = buffer.cells[cy][cx]
            char_to_show = curr_cell.char or " "
            buffer.set(cx, cy, char_to_show, fg=theme.DEFAULT, bg=theme.get_bg(), bold=True, reverse=True)
        
        # Mark parent Box as changed if state changed
        if state_changed and parent_box and hasattr(parent_box, 'mark_changed'):
            parent_box.mark_changed()
        
        return state_changed
