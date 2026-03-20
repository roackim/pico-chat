"""Menu management for input component."""

from typing import Optional, Any, List, Callable
from pico_chat.ui.tui.components.menu import CommandMenu
from pico_chat.ui.tui.buffer import Buffer


class MenuManager:
    """Manages command and context menus for the input component."""
    
    def __init__(self, fg, bg):
        self.command_menu: Optional[CommandMenu] = None
        self.context_menu: Optional[CommandMenu] = None
        self.get_context_items_callback: Optional[Callable[[], List[str]]] = None
        self.fg = fg
        self.bg = bg
    
    def setup_menus(self, commands: List[str], get_context_items: Optional[Callable[[], List[str]]] = None):
        """Initialize built-in menus."""
        self.command_menu = CommandMenu(commands, fg=self.fg, bg=self.bg)
        self.command_menu.on_select = self._on_command_selected
        
        self.context_menu = CommandMenu([], fg=self.fg, bg=self.bg, trigger="@")
        self.context_menu.on_select = self._on_context_selected
        self.get_context_items_callback = get_context_items
        
        # Store callbacks that will be set by InputComponent
        self._text_setter = None
        self._cursor_setter = None
    
    def set_text_callbacks(self, text_setter, cursor_setter):
        """Set callbacks for updating text/cursor when menu item is selected."""
        self._text_setter = text_setter
        self._cursor_setter = cursor_setter
    
    def _on_command_selected(self, command: str):
        """Handle command menu selection."""
        if self._text_setter and self._cursor_setter:
            self._text_setter(command)
            self._cursor_setter(len(command))
        if self.command_menu:
            self.command_menu.is_visible = False
    
    def _on_context_selected(self, item: str):
        """Handle context menu selection."""
        if self._text_setter and self._cursor_setter:
            # Get current text to find last @
            # This is a bit awkward - we need access to current text
            # For now, we'll handle this in InputComponent
            pass
    
    def update_visibility(self, text: str, cursor_pos: int):
        """Update menu visibility based on current text."""
        clean_text = text.lstrip()
        
        # Command menu logic
        if self.command_menu:
            if clean_text.startswith('/') and ' ' not in clean_text:
                self.command_menu.filter(clean_text)
            else:
                self.command_menu.is_visible = False
        
        # Context menu logic
        if self.context_menu:
            last_at = text.rfind('@')
            if last_at != -1:
                after_at = text[last_at+1:]
                if ' ' not in after_at:
                    if not self.context_menu.all_items and self.get_context_items_callback:
                        self.context_menu.all_items = self.get_context_items_callback()
                    self.context_menu.filter(text)
                else:
                    self.context_menu.is_visible = False
            else:
                self.context_menu.is_visible = False
    
    def handle_input(self, event: Any) -> bool:
        """Forward input to active menu. Return True if handled."""
        if self.command_menu and self.command_menu.is_visible:
            if self.command_menu.handle_input(event):
                return True
        
        if self.context_menu and self.context_menu.is_visible:
            if self.context_menu.handle_input(event):
                return True
        
        return False
    
    def render(self, buffer: Buffer, x: int, y: int, width: int):
        """Render visible menus."""
        if self.command_menu and self.command_menu.is_visible:
            menu_height = len(self.command_menu.filtered_items) + 2
            self.command_menu.set_layout(
                x - 1,
                y - menu_height - 1,
                width - 2,
                menu_height
            )
            self.command_menu.render(buffer)
        
        if self.context_menu and self.context_menu.is_visible:
            menu_height = min(len(self.context_menu.filtered_items) + 2, 12)
            self.context_menu.set_layout(
                x - 1,
                y - menu_height - 1,
                width - 2,
                menu_height
            )
            self.context_menu.render(buffer)
    
    def handle_context_selection(self, text: str, item: str) -> tuple[str, int]:
        """Handle context menu selection and return new text and cursor position."""
        last_at = text.rfind('@')
        if last_at != -1:
            new_text = text[:last_at] + item
            return new_text, len(new_text)
        return text, len(text)
