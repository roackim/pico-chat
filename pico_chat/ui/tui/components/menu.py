import math
import time
from typing import List, Optional, Any
from enum import Enum
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.fuzzy import fuzzy_search
from pico_chat.ui.tui.colors import RGB, theme


class SelectionMenu(Component):
    """A floating menu component for autocomplete/suggestions.
    
    Pure display and navigation component - doesn't know about commands,
    triggers, or business logic. Just displays items and handles selection.
    """
    
    def __init__(self, 
                 compositor: Optional[Any] = None,
                 id: Optional[str] = None, 
                 frame_color: RGB = None,
                 content_color: RGB = None,
                 left_pad: int = 1,
                 right_pad: int = 1,
                 max_height: int = 12):
        super().__init__(id)
        self.items: List[str] = []
        self.selected_index = 0
        self.frame_color = frame_color if frame_color is not None else theme.DEFAULT
        self.content_color = content_color if content_color is not None else self.frame_color
        self.bg = theme.get_bg()
        self.left_pad = left_pad
        self.right_pad = right_pad
        self.max_height = max_height
        self.is_visible = False
        self.display_prefix = ""  # Prefix to show (e.g., "/" for commands)
        
        # Compositor integration for auto-registration
        self.compositor = compositor
        self._registered_with_compositor = False

    def set_compositor(self, compositor):
        """Set compositor for auto-registration when menu is shown/hidden."""
        self.compositor = compositor
    
    def _update_compositor_registration(self):
        """Auto-register/unregister with compositor based on visibility."""
        if not self.compositor:
            return
        
        if self.is_visible and not self._registered_with_compositor:
            self.compositor.add_overlay(self)
            self._registered_with_compositor = True
        elif not self.is_visible and self._registered_with_compositor:
            self.compositor.remove_overlay(self)
            self._registered_with_compositor = False
    
    def update(self, all_items: List[str], search_term: str = "", display_prefix: str = ""):
        """Update menu with new items and optional search filter.
        
        Args:
            all_items: Complete list of items to choose from (raw, without prefixes)
            search_term: Optional search term to fuzzy filter items
            display_prefix: Prefix to show when rendering (e.g., "/" for commands)
        """
        self.display_prefix = display_prefix
        if not search_term:
            self.items = all_items
        else:
            # Fuzzy search
            results = fuzzy_search(search_term, all_items, threshold=0.01)
            self.items = [res[0] for res in results]
        
        # Show menu if we have items
        self.is_visible = len(self.items) > 0
        
        # Reset selection if out of bounds
        if self.selected_index >= len(self.items):
            self.selected_index = 0
        
        # Auto-register with compositor
        self._update_compositor_registration()
    
    def hide(self):
        """Hide the menu."""
        self.is_visible = False
        self.items = []
        self.selected_index = 0
        self.display_prefix = ""
        
        # Auto-unregister with compositor
        self._update_compositor_registration()
    
    def get_selected(self) -> Optional[str]:
        """Get the currently selected item."""
        if self.items and 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None
    
    def set_position_at(self, x: int, y: int):
        """Set menu position explicitly. Useful for positioning above trigger."""
        self._manual_x = x
        self._manual_y = y

    def render(self, buffer: Buffer):
        """Render the menu at its current position."""
        if not self.is_visible or not self.items:
            return

        # Calculate menu dimensions
        max_raw_len = max(len(self.display_prefix) + len(item) for item in self.items)
        menu_width = max_raw_len + self.left_pad + self.right_pad + 2  # +2 for borders
        menu_width = max(menu_width, 15)
        menu_width = min(menu_width, self.width)  # Respect parent width
        
        # Use max_height to limit visible items
        visible_count = min(len(self.items), self.max_height - 2)  # -2 for borders
        menu_height = visible_count + 2  # +2 for top and bottom borders
        
        # Draw the box with background
        buffer.set(self.x, self.y, "┌", fg=self.frame_color, bg=self.bg)
        for i in range(1, menu_width - 1):
            buffer.set(self.x + i, self.y, "─", fg=self.frame_color, bg=self.bg)
        buffer.set(self.x + menu_width - 1, self.y, "┐", fg=self.frame_color, bg=self.bg)
        
        # Render items
        for i in range(visible_count):
            item = self.items[i]
            curr_y = self.y + 1 + i
            
            # Draw left border
            buffer.set(self.x, curr_y, "│", fg=self.frame_color, bg=self.bg)
            
            is_selected = (i == self.selected_index)
            
            # Add display prefix to item
            display_text = f"{self.display_prefix}{item}"
            
            # Calculate available width for content
            inner_width = menu_width - 2  # Minus borders
            content_area = inner_width - self.left_pad - self.right_pad
            padded_text = display_text.ljust(content_area)[:content_area]  # Pad and clip
            
            # Render left padding
            for p in range(self.left_pad):
                buffer.set(self.x + 1 + p, curr_y, " ", bg=self.bg, reverse=is_selected)
            
            # Render content
            if is_selected:
                # Use reverse video for highlighting
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


    def action_up(self):
        """Move selection up."""
        if self.items:
            self.selected_index = (self.selected_index - 1) % len(self.items)
    
    def action_down(self):
        """Move selection down."""
        if self.items:
            self.selected_index = (self.selected_index + 1) % len(self.items)
    
    def get_selection(self) -> Optional[str]:
        """Get the currently selected item, or None if no items."""
        if self.items and 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None
