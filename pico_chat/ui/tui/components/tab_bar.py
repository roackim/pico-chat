"""Tab bar component for multi-conversation support."""

from dataclasses import dataclass, field
from typing import List, Optional, Callable
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.events import MouseEvent
from pico_chat.ui.tui.colors import theme, RGB


@dataclass
class Tab:
    """Represents a single tab."""
    id: int
    name: str
    closeable: bool = True


class TabBar(Component):
    """Single-line tab bar rendered at the top of the UI.
    
    Renders tabs as: " chat [x]  debug [x] ___"
    Active tab is highlighted with reverse video; [x] button closes the tab on click.
    First tab gets [x] only when there are 2+ tabs.
    Underline fills remaining space.
    """
    
    def __init__(self, id: Optional[str] = None):
        super().__init__(id)
        self.tabs: List[Tab] = []
        self.active_index: int = 0
        self._on_select: Optional[Callable[[int], None]] = None   # callback(tab_index)
        self._on_close: Optional[Callable[[int], None]] = None    # callback(tab_index)
        self._on_new: Optional[Callable[[], None]] = None         # callback()
        # Click regions: list of (x_start, x_end, tab_index, is_close_button)
        self._click_regions: List[tuple[int, int, int, bool]] = []
        self._new_btn_region: Optional[tuple[int, int]] = None    # (x_start, x_end)
    
    def set_callbacks(self, on_select: Callable[[int], None], on_close: Callable[[int], None], on_new: Callable[[], None]):
        """Set tab selection, close, and new-tab callbacks."""
        self._on_select = on_select
        self._on_close = on_close
        self._on_new = on_new
    
    def add_tab(self, name: str, closeable: bool = True) -> int:
        """Add a new tab, return its id."""
        tab_id = len(self.tabs)
        self.tabs.append(Tab(id=tab_id, name=name, closeable=closeable))
        self.mark_changed()
        return tab_id

    def insert_tab(self, index: int, name: str, closeable: bool = True) -> int:
        """Insert a tab at an existing tab-strip position."""
        index = max(0, min(index, len(self.tabs)))
        tab_id = len(self.tabs)
        self.tabs.insert(index, Tab(id=tab_id, name=name, closeable=closeable))
        self.mark_changed()
        return tab_id
    
    def remove_tab(self, index: int):
        """Remove tab at index."""
        if 0 <= index < len(self.tabs):
            self.tabs.pop(index)
            # Adjust active index
            if self.active_index >= len(self.tabs):
                self.active_index = max(0, len(self.tabs) - 1)
            elif self.active_index > index:
                self.active_index -= 1
            self.mark_changed()
    
    def set_active(self, index: int):
        """Set the active tab by index."""
        if 0 <= index < len(self.tabs) and index != self.active_index:
            self.active_index = index
            self.mark_changed()
    
    def rename_tab(self, index: int, name: str):
        """Rename a tab."""
        if 0 <= index < len(self.tabs):
            self.tabs[index].name = name
            self.mark_changed()
    
    def get_preferred_height(self, width: int) -> int:
        return 1

    def set_layout(self, x: int, y: int, width: int, height: int):
        old_layout = (self.x, self.y, self.width, self.height)
        super().set_layout(x, y, width, height)
        if old_layout != (x, y, width, height):
            self._click_regions = []
            self._new_btn_region = None
    
    def render(self, buffer: Buffer):
        """Render tab bar as a single line."""
        self._click_regions = []
        self._new_btn_region = None
        x = self.x
        remaining = self.width
        
        for i, tab in enumerate(self.tabs):
            is_active = (i == self.active_index)
            
            # Build tab label: " name " and close button " × "
            label = f" {tab.name}"
            close_btn = " × "
            
            # Calculate width needed
            tab_width = len(label) + len(close_btn)
            if tab_width > remaining:
                break
            
            # Colors
            if is_active:
                fg = theme.DEFAULT
                fgb = theme.DEFAULT
            else:
                fg = theme.MUTED
                fgb = theme.MUTED
            
            # Render tab label
            buffer.write_str(x, self.y, label, fg=fg, bg=None, reverse=True, max_width=len(label))
            
            # Register click region for tab label
            self._click_regions.append((x, x + len(label), i, False))
            x += len(label)
            remaining -= len(label)
            
            # Render close button (same colors as header)
            buffer.write_str(x, self.y, close_btn, fg=fgb, bg=None, reverse=True, max_width=len(close_btn))
            self._click_regions.append((x, x + len(close_btn), i, True))
            x += len(close_btn)
            remaining -= len(close_btn)
        
        # Render "+" button in focused color
        new_btn = " + "
        if len(new_btn) <= remaining:
            buffer.write_str(x, self.y, new_btn, fg=theme.FOCUSED, bg=None, reverse=True, max_width=len(new_btn))
            self._new_btn_region = (x, x + len(new_btn))
            x += len(new_btn)
            remaining -= len(new_btn)
        
        # Fill remaining space with ▁ (lower block)
        if remaining > 0:
            fill_text = "▁" * remaining
            buffer.write_str(x, self.y, fill_text, fg=theme.MUTED, bg=theme.get_bg(), max_width=remaining)
    
    def handle_input(self, event) -> bool:
        """Handle mouse clicks on tabs."""
        if isinstance(event, MouseEvent) and event.pressed and event.button == 0 \
            and self.y <= event.y < self.y + self.height:
            # Check "+" button first
            if self._new_btn_region:
                x_start, x_end = self._new_btn_region
                if x_start <= event.x < x_end:
                    if self._on_new:
                        self._on_new()
                    return True
            # Check tab regions
            for x_start, x_end, tab_index, is_close in self._click_regions:
                if x_start <= event.x < x_end:
                    if is_close:
                        if self.tabs[tab_index].closeable and self._on_close:
                            self._on_close(tab_index)
                    else:
                        if self._on_select:
                            self._on_select(tab_index)
                    return True
        return False
