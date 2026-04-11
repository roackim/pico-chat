"""Server name completion for /server use and /server remove commands."""

from typing import List, Optional, Callable
from pico_chat.ui.tui.components.menu import SelectionMenu


class ServerCompletion:
    """Manages server name completion for /server use and /server remove, and type completion for /server add."""
    
    def __init__(self, menu: SelectionMenu, get_servers_callback: Callable[[], List[str]]):
        self.menu = menu
        self.get_servers = get_servers_callback
        self.is_active = False
        self.suppressed_word: Optional[str] = None
        self.server_name_commands = ["use", "remove"]  # Commands that need server names
        self.server_types = ["openrouter", "llamacpp"]  # Available server types for 'add'
    
    def parse_command_line(self, text: str) -> Optional[tuple[str, str, str]]:
        """Parse /server <subcommand> <argument>.
        
        Returns (command, subcommand, argument_text) or None.
        """
        clean = text.lstrip()
        
        # Must start with /server
        if not clean.startswith('/server '):
            return None
        
        # Split into parts
        parts = clean.split(' ', 2)
        
        if len(parts) < 2:
            return None
        
        command = parts[0][1:]  # Remove leading /
        subcommand = parts[1]
        argument_text = parts[2] if len(parts) > 2 else ""
        
        # Trigger for server name commands or 'add' command
        if subcommand not in self.server_name_commands and subcommand != 'add':
            return None
        
        return (command, subcommand, argument_text)
    
    def should_trigger(self, text: str) -> bool:
        """Check if server name completion should be active."""
        parsed = self.parse_command_line(text)
        return parsed is not None
    
    def update(self, text: str, cursor_pos: int):
        """Auto-update menu based on current text and cursor position."""
        parsed = self.parse_command_line(text)
        
        if not parsed:
            self.hide()
            return
        
        command, subcommand, argument_text = parsed
        
        # Determine what to show: server types or server names
        if subcommand == 'add':
            # For '/server add', show server types
            items = self.server_types
        else:
            # For '/server use' and '/server remove', show server names
            items = self.get_servers()
        
        if not items:
            self.hide()
            return
        
        # Clear suppression memory if argument text changes
        if self.suppressed_word and argument_text:
            if not argument_text.startswith(self.suppressed_word):
                self.suppressed_word = None
        elif self.suppressed_word and not argument_text:
            self.suppressed_word = None
        
        # Don't show menu if current word starts with suppressed prefix
        if argument_text and self.suppressed_word and argument_text.startswith(self.suppressed_word):
            self.hide()
            return
        
        # Strip trailing whitespace for exact match check
        argument_trimmed = argument_text.rstrip()
        
        # For /server add, check if we've entered a valid type and additional arguments
        if subcommand == 'add' and ' ' in argument_text:
            # User has typed server type and is now typing additional args
            self.hide()
            return
        
        # Filter out exact matches
        if argument_trimmed in items:
            self.hide()
            return
        
        # Update menu with fuzzy filtering
        self.menu.update(items, argument_trimmed, display_prefix="")
        self.is_active = self.menu.is_visible
    
    def accept_selection(self, text: str) -> Optional[str]:
        """Accept current selection, return completed text."""
        selected = self.menu.get_selected()
        if not selected:
            return None
        
        parsed = self.parse_command_line(text)
        if not parsed:
            return None
        
        command, subcommand, _ = parsed
        
        # Return full command with selected item
        return f"/{command} {subcommand} {selected}"
    
    def hide(self):
        """Deactivate and hide menu."""
        self.menu.hide()
        self.is_active = False
    
    def cancel(self, text: str, cursor_pos: int):
        """User pressed ESC - suppress menu for current argument prefix."""
        parsed = self.parse_command_line(text)
        if parsed:
            _, _, argument_text = parsed
            if argument_text:
                self.suppressed_word = argument_text
        self.hide()
    
    def navigate_up(self):
        """Move selection up in menu."""
        if self.is_active:
            self.menu.action_up()
    
    def navigate_down(self):
        """Move selection down in menu."""
        if self.is_active:
            self.menu.action_down()
