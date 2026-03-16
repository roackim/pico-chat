"""Input panel for the Pico-Chat TUI."""

import asyncio
from typing import Optional, Callable, List

from pico_chat.ui.tui.component import InputComponent, Box
from pico_chat.ui.tui.command_menu import CommandMenu
from pico_chat.ui.commands import get_command_list


class InputPanel:
    """Manages the user input panel."""

    def __init__(self, agent):
        """Initialize the input panel.
        
        Args:
            agent: The Pico-Chat agent instance (for config)
        """
        self.agent = agent
        user_color = agent.config.ui_user_color
        self.component = InputComponent(" ", id="entry", fg=user_color)
        self.component.config = agent.config # Pass config for cursor behavior
        self.box = Box(self.component, title="message")
        self.box.max_height = 14 # 12 lines of text + 2 for borders
        self.on_submit_callback: Optional[Callable[[str], None]] = None
        
        # Command menu
        self.commands = get_command_list()
        self.command_menu = CommandMenu(self.commands, fg=user_color, bg=(0, 0, 0))
        self.command_menu.on_select = self.on_command_selected
        
        # Override component.handle_input to check for '/'
        self._original_handle_input = self.component.handle_input
        self.component.handle_input = self.handle_input
        self.component.update = self.update_and_filter

    def update_and_filter(self, text: str):
        """Update text and filter command menu."""
        self.component.text = text
        self.component.cursor_pos = len(text)
        self.command_menu.filter(text)

    def on_command_selected(self, command: str):
        """Handle command selection from menu."""
        self.component.text = command
        self.component.cursor_pos = len(command)
        self.command_menu.is_visible = False

    def handle_input(self, event) -> bool:
        """Interceptor for input to handle command menu."""
        # 1. Let command menu handle navigation if visible
        if self.command_menu.is_visible:
            if self.command_menu.handle_input(event):
                return True
        
        # 2. Pass to standard input component
        handled = self._original_handle_input(event)
        
        # 3. After input, check if we need to show/filter menu
        if isinstance(event, str):
            # If start of message is '/' and has no spaces, show/filter menu
            if self.component.text.startswith('/') and ' ' not in self.component.text:
                self.command_menu.filter(self.component.text)
            else:
                self.command_menu.is_visible = False
                
        return handled

    def set_on_submit(self, callback: Callable[[str], None]):
        """Set the callback for when user submits input.
        
        Args:
            callback: Function to call with the submitted text
        """
        self.on_submit_callback = callback
        self.component.on_submit = callback

    def get_component(self):
        """Get the box component for layout."""
        return self.box

    def render_menu(self, buffer):
        """Render floating command menu."""
        if not self.command_menu.is_visible:
            return
            
        # Position menu above input area
        menu_height = len(self.command_menu.filtered_commands) + 2
        # Target position: Above the box, shifted 2 chars more to the left
        self.command_menu.set_layout(
            self.box.x, 
            self.box.y - menu_height, 
            self.box.width - 4, 
            menu_height
        )
        self.command_menu.render(buffer)
