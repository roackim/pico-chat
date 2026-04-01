from dataclasses import dataclass
from typing import Optional, Any, List
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer, SubBuffer
from pico_chat.ui.tui.terminal import MouseEvent

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme

class Box(Component):
    def __init__(self, child: Component, title: str = "", id: Optional[str] = None, bg=None, fg=None, focused: bool = False, actions: Optional[List] = None, parent_msg=None):
        super().__init__(id)
        self.child = child
        self.child.parent = self
        self.parent_msg = parent_msg  # Reference to parent Message if provided
        self.title = title
        self.bg = bg
        self.fg = fg
        self.focused = focused
        self.actions = actions or []
        
        if self.bg is None: self.bg = theme.get_bg()
        if self.fg is None: self.fg = theme.DEFAULT
        
        # SubBuffer for efficient rendering
        self.subbuffer: Optional[SubBuffer] = None
        self._last_size = (0, 0)  # Track size changes

    @property
    def children(self):
        return [self.child]
    
    def set_focused(self, focused: bool):
        """Set the focused state of this box."""
        if self.focused != focused:
            self.focused = focused
            self.mark_changed()  # Focus changes appearance

    def set_layout(self, x: int, y: int, width: int, height: int):
        super().set_layout(x, y, width, height)
        self.child.set_layout(x + 1, y + 1, width - 2, height - 2)
        
        # Initialize or resize SubBuffer if size changed
        if (width, height) != self._last_size:
            if self.subbuffer is None:
                self.subbuffer = SubBuffer(width, height)
            elif width != self.subbuffer.width or height != self.subbuffer.height:
                # Size changed - recreate SubBuffer (grow not applicable here)
                self.subbuffer = SubBuffer(width, height)
            self.mark_changed()
            self._last_size = (width, height)
        
        # Update blit position (free for scrolling!)
        if self.subbuffer:
            self.subbuffer.set_position(x, y)

    def get_preferred_height(self, width: int) -> int:
        """Box adds 2 rows of height for borders (top/bottom)."""
        if hasattr(self.child, 'get_preferred_height'):
            # Height of child inside the box plus top/bottom borders.
            # Child's width inside box is box_width - 2.
            inner_height = self.child.get_preferred_height(width - 2)
            return inner_height + 2
        # Otherwise fall back to a reasonable default or 0
        return 0
    
    def mark_changed(self):
        """Mark this box as needing re-rendering."""
        if self.subbuffer:
            self.subbuffer.mark_changed()

    def render(self, buffer: Buffer):
        if self.width < 2 or self.height < 2:
            return
        
        # Ensure SubBuffer exists
        if self.subbuffer is None:
            self.subbuffer = SubBuffer(self.width, self.height)
            self.subbuffer.set_position(self.x, self.y)
            self.mark_changed()
        
        # Phase 1: Render to SubBuffer if changed
        if self.subbuffer.has_changed:
            self._render_to_subbuffer()
            self.subbuffer.has_changed = False
        
        # Phase 2: Blit SubBuffer to main buffer (always happens, position updates are free!)
        self.subbuffer.blit(buffer)
        
        # Phase 3: Render cursor overlay for InputComponent (outside SubBuffer caching)
        if hasattr(self.child, 'render_cursor'):
            self.child.render_cursor(buffer)
    
    def _render_to_subbuffer(self):
        """Render box content to its SubBuffer using local coordinates (0,0)."""
        # Get values from parent_msg if available, otherwise use direct attributes
        if self.parent_msg:
            title = self.parent_msg.title
            fg = self.parent_msg.frame_color
            actions = self.parent_msg.get_active_actions()
        else:
            title = self.title
            fg = self.fg
            actions = self.actions
        
        bg = self.bg
        
        if self.focused:
            fg = theme.FOCUSED
        
        @dataclass(frozen=True)
        class BorderStyle:
            tl: str  # top-left
            tr: str  # top-right
            bl: str  # bottom-left
            br: str  # bottom-right
            h: str   # horizontal
            v: str   # vertical
            
        STYLES = {
            "square":  BorderStyle("┌", "┐", "└", "┘", "─", "│"),
            "double":  BorderStyle("╔", "╗", "╚", "╝", "═", "║"),
            "ascii":   BorderStyle("+", "+", "+", "+", "-", "|"),
            "rounded": BorderStyle("╭", "╮", "╰", "╯", "─", "│"),
        }

        # Use focused style if box is focused, otherwise use normal style
        style_name = pico_cfg.config.ui_box_style_focused if self.focused else pico_cfg.config.ui_box_style
        style = STYLES[style_name]

        # Clear SubBuffer
        self.subbuffer.clear()
        
        # Render using local coordinates (0, 0) within SubBuffer
        # 1. Top + Left borders
        self.subbuffer.set(0, 0, style.tl, fg=fg, bg=bg)

        for i in range(1, self.width - 1):
            self.subbuffer.set(i, 0, style.h, fg=fg, bg=bg)

        for i in range(1, self.height - 1):
            self.subbuffer.set(0, i, style.v, fg=fg, bg=bg)

        # 2. Background
        if self.bg:
            for iy in range(1, self.height - 1):
                for ix in range(1, self.width - 1):
                    self.subbuffer.set(ix, iy, " ", bg=bg)

        # 3. Content - render child to SubBuffer
        # Note: child still uses absolute coordinates from set_layout
        # We need to create a temporary buffer that maps to our SubBuffer
        # For now, create a wrapper buffer that redirects to SubBuffer
        temp_buffer = self._create_subbuffer_wrapper()
        self.child.render(temp_buffer)

        # 4. Bottom + Right borders
        for i in range(1, self.height - 1):
            self.subbuffer.set(self.width - 1, i, style.v, fg=fg, bg=bg)

        # Bottom border with metrics (above actions) and actions
        metrics_str = None
        if self.parent_msg and hasattr(self.parent_msg, 'should_show_metrics') and self.parent_msg.should_show_metrics():
            metrics_str = self.parent_msg.get_metrics_string()
        
        # Build bottom line content: metrics, then actions
        bottom_content_parts = []
        if metrics_str:
            bottom_content_parts.append(f" {metrics_str} ")
        if actions and self.focused:
            actions_str = " ".join(action.format() for action in actions)
            bottom_content_parts.append(f" {actions_str} ")
        
        if bottom_content_parts:
            # Join metrics and actions with separator if both exist
            if len(bottom_content_parts) == 2:
                bottom_str = bottom_content_parts[0] + "│" + bottom_content_parts[1]
            else:
                bottom_str = bottom_content_parts[0]
            
            bottom_width = len(bottom_str)
            
            # Calculate how much space we have for the bottom border
            available_width = self.width - 3
            
            if bottom_width <= available_width:
                # Draw left part of bottom border
                left_border_width = available_width - bottom_width
                for i in range(1, left_border_width + 1):
                    self.subbuffer.set(i, self.height - 1, style.h, fg=fg, bg=bg)
                
                # Draw combined string
                self.subbuffer.write_str(left_border_width + 1, self.height - 1, bottom_str, fg=fg, bg=bg)
                
                # Draw one more border char on the right before the corner
                self.subbuffer.set(self.width - 2, self.height - 1, style.h, fg=fg, bg=bg)
            else:
                # Content too long, just draw normal border
                for i in range(1, self.width - 1):
                    self.subbuffer.set(i, self.height - 1, style.h, fg=fg, bg=bg)
        else:
            # No content, draw normal bottom border
            for i in range(1, self.width - 1):
                self.subbuffer.set(i, self.height - 1, style.h, fg=fg, bg=bg)

        # Corners
        self.subbuffer.set(self.width - 1, 0, style.tr, fg=fg, bg=bg)
        self.subbuffer.set(0, self.height - 1, style.bl, fg=fg, bg=bg)
        self.subbuffer.set(self.width - 1, self.height - 1, style.br, fg=fg, bg=bg)

        # Title
        if title:
            title_str = f" {title[:self.width-4]} "
            self.subbuffer.write_str(2, 0, title_str, fg=fg, bg=bg)
    
    def _create_subbuffer_wrapper(self):
        """Create a Buffer-compatible wrapper that redirects to SubBuffer with coordinate translation."""
        class SubBufferWrapper:
            def __init__(self, subbuffer, x_offset, y_offset):
                self.subbuffer = subbuffer
                self.x_offset = x_offset
                self.y_offset = y_offset
                self.width = subbuffer.width
                self.height = subbuffer.height
            
            @property
            def cells(self):
                """Expose subbuffer cells - note: direct indexing uses absolute coords and needs translation."""
                # Return a proxy object that translates coordinates
                return SubBufferCellsProxy(self.subbuffer.cells, self.x_offset, self.y_offset)
            
            def set(self, x, y, char, fg=None, bg=None, bold=False, reverse=False):
                # Translate from absolute coordinates to SubBuffer-local coordinates
                local_x = x - self.x_offset
                local_y = y - self.y_offset
                self.subbuffer.set(local_x, local_y, char, fg, bg, bold, reverse)
            
            def write_str(self, x, y, s, fg=None, bg=None, bold=False, reverse=False, max_width=None):
                local_x = x - self.x_offset
                local_y = y - self.y_offset
                self.subbuffer.write_str(local_x, local_y, s, fg, bg, bold, reverse, max_width)
            
            def fill(self, x, y, width, height, char=" ", fg=None, bg=None):
                local_x = x - self.x_offset
                local_y = y - self.y_offset
                self.subbuffer.fill(local_x, local_y, width, height, char, fg, bg)
            
            def set_clip(self, x, y, w, h):
                pass  # Not implemented for SubBuffer
            
            def clear_clip(self):
                pass  # Not implemented for SubBuffer
        
        class SubBufferCellsProxy:
            """Proxy for cell access that translates absolute coordinates to SubBuffer-local."""
            def __init__(self, cells, x_offset, y_offset):
                self.cells = cells
                self.x_offset = x_offset
                self.y_offset = y_offset
            
            def __getitem__(self, y):
                """Return a row proxy that translates x coordinates."""
                local_y = y - self.y_offset
                if 0 <= local_y < len(self.cells):
                    return SubBufferRowProxy(self.cells[local_y], self.x_offset)
                # Return empty row if out of bounds
                return []
        
        class SubBufferRowProxy:
            """Proxy for row access that translates x coordinates."""
            def __init__(self, row, x_offset):
                self.row = row
                self.x_offset = x_offset
            
            def __getitem__(self, x):
                """Get cell at translated x coordinate."""
                local_x = x - self.x_offset
                if 0 <= local_x < len(self.row):
                    return self.row[local_x]
                # Return empty cell if out of bounds
                from pico_chat.ui.tui.buffer import Cell
                return Cell()
        
        return SubBufferWrapper(self.subbuffer, self.x, self.y)

    def handle_input(self, event: Any) -> bool:
        """Pass input to child, but check mouse bounds for the box area."""
        if isinstance(event, MouseEvent):
            if self.x <= event.x < self.x + self.width and \
               self.y <= event.y < self.y + self.height:
                return self.child.handle_input(event)
            return False
        return self.child.handle_input(event)
