import math
import time
from typing import List, Optional, Any, Callable
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.fuzzy import fuzzy_search
from pico_chat.ui.tui.colors import RGB, theme

class CommandMenu(Component):
    """A floating menu component for command autocomplete/suggestions."""
    
    def __init__(self, 
                 items: List[str], 
                 id: Optional[str] = None, 
                 frame_color: RGB = None,
                 content_color: RGB = None,
                 left_pad: int = 1,
                 right_pad: int = 1,
                 max_height: int = 12,
                 trigger: str = "/"):
        super().__init__(id)
        self.all_items = items
        self.filtered_items: List[str] = []
        self.selected_index = 0
        self.frame_color = frame_color if frame_color is not None else theme.DEFAULT
        self.content_color = content_color if content_color is not None else self.frame_color
        self.bg = theme.get_bg()  # Use global background
        self.left_pad = left_pad
        self.right_pad = right_pad
        self.max_height = max_height
        self.is_visible = False
        self.on_select: Optional[Callable[[str], None]] = None
        self.trigger = trigger

    def filter(self, query: str):
        """Refine the menu based on fuzzy matching of the query."""
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
            # Show all items when just trigger is typed
            self.filtered_items = self.all_items
            self.is_visible = True
        else:
            # Use fuzzy search with a lower threshold to capture partial matches
            results = fuzzy_search(search_term, self.all_items, threshold=0.01)
            self.filtered_items = [res[0] for res in results]
            
            # Disable menu if no fuzzy match is found
            self.is_visible = len(self.filtered_items) > 0

        if self.selected_index >= len(self.filtered_items):
            self.selected_index = 0

    def render(self, buffer: Buffer):
        if not self.is_visible or not self.filtered_items:
            return

        # Calculate menu dimensions
        max_raw_len = max(len(item) for item in self.filtered_items)
        content_width = max_raw_len + len(self.trigger)
        menu_width = content_width + self.left_pad + self.right_pad + 2  # +2 for borders
        menu_width = max(menu_width, 15)
        menu_width = min(menu_width, self.width)  # Respect parent width
        
        # Use max_height to limit visible items
        visible_count = min(len(self.filtered_items), self.max_height - 2)  # -2 for borders
        menu_height = visible_count + 2  # +2 for top and bottom borders
        
        # Draw the box with background
        buffer.set(self.x, self.y, "┌", fg=self.frame_color, bg=self.bg)
        for i in range(1, menu_width - 1):
            buffer.set(self.x + i, self.y, "─", fg=self.frame_color, bg=self.bg)
        buffer.set(self.x + menu_width - 1, self.y, "┐", fg=self.frame_color, bg=self.bg)
        
        # Render items
        for i in range(visible_count):
            item = self.filtered_items[i]
            curr_y = self.y + 1 + i
            
            # Draw left border
            buffer.set(self.x, curr_y, "│", fg=self.frame_color, bg=self.bg)
            
            display_text = f"{self.trigger}{item}"
            is_selected = (i == self.selected_index)
            
            # Calculate available width for content
            inner_width = menu_width - 2  # Minus borders
            content_area = inner_width - self.left_pad - self.right_pad
            padded_text = display_text.ljust(content_area)[:content_area]  # Pad and clip
            
            # Render left padding
            for p in range(self.left_pad):
                buffer.set(self.x + 1 + p, curr_y, " ", bg=self.bg, reverse=is_selected)
            
            # Render content
            if is_selected:
                # Use reverse video for highlighting - works with any terminal background
                buffer.write_str(self.x + 1 + self.left_pad, curr_y, padded_text, 
                               fg=self.content_color, bg=self.bg, reverse=True)
            else:
                buffer.write_str(self.x + 1 + self.left_pad, curr_y, padded_text, 
                               fg=self.content_color, bg=self.bg)
            
            # Render right padding
            for p in range(self.right_pad):
                buffer.set(self.x + 1 + self.left_pad + content_area + p, curr_y, " ", 
                         bg=self.bg, reverse=is_selected)
            
            # Draw right border
            buffer.set(self.x + menu_width - 1, curr_y, "│", fg=self.frame_color, bg=self.bg)
        
        # Draw bottom border
        buffer.set(self.x, self.y + menu_height - 1, "└", fg=self.frame_color, bg=self.bg)
        for i in range(1, menu_width - 1):
            buffer.set(self.x + i, self.y + menu_height - 1, "─", fg=self.frame_color, bg=self.bg)
        buffer.set(self.x + menu_width - 1, self.y + menu_height - 1, "┘", fg=self.frame_color, bg=self.bg)

    def handle_input(self, event: Any) -> bool:
        if not self.is_visible:
            return False
            
        if event == '\x1b[A': # Up
            if self.filtered_items:
                self.selected_index = (self.selected_index - 1) % len(self.filtered_items)
                return True
        elif event == '\x1b[B': # Down
            if self.filtered_items:
                self.selected_index = (self.selected_index + 1) % len(self.filtered_items)
                return True
        elif event == '\t': # Tab -> Complete
            if self.filtered_items and self.on_select:
                completion = self.filtered_items[self.selected_index]
                if self.trigger == "/":
                    completion = self.trigger + completion
                self.on_select(completion)
                self.is_visible = False
                return True
        elif event == '\r' or event == '\n': # Enter -> Complete and submit
            if self.filtered_items and self.on_select:
                completion = self.filtered_items[self.selected_index]
                if self.trigger == "/":
                    completion = self.trigger + completion
                self.on_select(completion)
                self.is_visible = False
                return False  # Let Enter pass through to trigger submission
            self.is_visible = False
            return False
        elif event == '\x1b' or event == ' ': # Escape or Space -> Disable menu
            self.is_visible = False
            return False
            
        return False
