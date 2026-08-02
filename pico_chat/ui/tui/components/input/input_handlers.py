"""Input event handlers for the input component."""

from typing import Any, TYPE_CHECKING
from pico_chat.ui.tui.terminal import MouseEvent, PasteEvent

if TYPE_CHECKING:
    from .text_buffer import TextBuffer
    from .coordinate_mapper import CoordinateMapper


class InputContext:
    """Context object passed to input handlers."""
    
    def __init__(self, buffer, coord_mapper, scroll_manager, menu_manager=None):
        self.buffer = buffer  # TextBuffer
        self.coord_mapper = coord_mapper  # CoordinateMapper
        self.scroll = scroll_manager  # ScrollManager
        self.menus = menu_manager  # Optional, kept for backwards compatibility


class InputHandler:
    """Base class for input event handlers."""
    
    def can_handle(self, event: Any) -> bool:
        """Check if this handler can process the event."""
        raise NotImplementedError
    
    def handle(self, event: Any, context: InputContext) -> bool:
        """Process the event. Return True if handled."""
        raise NotImplementedError


class PasteHandler(InputHandler):
    """Handles paste events."""
    
    def can_handle(self, event: Any) -> bool:
        return isinstance(event, PasteEvent)
    
    def handle(self, event: PasteEvent, context: InputContext) -> bool:
        # Normalize line endings
        paste_text = event.text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Insert at cursor
        context.buffer.insert(paste_text)
        
        # Auto-scroll to show cursor
        context.scroll.scroll_to_cursor()
        
        return True


class MouseHandler(InputHandler):
    """Handles mouse wheel scrolling."""
    
    def can_handle(self, event: Any) -> bool:
        return isinstance(event, MouseEvent)
    
    def handle(self, event: MouseEvent, context: InputContext) -> bool:
        # Check if mouse is within component bounds (handled by caller)
        if event.button == 64:  # Scroll Up
            for _ in range(event.scroll_delta):
                context.scroll.scroll_up()
            return True
        elif event.button == 65:  # Scroll Down
            for _ in range(event.scroll_delta):
                context.scroll.scroll_down()
            return True
        
        return False


class KeyboardHandler(InputHandler):
    """Handles keyboard input events."""
    
    # Key constants
    KEY_ENTER = '\r'
    KEY_NEWLINE = '\n'
    KEY_BACKSPACE = '\x7f'
    KEY_ESC = '\x1b'
    
    def __init__(self):
        self.on_submit = None  # Callback for when enter is pressed
    
    def can_handle(self, event: Any) -> bool:
        return isinstance(event, str)
    
    def handle(self, event: str, context: InputContext) -> bool:
        # Ignore naked escape
        if event == self.KEY_ESC:
            return True
        
        # Navigation keys
        if self._handle_navigation(event, context):
            return True
        
        # Editing keys
        if self._handle_editing(event, context):
            return True
        
        # Special combinations
        if self._handle_special_keys(event, context):
            return True
        
        # Default: insert printable character
        if len(event) == 1 and ord(event) >= 32:
            context.buffer.insert(event)
            return True
        
        return False
    
    def _handle_navigation(self, event: str, context: InputContext) -> bool:
        """Handle cursor movement keys."""
        if event == '\x1b[D':  # Left
            context.buffer.move_cursor_left()
            context.scroll.ensure_cursor_visible()
            return True
        
        if event == '\x1b[C':  # Right
            context.buffer.move_cursor_right()
            context.scroll.ensure_cursor_visible()
            return True
        
        if event == '\x1b[A':  # Up
            curr_r, curr_c = context.coord_mapper.get_cursor_coords(
                context.buffer.text, context.buffer.cursor_pos
            )
            if curr_r > 0:
                new_pos = context.coord_mapper.get_pos_from_coords(
                    context.buffer.text, curr_r - 1, curr_c
                )
                context.buffer.cursor_pos = new_pos
                context.scroll.ensure_cursor_visible()
            return True
        
        if event == '\x1b[B':  # Down
            curr_r, curr_c = context.coord_mapper.get_cursor_coords(
                context.buffer.text, context.buffer.cursor_pos
            )
            # Get total number of rows
            lines = context.coord_mapper.get_wrapped_lines(context.buffer.text)
            # Only move down if not on last row
            if curr_r < len(lines) - 1:
                new_pos = context.coord_mapper.get_pos_from_coords(
                    context.buffer.text, curr_r + 1, curr_c
                )
                context.buffer.cursor_pos = new_pos
                context.scroll.ensure_cursor_visible()
            return True
        
        # Ctrl+Left (Word back)
        if event == '\x1b[1;5D':
            context.buffer.move_cursor_word_left()
            return True
        
        # Ctrl+Right (Word forward)
        if event == '\x1b[1;5C':
            context.buffer.move_cursor_word_right()
            return True
        
        return False
    
    def _handle_editing(self, event: str, context: InputContext) -> bool:
        """Handle text editing keys."""
        if event == self.KEY_BACKSPACE:
            context.buffer.delete_backward()
            return True
        
        # Ctrl+W or Ctrl+Backspace (Delete word back)
        if event in ('\x17', '\x1b\x7f', '\x08'):
            context.buffer.delete_word_backward()
            return True
        
        return False
    
    def _handle_special_keys(self, event: str, context: InputContext) -> bool:
        """Handle special key combinations."""
        # Alt+Enter or Ctrl+Enter -> Insert newline
        if event in ('\x1b\r', '\x1b\n', '\x0a'):
            context.buffer.insert('\n')
            return True
        
        # Regular Enter -> Submit
        if event in (self.KEY_ENTER, self.KEY_NEWLINE):
            if self.on_submit and not context.buffer.is_empty():
                self.on_submit(context.buffer.text)
                context.buffer.clear()
                context.scroll.reset()
            return True
        
        return False
