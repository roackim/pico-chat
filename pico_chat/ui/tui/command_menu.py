from typing import List, Optional, Any, Callable
from pico_chat.ui.tui.component import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.fuzzy import fuzzy_search

class CommandMenu(Component):
    """A floating menu component for command autocomplete/suggestions."""
    
    def __init__(self, commands: List[str], id: Optional[str] = None, fg=None, bg=None, trigger: str = "/"):
        super().__init__(id)
        self.all_commands = commands
        self.filtered_commands: List[str] = []
        self.selected_index = 0
        self.fg = fg
        self.bg = bg
        self.is_visible = False
        self.on_select: Optional[Callable[[str], None]] = None
        self.trigger = trigger

    def filter(self, query: str):
        """Refine the menu based on fuzzy matching of the query."""
        # For commands, we still only support start of line for now to avoid collision
        if self.trigger == "/":
            if not query.startswith('/') or ' ' in query:
                self.is_visible = False
                return
            search_term = query[1:].strip()
        else:
            # For context, we find the last trigger in the string
            last_trigger_idx = query.rfind(self.trigger)
            if last_trigger_idx == -1:
                self.is_visible = False
                return
            
            # Extract content after the trigger until the end of string
            search_term = query[last_trigger_idx + len(self.trigger):]
            
            # If there's a space after the trigger, it's not a completion anymore
            if ' ' in search_term:
                self.is_visible = False
                return

        if not search_term:
            # Show all commands when just trigger is typed
            self.filtered_commands = self.all_commands
            self.is_visible = True
        else:
            # Use fuzzy search with a lower threshold to capture partial matches
            results = fuzzy_search(search_term, self.all_commands, threshold=0.01)
            self.filtered_commands = [res[0] for res in results]
            
            # Disable menu if no fuzzy match is found
            self.is_visible = len(self.filtered_commands) > 0

        if self.selected_index >= len(self.filtered_commands):
            self.selected_index = 0

    def render(self, buffer: Buffer):
        if not self.is_visible or not self.filtered_commands:
            return

        menu_height = len(self.filtered_commands) + 2
        
        # Calculate width including trigger
        max_raw_len = max(len(cmd) for cmd in self.filtered_commands)
        menu_width = max_raw_len + len(self.trigger) + 4
        menu_width = max(menu_width, 15)
        
        # Ensure it doesn't exceed parent width
        menu_width = min(menu_width, self.width)
        
        # Position menu above the anchor (usually the input field)
        # The parent should set our x, y such that we are positioned correctly.
        # But if we are a "floating" component, we might need absolute placement or 
        # the compositor to handle us special. For now, we'll assume the compositor 
        # or the root component gives us a proper bounding box.
        
        # Draw the box
        # Top border
        buffer.set(self.x, self.y, "┌", fg=self.fg)
        for i in range(1, menu_width - 1):
            buffer.set(self.x + i, self.y, "─", fg=self.fg)
        buffer.set(self.x + menu_width - 1, self.y, "┐", fg=self.fg)
        
        # Content
        for i, cmd in enumerate(self.filtered_commands):
            curr_y = self.y + 1 + i
            buffer.set(self.x, curr_y, "│", fg=self.fg)
            
            # Text to display
            display_text = f"{self.trigger}{cmd}"
            is_selected = (i == self.selected_index)
            
            # We want: │ (space) (highlighted text) (space) │
            # Total width inside borders is menu_width - 2
            inner_width = menu_width - 2
            
            # Draw the line
            highlight_width = inner_width - 2
            # Remove one space before the cmd string
            padded_text = f"{display_text}".ljust(highlight_width)
            
            if is_selected:
                # 1. Left margin (original background)
                buffer.set(self.x + 1, curr_y, " ", bg=self.bg)
                
                # 2. Highlighted content (covers width until 1 char from right border)
                buffer.write_str(self.x + 2, curr_y, padded_text, fg=self.bg, bg=self.fg)
                
                # 3. Right margin (original background)
                buffer.set(self.x + 1 + highlight_width + 1, curr_y, " ", bg=self.bg)
            else:
                # Regular rendering with same spacing
                buffer.set(self.x + 1, curr_y, " ", bg=self.bg)
                buffer.write_str(self.x + 2, curr_y, padded_text, fg=self.fg, bg=self.bg)
                buffer.set(self.x + 1 + highlight_width + 1, curr_y, " ", bg=self.bg)
                
            buffer.set(self.x + menu_width - 1, curr_y, "│", fg=self.fg)
            
        # Bottom border
        buffer.set(self.x, self.y + menu_height - 1, "└", fg=self.fg)
        for i in range(1, menu_width - 1):
            buffer.set(self.x + i, self.y + menu_height - 1, "─", fg=self.fg)
        buffer.set(self.x + menu_width - 1, self.y + menu_height - 1, "┘", fg=self.fg)

    def handle_input(self, event: Any) -> bool:
        if not self.is_visible:
            return False
            
        if event == '\x1b[A': # Up
            if self.filtered_commands:
                self.selected_index = (self.selected_index - 1) % len(self.filtered_commands)
                return True
        elif event == '\x1b[B': # Down
            if self.filtered_commands:
                self.selected_index = (self.selected_index + 1) % len(self.filtered_commands)
                return True
        elif event == '\t': # Tab -> Complete
            if self.filtered_commands and self.on_select:
                # For context, we don't want the trigger prefix in the final text
                completion = self.filtered_commands[self.selected_index]
                if self.trigger == "/":
                    completion = self.trigger + completion
                self.on_select(completion)
                self.is_visible = False
                return True
        elif event == '\r' or event == '\n': # Enter
            # If a perfect match is highlighted, complete it and let it submit
            if self.filtered_commands and self.on_select:
                completion = self.filtered_commands[self.selected_index]
                if self.trigger == "/":
                    completion = self.trigger + completion
                self.on_select(completion)
                self.is_visible = False
                return False # Return False so the Enter event bubbles up and triggers submit
            self.is_visible = False
            return False
        elif event == '\x1b' or event == ' ': # Escape or Space -> Disable menu
            self.is_visible = False
            return False
            
        return False
