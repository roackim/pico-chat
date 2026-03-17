"""Input panel for the Pico-Chat TUI."""

import asyncio
from typing import Optional, Callable, List

from pico_chat.ui.tui.component import InputComponent, Box
from pico_chat.ui.tui.terminal import PasteEvent
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
        
        # Context (File/Folder) menu
        self.context_menu = CommandMenu([], fg=user_color, bg=(0, 0, 0), trigger="@")
        self.context_menu.on_select = self.on_context_selected
        
        # Override component.handle_input to check for '/'
        self._original_handle_input = self.component.handle_input
        self.component.handle_input = self.handle_input
        self.component.update = self.update_and_filter

    def update_and_filter(self, text: str):
        """Update text and filter command menu."""
        self.component.text = text
        self.component.cursor_pos = len(text)
        self.command_menu.filter(text)
        self.context_menu.filter(text)

    def on_command_selected(self, command: str):
        """Handle command selection from menu."""
        self.component.text = command
        self.component.cursor_pos = len(command)
        self.command_menu.is_visible = False

    def on_context_selected(self, item: str):
        """Handle context (file/folder) selection from menu."""
        # Find the last '@' and replace everything from there with the item
        current_text = self.component.text
        last_at = current_text.rfind('@')
        if last_at != -1:
            # We replace the '@' and everything after it with just the path
            new_text = current_text[:last_at] + item
            self.component.text = new_text
            self.component.cursor_pos = len(new_text)
        self.context_menu.is_visible = False

    def handle_input(self, event) -> bool:
        """Interceptor for input to handle command menu."""
        # 1. Let command menus handle navigation if visible
        if self.command_menu.is_visible:
            if self.command_menu.handle_input(event):
                return True
        if self.context_menu.is_visible:
            if self.context_menu.handle_input(event):
                return True
        
        # 2. Pass to standard input component
        # IMPORTANT: We purposefully do NOT filter standard input here
        handled = self._original_handle_input(event)
        
        # 3. After input, check if we need to show/filter menu
        if isinstance(event, (str, PasteEvent)):
            # Check for leading spaces logic only for MENU visibility, not for preventing input
            full_text = self.component.text
            clean_text = full_text.lstrip()
            
            # If start of message is '/' AND there are NO spaces AFTER the slash
            # (meaning we are typing the command name)
            if clean_text.startswith('/') and ' ' not in clean_text:
                self.command_menu.filter(clean_text)
            else:
                self.command_menu.is_visible = False
            
            # Context menu logic (@) - can be anywhere in line
            last_at = full_text.rfind('@')
            if last_at != -1:
                # Check if there are any spaces between '@' and end of string
                after_at = full_text[last_at+1:]
                if ' ' not in after_at:
                    # Refresh file list if needed
                    if not self.context_menu.all_commands:
                        if hasattr(self.agent, 'list_files_and_folders'):
                            self.context_menu.all_commands = self.agent.list_files_and_folders()
                    
                    self.context_menu.filter(full_text)
                else:
                    self.context_menu.is_visible = False
            else:
                self.context_menu.is_visible = False
                
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
        if self.command_menu.is_visible:
            # Position menu above input area
            menu_height = len(self.command_menu.filtered_commands) + 2
            self.command_menu.set_layout(
                self.box.x, 
                self.box.y - menu_height, 
                self.box.width - 4, 
                menu_height
            )
            self.command_menu.render(buffer)
            
        if self.context_menu.is_visible:
            # Position menu above input area, same as command menu (they shouldn't be both visible)
            menu_height = min(len(self.context_menu.filtered_commands) + 2, 12) # Cap height for context
            self.context_menu.set_layout(
                self.box.x, 
                self.box.y - menu_height, 
                self.box.width - 4, 
                menu_height
            )
            self.context_menu.render(buffer)
