from typing import Optional, Any, List, Callable
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.components.text_buffer import TextBuffer
from pico_chat.ui.tui.components.coordinate_mapper import CoordinateMapper
from pico_chat.ui.tui.components.input_handlers import (
    InputHandler, InputContext, KeyboardHandler, MouseHandler, PasteHandler
)
from pico_chat.ui.tui.components.menu_manager import MenuManager
from pico_chat.ui.tui.components.scroll_manager import ScrollManager
from pico_chat.ui.tui.components.cursor_renderer import CursorRenderer
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.terminal import MouseEvent
from pico_chat.ui.tui.layout_utils import display_width

from pico_chat.ui.tui.colors import theme

class InputComponent(Component):
    """Multi-line text input component with menus, scrolling, and cursor animation."""
    
    def __init__(self, prompt: str = "> ", id: Optional[str] = None, fg=None, bg=None):
        super().__init__(id)
        self.prompt = prompt
        self.fg = fg if fg is not None else theme.DEFAULT
        self.bg = bg if bg is not None else theme.get_bg()
        self.config = None  # Config object passed during initialization
        
        # Core components
        self.buffer = TextBuffer()
        self.coord_mapper = CoordinateMapper(prompt, self.width)
        self.menu_manager = MenuManager(self.fg, self.bg)
        self.scroll_manager = ScrollManager(
            self.buffer,
            self.coord_mapper,
            lambda: self.height
        )
        self.cursor_renderer = CursorRenderer(lambda: self.config, self.bg)
        
        # Input handlers
        self.keyboard_handler = KeyboardHandler()
        self.input_handlers: List[InputHandler] = [
            PasteHandler(),
            MouseHandler(),
            self.keyboard_handler
        ]
        
        # Setup menu callbacks
        self.menu_manager.set_text_callbacks(
            lambda text: setattr(self.buffer, 'text', text),
            lambda pos: setattr(self.buffer, 'cursor_pos', pos)
        )
    
    @property
    def on_submit(self):
        """Get submit callback."""
        return self.keyboard_handler.on_submit
    
    @on_submit.setter
    def on_submit(self, callback):
        """Set submit callback."""
        self.keyboard_handler.on_submit = callback
    
    @property
    def text(self) -> str:
        """Get current text (for backward compatibility)."""
        return self.buffer.text
    
    @text.setter
    def text(self, value: str):
        """Set text (for backward compatibility)."""
        self.buffer.text = value
    
    @property
    def cursor_pos(self) -> int:
        """Get cursor position (for backward compatibility)."""
        return self.buffer.cursor_pos
    
    @cursor_pos.setter
    def cursor_pos(self, value: int):
        """Set cursor position (for backward compatibility)."""
        self.buffer.cursor_pos = value

    def setup_menus(self, commands: List[str], get_context_items: Optional[Callable[[], List[str]]] = None):
        """Initialize built-in menus."""
        self.menu_manager.setup_menus(commands, get_context_items)
        
        # Override context selection to handle @ replacement properly
        original_on_select = self.menu_manager.context_menu.on_select
        def context_select_wrapper(item: str):
            new_text, new_cursor = self.menu_manager.handle_context_selection(self.buffer.text, item)
            self.buffer.text = new_text
            self.buffer.cursor_pos = new_cursor
            if self.menu_manager.context_menu:
                self.menu_manager.context_menu.is_visible = False
        
        if self.menu_manager.context_menu:
            self.menu_manager.context_menu.on_select = context_select_wrapper

    def set_layout(self, x: int, y: int, width: int, height: int):
        """Update layout and notify coordinate mapper of width change."""
        super().set_layout(x, y, width, height)
        self.coord_mapper.update_dimensions(width)

    def get_preferred_height(self, width: int) -> int:
        """Calculate height needed for wrapped text."""
        # Temporarily update dimensions for calculation
        old_width = self.coord_mapper.width
        self.coord_mapper.update_dimensions(width)
        lines = self.coord_mapper.get_wrapped_lines(self.buffer.text)
        self.coord_mapper.update_dimensions(old_width)
        
        # Apply maximum height constraint from config
        height = len(lines) if lines else 1
        if self.config and hasattr(self.config, 'ui_max_input_height'):
            height = min(height, self.config.ui_max_input_height)
        return height

    def render(self, buffer: Buffer):
        """Render the input field with prompt, text, scrolling, and menus."""
        # Clear background
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=self.bg)
        
        # Get wrapped lines
        lines = self.coord_mapper.get_wrapped_lines(self.buffer.text)
        prompt_width = display_width(self.prompt)
        
        # Get cursor position
        cursor_row, cursor_col = self.coord_mapper.get_cursor_coords(
            self.buffer.text, self.buffer.cursor_pos
        )
        
        # Ensure cursor is visible and scroll is constrained
        self.scroll_manager.ensure_cursor_visible()
        
        # Render visible lines
        scroll_y = self.scroll_manager.scroll_y
        
        # Safety check: ensure scroll_y is in bounds
        if scroll_y >= len(lines):
            scroll_y = max(0, len(lines) - 1)
            self.scroll_manager.scroll_y = scroll_y
        
        for i in range(scroll_y, min(len(lines), scroll_y + self.height)):
            line_idx = i - scroll_y
            line = lines[i]
            
            # Only add prompt to the very first line of content (when not scrolled past it)
            if i == 0:
                # First line of text - add prompt
                display_line = self.prompt + line
            else:
                # Continuation lines already have proper padding
                display_line = line
            
            buffer.write_str(self.x, self.y + line_idx, display_line, fg=self.fg, bg=self.bg, max_width=self.width)
        
        # Render cursor
        self.cursor_renderer.render(
            buffer, cursor_row, cursor_col,
            self.x, self.y, scroll_y, self.height
        )
        
        # Render menus
        self.menu_manager.render(buffer, self.x, self.y, self.width)

    def handle_input(self, event: Any) -> bool:
        """Handle input events by delegating to appropriate handlers."""
        # Mark input for cursor animation
        self.cursor_renderer.mark_input()
        
        # Try menus first
        if self.menu_manager.handle_input(event):
            return True
        
        # Handle mouse events (check bounds)
        if isinstance(event, MouseEvent):
            target = self.parent if self.parent else self
            if not (target.x <= event.x < target.x + target.width and
                    target.y <= event.y < target.y + target.height):
                return False
        
        # Create context for handlers
        context = InputContext(
            self.buffer,
            self.coord_mapper,
            self.scroll_manager,
            self.menu_manager
        )
        
        # Try each handler
        for handler in self.input_handlers:
            if handler.can_handle(event) and handler.handle(event, context):
                # Update menu visibility after text changes
                self.menu_manager.update_visibility(self.buffer.text, self.buffer.cursor_pos)
                return True
        
        return False

    def update(self, text: str):
        """Update the input field text programmatically."""
        self.buffer.text = text
        self.buffer.cursor_pos = len(text)

    def clear(self):
        """Clear the input field."""
        self.buffer.clear()
        self.scroll_manager.reset()
