from dataclasses import dataclass
from typing import Optional, Any, List
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.buffer import Buffer, SubBuffer, Cell
from pico_chat.ui.tui.events import MouseEvent
from pico_chat.ui.tui.msg_types import MsgAction

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme

# Braille spinner frames for animating in-progress thinking.
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class SubBufferCellsProxy:
    """Proxy for cell access that translates absolute coordinates to SubBuffer-local."""

    def __init__(self, cells, x_offset, y_offset):
        self.cells = cells
        self.x_offset = x_offset
        self.y_offset = y_offset
        self._rows = {}

    def __getitem__(self, y):
        local_y = y - self.y_offset
        if 0 <= local_y < len(self.cells):
            row = self._rows.get(local_y)
            if row is None:
                row = SubBufferRowProxy(self.cells[local_y], self.x_offset)
                self._rows[local_y] = row
            return row
        return []


class SubBufferRowProxy:
    """Proxy for row access that translates x coordinates."""

    def __init__(self, row, x_offset):
        self.row = row
        self.x_offset = x_offset

    def __getitem__(self, x):
        local_x = x - self.x_offset
        if 0 <= local_x < len(self.row):
            return self.row[local_x]
        return Cell()


class SubBufferWrapper:
    """Buffer-compatible wrapper that redirects to a SubBuffer with coordinate translation."""

    def __init__(self, subbuffer, x_offset, y_offset):
        self.subbuffer = subbuffer
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.width = subbuffer.width
        self.height = subbuffer.height
        self.clip_rect = None
        self._cells_proxy = SubBufferCellsProxy(subbuffer.cells, x_offset, y_offset)

    @property
    def cells(self):
        return self._cells_proxy

    def set(self, x, y, char, fg=None, bg=None, bold=False, reverse=False):
        self.subbuffer.set(x - self.x_offset, y - self.y_offset, char, fg, bg, bold, reverse)

    def write_str(self, x, y, s, fg=None, bg=None, bold=False, reverse=False, max_width=None):
        self.subbuffer.write_str(x - self.x_offset, y - self.y_offset, s, fg, bg, bold, reverse, max_width)

    def fill(self, x, y, width, height, char=" ", fg=None, bg=None):
        self.subbuffer.fill(x - self.x_offset, y - self.y_offset, width, height, char, fg, bg)

    def set_clip(self, x, y, w, h):
        # Keep the clip in absolute coordinates (so children can compare against
        # their own x/y) while the subbuffer gets local coordinates.
        self.clip_rect = (x, y, w, h)
        self.subbuffer.set_clip(x - self.x_offset, y - self.y_offset, w, h)

    def clear_clip(self):
        self.clip_rect = None
        self.subbuffer.clear_clip()


class Box(Component):
    def __init__(self, child: Component, title: str = "", id: Optional[str] = None, bg=None, fg=None, focused: bool = False, actions: Optional[List] = None, parent_msg=None, compact_when_unfocused: bool = False, padding: int = 0, padding_y: Optional[int] = None, focus_in_padding: bool = False, focus_color=None, thread_mode: bool = False, gutter: str = "▸", gutter_color=None, lines_only: bool = False, title_provider: Optional[callable] = None, color_provider: Optional[callable] = None, content_pad_left: int = 0, content_pad_right: int = 0, full_height_gutter: bool = False):
        super().__init__(id)
        self.child = child
        self.child.parent = self
        self.parent_msg = parent_msg  # Reference to parent Message if provided
        self.title = title
        self._title_provider = title_provider  # Optional callable -> current title
        self._color_provider = color_provider  # Optional callable -> current fg color
        self.bg = bg
        self.fg = fg
        self.focus_color = focus_color
        self.focused = focused
        self.actions = actions or []
        self.focused_action_key = None
        self.compact_when_unfocused = compact_when_unfocused  # If True, render without borders when unfocused
        self.lines_only = lines_only  # If True, render only full-width top/bottom lines
        # Horizontal content padding is the default. Vertical padding is
        # opt-in; otherwise every compact form row would gain blank lines.
        self.padding = max(0, padding)
        self.padding_y = max(0, 0 if padding_y is None else padding_y)
        self.focus_in_padding = focus_in_padding
        # Thread mode: borderless chat-thread rendering with a role gutter.
        self.thread_mode = thread_mode
        self.gutter = gutter
        self.gutter_color = gutter_color
        # Thread mode: horizontal padding applied to the content once, inside
        # the box (content components render unpadded).
        self.content_pad_left = max(0, content_pad_left)
        self.content_pad_right = max(0, content_pad_right)
        # Thread mode: draw the gutter glyph on every row (a full-height bar),
        # not just the first line.
        self.full_height_gutter = full_height_gutter
        
        if self.bg is None: self.bg = theme.get_bg()
        if self.fg is None: self.fg = theme.DEFAULT
        
        # SubBuffer for efficient rendering
        self.subbuffer: Optional[SubBuffer] = None
        self._sub_valid = False  # True once the SubBuffer holds a full frame
        self._grew_from: Optional[int] = None  # pre-growth height of the SubBuffer
        self._last_size = (0, 0)  # Track size changes

        # Optional in-place editor (replaces child rendering while active)
        self.inline_editor = None

        # Hit regions for clickable actions in the bottom border
        # List of (local_x_start, local_x_end, MsgAction)
        # Populated during render; action click detection is handled by ChatHistoryPanel.
        self._action_hit_regions: List[tuple[int, int, MsgAction]] = []

    @property
    def children(self):
        return [self.child]

    @property
    def current_title(self) -> str:
        """Resolve the title, honoring a dynamic title_provider if set."""
        if self._title_provider is not None:
            return self._title_provider() or self.title
        return self.title

    @property
    def current_fg_color(self):
        """Resolve the foreground color, honoring a dynamic color_provider."""
        if self._color_provider is not None:
            return self._color_provider() or self.fg
        return self.fg
    
    def set_focused(self, focused: bool):
        """Set the focused state of this box."""
        if self.focused != focused:
            self.focused = focused
            self.mark_changed()  # Focus changes appearance

    def set_layout(self, x: int, y: int, width: int, height: int):
        old_size = (self.width, self.height)
        size_changed = old_size != (width, height)

        if self.focus_in_padding and hasattr(self.child, "fields"):
            fields = getattr(self.child, "all_fields", self.child.fields)
            for field in fields:
                field.suppress_focus_marker = True

        # In thread mode, no borders - child is inset by the gutter width (1 col)
        # so content flows to the right of the role gutter. When focused with
        # actions, the child is one row shorter so the action line sits below.
        if self.thread_mode:
            gutter_w = 1
            pad_l = self.content_pad_left
            pad_r = self.content_pad_right
            has_actions = bool(self._visible_actions())
            child_h = max(0, height - (1 if has_actions else 0))
            child_x = x + gutter_w + pad_l
            child_w = max(0, width - gutter_w - pad_l - pad_r)
            if size_changed:
                super().set_layout(x, y, width, height)
                self.child.set_layout(child_x, y, child_w, child_h)
            else:
                self.x = x
                self.y = y
                self.width = width
                self.height = height
                self.child.x = child_x
                self.child.y = y
                self.child.width = child_w
                self.child.height = child_h
        # In compact mode when unfocused, no borders - child gets full size
        elif self.compact_when_unfocused and not self.focused:
            if size_changed:
                super().set_layout(x, y, width, height)
                self.child.set_layout(x, y, width, height)
            else:
                self.x = x
                self.y = y
                self.width = width
                self.height = height
                self.child.x = x
                self.child.y = y
                self.child.width = width
                self.child.height = height
        # Lines-only mode: only full-width top/bottom lines, child inset by 1
        # vertically and 1 column right (to clear the ">" prefix), no walls.
        elif self.lines_only:
            inset_x = 1 + self.padding
            inset_y = 1 + self.padding_y
            if size_changed:
                super().set_layout(x, y, width, height)
                self.child.set_layout(x + inset_x, y + inset_y,
                                      width - inset_x - self.padding,
                                      height - 2 * inset_y)
            else:
                self.x = x
                self.y = y
                self.width = width
                self.height = height
                self.child.x = x + inset_x
                self.child.y = y + inset_y
                self.child.width = width - inset_x - self.padding
                self.child.height = height - 2 * inset_y
        else:
            # Normal mode with borders
            if size_changed:
                super().set_layout(x, y, width, height)
                inset_x = 1 + self.padding
                inset_y = 1 + self.padding_y
                self.child.set_layout(x + inset_x, y + inset_y,
                                      width - 2 * inset_x, height - 2 * inset_y)
            else:
                self.x = x
                self.y = y
                self.width = width
                self.height = height
                inset_x = 1 + self.padding
                inset_y = 1 + self.padding_y
                self.child.x = x + inset_x
                self.child.y = y + inset_y
                self.child.width = width - 2 * inset_x
                self.child.height = height - 2 * inset_y
        
        # Initialize or resize SubBuffer if size changed
        if size_changed:
            if self.subbuffer is None:
                self.subbuffer = SubBuffer(width, height)
                self._sub_valid = False
            elif width != self.subbuffer.width:
                # Width change rewraps content: full rebuild.
                self.subbuffer = SubBuffer(width, height)
                self._sub_valid = False
            elif height < self.subbuffer.height:
                self.subbuffer.shrink(height)
            elif height > self.subbuffer.height:
                # Append-only growth keeps the already-rasterized prefix, but
                # remember the pre-growth height: if the dirty tail starts below
                # it (e.g. a shrink+grow), the re-added rows lack a gutter and
                # need a full redraw.
                self._grew_from = self.subbuffer.height
                self.subbuffer.grow(height)
            self.mark_changed()
            self._last_size = (width, height)
        
        # Update blit position (free for scrolling!)
        if self.subbuffer:
            self.subbuffer.set_position(x, y)

        # Keep inline editor layout in sync with the box inner area,
        # honouring the parent message's left/right padding if available.
        if self.inline_editor is not None:
            lpad = getattr(self.parent_msg, 'left_pad', 0) if self.parent_msg else 0
            rpad = getattr(self.parent_msg, 'right_pad', 0) if self.parent_msg else 0
            inset_x = 1 + self.padding
            inset_y = 1 + self.padding_y
            ex = x + inset_x + lpad
            ew = max(1, width - 2 * inset_x - lpad - rpad)
            self.inline_editor.set_layout(ex, y + inset_y, ew,
                                           max(1, height - 2 * inset_y))

    def _visible_actions(self):
        """Actions this box should render.

        A parent message can opt out of inline actions by setting
        ``inline_actions = False``; such messages surface their actions through
        the app's bottom mode line instead.
        """
        if self.parent_msg is not None:
            if not getattr(self.parent_msg, "inline_actions", True):
                return []
            return self.parent_msg.get_active_actions() if self.focused else []
        return self.actions if self.focused else []

    def get_preferred_height(self, width: int) -> int:
        """Box adds 2 rows of height for borders (top/bottom), unless in compact unfocused or thread mode."""
        if self.inline_editor is not None:
            lpad = getattr(self.parent_msg, 'left_pad', 0) if self.parent_msg else 0
            rpad = getattr(self.parent_msg, 'right_pad', 0) if self.parent_msg else 0
            inner_w = max(1, width - 2 - 2 * self.padding - lpad - rpad)
            return self.inline_editor.get_preferred_height(inner_w) + 2 + 2 * self.padding_y
        if hasattr(self.child, 'get_preferred_height'):
            # Collapsed messages render a single summary line.
            if self.parent_msg is not None and getattr(self.parent_msg, "collapsed", False):
                return 1
            # In thread mode, no borders; child width is reduced by the gutter.
            # A focused message with actions gains one extra row for the action
            # line below the content, which pushes subsequent messages down.
            if self.thread_mode:
                inner_w = max(1, width - 1 - self.content_pad_left - self.content_pad_right)
                base = self.child.get_preferred_height(inner_w)
                if self._visible_actions():
                    return base + 1
                return base
            # In compact mode when unfocused, no borders
            if self.compact_when_unfocused and not self.focused:
                return self.child.get_preferred_height(width)
            # Height of child inside the box plus top/bottom borders.
            # Child's width inside box is box_width - 2.
            inner_height = self.child.get_preferred_height(width - 2 - 2 * self.padding)
            return inner_height + 2 + 2 * self.padding_y
        # Otherwise fall back to a reasonable default or 0
        return 0
    
    def mark_changed(self, rect: Optional[tuple[int, int, int, int]] = None):
        """Mark this box as needing re-rendering."""
        super().mark_changed(rect if rect is not None else (self.x, self.y, self.width, self.height))
        if self.subbuffer:
            self.subbuffer.mark_changed()

    def render(self, buffer: Buffer):
        # Skip if too small - but compact and thread modes can be 1x1
        min_size = 1 if (self.compact_when_unfocused and not self.focused) or self.thread_mode else 2
        if self.width < min_size or self.height < min_size:
            return
        
        # Ensure SubBuffer exists
        if self.subbuffer is None:
            self.subbuffer = SubBuffer(self.width, self.height)
            self.subbuffer.set_position(self.x, self.y)
            self.mark_changed()
        
        # Phase 1: Render to SubBuffer if changed
        if self.subbuffer.has_changed or not self._sub_valid:
            dirty_from = None
            if self._sub_valid:
                target = self.inline_editor if self.inline_editor is not None else self.child
                taker = getattr(target, "take_dirty_from_line", None)
                if callable(taker):
                    dirty_from = taker()
                # Growth from a lower height means the tail may start above the
                # re-added rows; a full redraw is required then.
                if (dirty_from is not None and self._grew_from is not None
                        and dirty_from > self._grew_from):
                    dirty_from = None
            self._render_to_subbuffer(dirty_from)
            self.subbuffer.has_changed = False
            self._sub_valid = True
            self._grew_from = None
        
        # Phase 2: Blit SubBuffer to main buffer (always happens, position updates are free!)
        self.subbuffer.blit(buffer, clip_rect=getattr(buffer, 'clip_rect', None))

        # Optional focus gutter: containers may keep their content unindented
        # while the focus arrow occupies the Box padding immediately to the
        # left of the focused child.
        if self.focus_in_padding and self.padding > 0:
            focused = getattr(self.child, "get_focused_field", lambda: None)()
            if focused is not None and getattr(focused, "focused", False):
                buffer.write_str(self.child.x - 1, focused.y, "▸",
                                 fg=theme.FOCUSED, max_width=1)
        
        # Phase 3: Render cursor overlay (outside SubBuffer caching)
        cursor_target = self.inline_editor if self.inline_editor is not None else self.child
        if hasattr(cursor_target, 'render_cursor'):
            cursor_target.render_cursor(buffer)
    
    def _render_to_subbuffer(self, dirty_from: Optional[int] = None):
        """Render box content to its SubBuffer using local coordinates (0,0).

        ``dirty_from`` is the first content row that changed (append-only tail
        raster); other modes ignore it and redraw fully.
        """
        # A previous incremental render may have left a clip on the shared
        # SubBuffer; never draw the frame's clear/gutter under it.
        self.subbuffer.clear_clip()
        # Get values from parent_msg if available, otherwise use direct attributes
        if self.parent_msg:
            title = self.parent_msg.title
            fg = self.parent_msg.frame_color
            actions = self._visible_actions()
        else:
            title = self.current_title
            fg = self.fg
            actions = self.actions
        
        bg = self.bg
        
        # Thread mode: borderless chat-thread rendering with a role gutter
        if self.thread_mode:
            self._render_thread_to_subbuffer(dirty_from)
            return

        # Compact mode: render without borders when unfocused
        if self.compact_when_unfocused and not self.focused:
            self._render_compact_to_subbuffer()
            return

        # Lines-only mode: just full-width horizontal bars on top and bottom,
        # no vertical walls and no corner characters.
        if self.lines_only:
            self._render_lines_only_to_subbuffer()
            return
        
        if self.focused:
            fg = self.focus_color or theme.FOCUSED
        
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
        render_target = self.inline_editor if self.inline_editor is not None else self.child
        render_target.render(temp_buffer)

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
        if actions:
            actions_str = " ".join(action.format() for action in actions)
            bottom_content_parts.append(f" {actions_str} ")
        
        # Reset hit regions (only valid when focused with actions)
        self._action_hit_regions = []
        
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
                
                # Record action hit regions (local SubBuffer coordinates)
                if actions and self.focused:
                    actions_start_in_str = 0
                    if len(bottom_content_parts) == 2:
                        actions_start_in_str = len(bottom_content_parts[0]) + len("│")
                    # Each action occupies "[key] label " (with trailing space).
                    # The action block has one separator space before its first
                    # label; regions begin on the visible action text.
                    x_offset = left_border_width + 1 + actions_start_in_str + 1
                    flash_key = getattr(self.parent_msg, '_flash_action_key', None)
                    for action in actions:
                        formatted = action.format()
                        region_start = x_offset
                        region_end = x_offset + len(formatted)
                        self._action_hit_regions.append((region_start, region_end, action))
                        # Flash feedback: overwrite this action's cells with reverse
                        if ((flash_key and action.key == flash_key)
                            or action.key == self.focused_action_key):
                            for fx in range(region_start, region_end):
                                self.subbuffer.set(fx, self.height - 1,
                                                   self.subbuffer.cells[self.height - 1][fx].char,
                                                   fg=fg, bg=bg, reverse=True)
                        x_offset += len(formatted) + 1  # +1 for the space separator
                
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
    
    def _render_compact_to_subbuffer(self):
        """Render in compact mode: no borders, just content."""
        bg = self.bg
        
        # Clear SubBuffer
        self.subbuffer.clear()
        
        # Fill background
        if bg:
            for iy in range(self.height):
                for ix in range(self.width):
                    self.subbuffer.set(ix, iy, " ", bg=bg)
        
        # Render child content directly (no border offset)
        temp_buffer = self._create_subbuffer_wrapper()
        self.child.render(temp_buffer)

    def _render_lines_only_to_subbuffer(self):
        """Render only full-width horizontal bars on the top and bottom edges.

        No corner characters and no vertical walls — just a clean top and
        bottom line spanning the full width. The current title (mode) is drawn
        inline in the top bar, and a ``>`` prompt prefix sits in the first
        content column.
        """
        if self.focused and self.focus_color:
            fg = self.focus_color
        elif self._color_provider:
            fg = self._color_provider()
        else:
            fg = self.fg
        bg = self.bg

        self.subbuffer.clear()

        # Fill background
        if bg:
            for iy in range(self.height):
                for ix in range(self.width):
                    self.subbuffer.set(ix, iy, " ", bg=bg)

        # Top horizontal bar, full width.
        for ix in range(self.width):
            self.subbuffer.set(ix, 0, "─", fg=fg, bg=bg)

        # Section name (mode) inline in the top bar: "─ message ───...".
        title = self.current_title
        if title:
            title_str = f" {title[:max(0, self.width - 4)]} "
            self.subbuffer.write_str(1, 0, title_str, fg=fg, bg=bg)

        # Bottom horizontal bar, full width.
        for ix in range(self.width):
            self.subbuffer.set(ix, self.height - 1, "─", fg=fg, bg=bg)

        # Prompt prefix ("▸") in the first content column, matching the role
        # gutter used for chat-history messages in thread mode.
        if self.width > 1 and self.height > 2:
            self.subbuffer.set(0, 1, "▸", fg=fg, bg=bg)

        # Render child content (inset by the layout previously computed).
        temp_buffer = self._create_subbuffer_wrapper()
        self.child.render(temp_buffer)

    def _render_thread_to_subbuffer(self, dirty_from: Optional[int] = None):
        """Render in thread mode: borderless content with a role gutter.

        The gutter (e.g. ▸ for assistant, ❯ for user) is drawn in the first
        column, colored by the message's frame color. Content flows to the
        right. When focused, actions render on the last row.

        When ``dirty_from`` is set, only rows from that content line down are
        cleared and re-rasterized (append-only streaming); the unchanged prefix
        is kept from the previous frame.
        """
        bg = self.bg
        fg = self.gutter_color or self.fg

        # Lifecycle-aware gutter: tool/permission messages swap their prefix
        # glyph with the running/done state (spinner → ✓/✗/⏹, ? for ask).
        gutter = self.gutter
        if self.parent_msg is not None and hasattr(self.parent_msg, "dynamic_gutter"):
            gutter, dynamic_color = self.parent_msg.dynamic_gutter()
            fg = dynamic_color or fg

        # Collapsed messages and non-thread modes always redraw fully.
        collapsed = self.parent_msg is not None and getattr(self.parent_msg, "collapsed", False)
        incremental = (
            dirty_from is not None
            and dirty_from > 0
            and not collapsed
            and dirty_from < self.height
        )

        if incremental:
            start = dirty_from
            self.subbuffer.clear_region(0, start, self.width, self.height - start)
        else:
            start = 0
            self.subbuffer.clear()

        # Fill background
        if bg:
            for iy in range(start, self.height):
                for ix in range(self.width):
                    self.subbuffer.set(ix, iy, " ", bg=bg)

        # Draw the role gutter in the first column. User/pico messages use a
        # full-height prefix bar (every row); status gutters stay on row 0.
        if gutter and self.width > 0:
            if self.full_height_gutter:
                rows = range(start, self.height)
            else:
                rows = (0,) if start == 0 else ()
            for row in rows:
                self.subbuffer.set(0, row, gutter, fg=fg, bg=bg)

        # Collapsed messages (e.g. thinking folded by default) render a single
        # summary line instead of the full content.
        if collapsed:
            self._render_collapsed_line()
            return

        # Render child content (no border offset). For incremental raster, clip
        # to the dirty band so the child skips unchanged lines.
        temp_buffer = self._create_subbuffer_wrapper()
        if incremental:
            temp_buffer.set_clip(self.x, self.y + start, self.width, self.height - start)
        self.child.render(temp_buffer)

        # Actions on a dedicated row below the content when focused. This row
        # is part of the box height (see get_preferred_height), so it pushes
        # subsequent messages down rather than overlaying content.
        if self.parent_msg is not None or self.focused:
            actions = self._visible_actions()
            if actions:
                actions_str = " ".join(action.format() for action in actions)
                self.subbuffer.write_str(2, self.height - 1, actions_str,
                                         fg=theme.FOCUSED, bg=bg, max_width=max(0, self.width - 2))
                # Record hit regions for mouse clicks.
                self._action_hit_regions = []
                x_offset = 2
                for action in actions:
                    formatted = action.format()
                    self._action_hit_regions.append((x_offset, x_offset + len(formatted), action))
                    x_offset += len(formatted) + 1

    def _render_collapsed_line(self):
        """Render a single summary line for a collapsed message.

        Shows an animated spinner while the message is not finalized, then a
        static marker once finalized.
        """
        bg = self.bg
        parent = self.parent_msg
        text = parent._collapsed_text()

        # The gutter already marks the role (… for thinking), so the collapsed
        # line shows the spinner + label while streaming, then a completion
        # marker + "thoughts" once finalized.
        if not parent.finalized:
            frame = SPINNER_FRAMES[parent.spinner_frame % len(SPINNER_FRAMES)]
            line = f"{frame} {text}"
        else:
            done_glyph, done_color = parent.done_glyph()
            line = f"{done_color}{done_glyph}{theme.reset()} {parent.done_label(text)}"

        self.subbuffer.write_str(2, 0, line, fg=self.gutter_color or self.fg,
                                 bg=bg, max_width=max(0, self.width - 2))

    def _create_subbuffer_wrapper(self):
        """Create a Buffer-compatible wrapper redirecting to this Box's SubBuffer."""
        return SubBufferWrapper(self.subbuffer, self.x, self.y)

    def handle_input(self, event: Any) -> bool:
        """Pass input to child, but check mouse bounds for the box area."""
        if isinstance(event, MouseEvent):
            if self.x <= event.x < self.x + self.width and \
               self.y <= event.y < self.y + self.height:
                return self.child.handle_input(event)
            return False
        return self.child.handle_input(event)
