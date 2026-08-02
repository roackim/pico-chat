"""Chat history panel for the Pico-Chat TUI."""

import time
from dataclasses import dataclass
from typing import Optional, Any
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components import TextComponent
from pico_chat.ui.tui.container import Hsplit
from pico_chat.ui.tui.terminal import MouseEvent

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme, RGB
from pico_chat.ui.tui.msg_types import MsgType, MsgAction

from pico_chat.ui.chat_message import Message


WELCOME_MESSAGE = "Welcome to pico-chat!\n"


@dataclass
class SelectionState:
    """Tracks text selection within a message."""
    msg: Any                    # The Message object
    start_line: int = 0         # Display line index (0-based within message component)
    start_col: int = 0          # Display column index (0-based within wrapped line)
    end_line: int = 0
    end_col: int = 0

    def get_normalized(self) -> tuple[int, int, int, int]:
        """Return (start_line, start_col, end_line, end_col) with start <= end."""
        if (self.start_line, self.start_col) <= (self.end_line, self.end_col):
            return self.start_line, self.start_col, self.end_line, self.end_col
        return self.end_line, self.end_col, self.start_line, self.start_col


class ChatHistoryPanel(TextComponent):
    """Manages the chat history display panel with dynamic width support."""

    def __init__(self, max_width: int = 80):
        """Initialize the chat history panel.
        
        Args:
            max_width: Initial maximum width for message line wrapping
        """
        super().__init__("", id="history")
        self.messages = []
        self.max_width = max_width
        self.left_pad = pico_cfg.config.ui_msg_h_padding
        self.right_pad = pico_cfg.config.ui_msg_h_padding
        self.max_messages = 150  # Maximum number of messages to keep
        self.scroll_offset = 0   # How many rows to scroll up from the bottom
        self.auto_scroll = True
        self.anchored_start_y: Optional[int] = None  # Absolute Y position when scrolled up (for stability)
        self.focused_message_index: Optional[int] = None  # Index of the currently focused message
        self.has_keyboard_focus = False  # Track if this panel should handle keyboard input
        self._selection: Optional[SelectionState] = None  # Current text selection
        self._selection_dragging: bool = False  # Whether user is actively dragging to select
        # Cache for line map (invalidated on scroll, focus change, message add/remove)
        self._line_map_cache: Optional[list] = None
        self._line_map_cache_key: Optional[tuple] = None  # (auto_scroll, anchored_start_y, msg_count)
        
        # Action click feedback: flash an action with inverted colors briefly
        self._flash_msg: Optional[Message] = None
        self._flash_action_key: Optional[str] = None  # e.g. "c" for COPY
        self._flash_until: float = 0.0  # monotonic time when flash expires
        
        # Selection drag throttle: cap update+repaint rate during drag
        self._selection_throttle_interval: float = 0.050  # 30ms between repaints
        self._selection_last_update: float = 0.0  # last monotonic time we updated
        
        # Container for all message boxes
        self.msg_container = Hsplit([], [])
        
        # Add welcome message
        # self.add_message(WELCOME_MESSAGE.rstrip())
        
        # Initial component - self is now the component
        self.compositor: Optional[object] = None
        
        # Action callbacks (set by parent app)
        self.on_copy_action: Optional[callable] = None
        self.on_edit_action: Optional[callable] = None
        self.on_retry_action: Optional[callable] = None
        self.on_stop_action: Optional[callable] = None
        self.on_allow_action: Optional[callable] = None
        self.on_deny_action: Optional[callable] = None
        self.on_output_action: Optional[callable] = None
        self.on_steer_action: Optional[callable] = None
        self.on_pause_action: Optional[callable] = None
        self.on_resume_action: Optional[callable] = None
        self.on_delete_action: Optional[callable] = None

        # In-place editing state
        self._inline_editing_msg = None  # Message currently being edited in-place
        self._inline_cancel_cb = None    # Optional cancel callback

    def set_compositor(self, compositor):
        """Set the compositor for updates."""
        self.compositor = compositor

    def mark_changed(self, rect: Optional[tuple[int, int, int, int]] = None):
        """Mark panel dirty and wake compositor for immediate repaint."""
        super().mark_changed(rect)
        if self.compositor and hasattr(self.compositor, 'request_render'):
            self.compositor.request_render()

    def _request_repaint(self):
        self.mark_changed((self.x, self.y, self.width, self.height))
        if self.compositor and hasattr(self.compositor, 'request_render'):
            self.compositor.request_render()
    
    def set_focused_message(self, index: Optional[int]):
        """Set the focused message by index.
        
        Args:
            index: Index of message to focus, or None to clear focus
        """
        # Clear previous focus
        if self.focused_message_index is not None and self.focused_message_index < len(self.messages):
            self.messages[self.focused_message_index].set_focused(False)
        
        # Set new focus
        self.focused_message_index = index
        if self.focused_message_index is not None and self.focused_message_index < len(self.messages):
            self.messages[self.focused_message_index].set_focused(True)
            # Disable auto-scroll when focusing a message, UNLESS it's the last message
            # (we want to follow the last message's content as it updates)
            if self.focused_message_index < len(self.messages) - 1:
                self.auto_scroll = False
        self._request_repaint()

    # --- Text Selection ---

    def start_selection(self, msg_index: int, display_line: int, col: int):
        """Begin a text selection at the given display position inside a message."""
        msg = self.messages[msg_index]
        self._selection = SelectionState(msg=msg, start_line=display_line, start_col=col, end_line=display_line, end_col=col)
        self._selection_dragging = True
        self._selection_last_update = time.monotonic()
        self._request_repaint()

    def update_selection(self, msg_index: int, display_line: int, col: int):
        """Extend the active selection to a new end position."""
        if self._selection is None:
            return
        if self._selection_dragging and self._selection.msg is self.messages[msg_index]:
            self._selection.end_line = display_line
            self._selection.end_col = col
            self._request_repaint()

    def end_selection(self):
        """Finalize the current selection (stop dragging)."""
        self._selection_dragging = False

    def get_selection_text(self) -> Optional[str]:
        """Extract the selected text from the component's rendered lines.
        
        Returns the selected text as a plain string, or None if nothing selected.
        """
        sel = self._selection
        if sel is None:
            return None
        
        box = sel.msg.get_component()
        # Unwrap Box → inner component (MarkdownComponent or TextComponent)
        component = getattr(box, 'child', box)
        wrapped_lines = getattr(component, '_wrapped_lines', None)
        if wrapped_lines is None:
            # TextComponent: fall back to _lines
            wrapped_lines = getattr(component, '_lines', None)
            if wrapped_lines is None:
                return None

        sl, sc, el, ec = sel.get_normalized()
        sl = max(0, min(sl, len(wrapped_lines) - 1))
        el = max(0, min(el, len(wrapped_lines) - 1))
        
        parts = []
        for line_i in range(sl, el + 1):
            if line_i >= len(wrapped_lines):
                break
            
            line = wrapped_lines[line_i]
            if line_i == sl and line_i == el:
                # Same line: select substring
                parts.append(self._extract_line_text(line, sc, ec))
            elif line_i == sl:
                # First line: from sc to end
                parts.append(self._extract_line_text(line, sc, None))
            elif line_i == el:
                # Last line: from start to ec
                parts.append(self._extract_line_text(line, 0, ec))
            else:
                # Middle lines: full line
                parts.append(self._extract_line_text(line, 0, None))
        
        text = "\n".join(parts)
        return text if text else None

    def _extract_line_text(self, line, start_col: int, end_col: Optional[int]) -> str:
        """Extract plain text from a wrapped line (list of StyledSegments or strings)."""
        if isinstance(line, str):
            return line[start_col:end_col]
        
        # List of StyledSegments
        text_parts = []
        col = 0
        for seg in line:
            seg_w = seg.display_width
            seg_end_col = col + seg_w
            
            # Check if segment overlaps with selection range
            if end_col is not None and col >= end_col:
                break
            if seg_end_col > start_col:
                # Figure out which portion of the segment text to include
                if col >= start_col and (end_col is None or seg_end_col <= end_col):
                    text_parts.append(seg.text)
                else:
                    # Partial overlap — character-level extraction
                    char_col = col
                    for ch in seg.text:
                        from wcwidth import wcswidth
                        cw = wcswidth(ch)
                        if cw < 0:
                            cw = 1
                        ch_end = char_col + cw
                        if char_col >= start_col and (end_col is None or ch_end <= end_col):
                            text_parts.append(ch)
                        char_col = ch_end
            
            col = seg_end_col
        
        return "".join(text_parts)

    @staticmethod
    def _resolve_column(line, screen_x: int) -> int:
        """Map a screen x offset to a display column index within a wrapped line.

        Uses segment display_width for fast skipping; only walks characters
        when the target falls inside a segment.
        """
        if isinstance(line, str):
            return min(screen_x, len(line))

        col = 0
        for seg in line:
            seg_w = seg.display_width
            if col + seg_w <= screen_x:
                # Entire segment is before the target — skip
                col += seg_w
                continue
            if col + seg_w > screen_x:
                # Target falls inside this segment — walk characters
                from wcwidth import wcswidth
                seg_col = col
                for ch in seg.text:
                    cw = wcswidth(ch)
                    if cw < 0:
                        cw = 1
                    if seg_col + cw > screen_x:
                        return seg_col
                    seg_col += cw
                return seg_col
            col += seg_w
        return col

    def _dispatch_action(self, message, action: MsgAction):
        """Dispatch a MsgAction for a message, mirroring the keyboard handler logic.
        
        Triggers a brief visual flash on the action button before dispatching.
        """
        # Flash the action button for visual feedback
        self._flash_msg = message
        self._flash_action_key = action.key
        self._flash_until = time.monotonic() + 0.12  # 120ms flash
        message._flash_action_key = action.key
        message.box.mark_changed()
        self._request_repaint()
        
        if action == MsgAction.COPY and self.on_copy_action:
            self.on_copy_action(message)
        elif action == MsgAction.EDIT and self.on_edit_action:
            self.on_edit_action(message)
        elif action == MsgAction.DELETE and self.on_delete_action:
            self.on_delete_action(message)
        elif action == MsgAction.RETRY and self.on_retry_action:
            self.on_retry_action(message)
        elif action == MsgAction.STOP and self.on_stop_action:
            self.on_stop_action(message)
        elif action == MsgAction.ALLOW and self.on_allow_action:
            self.on_allow_action(message)
        elif action == MsgAction.DENY and self.on_deny_action:
            self.on_deny_action(message)
        elif action == MsgAction.OUTPUT and self.on_output_action:
            self.on_output_action(message)
        elif action == MsgAction.STEER and self.on_steer_action:
            self.on_steer_action(message)
        elif action == MsgAction.PAUSE and self.on_pause_action:
            self.on_pause_action(message)
        elif action == MsgAction.RESUME and self.on_resume_action:
            self.on_resume_action(message)

    def _hit_test_action_bar(self, msg, event_x: int, event_y: int) -> Optional[MsgAction]:
        """Check if a mouse click landed on an action button in the message's bottom border.
        
        Computes action hit regions on-demand (independent of focus/render state)
        so clicks work even before the message is focused.
        Returns the matched MsgAction or None.
        """
        box = msg.get_component()
        # Bottom border row is at box.y + box.height - 1
        bottom_y = box.y + box.height - 1
        if event_y != bottom_y:
            return None
        
        actions = msg.get_active_actions()
        if not actions:
            return None
        
        # Replicate the layout from Box._render_to_subbuffer:
        # available_width = box.width - 3
        # bottom_str = " metrics_str " + "│" + " actions_str "  (or just actions)
        available_width = box.width - 3
        
        metrics_str = None
        if hasattr(msg, 'should_show_metrics') and msg.should_show_metrics():
            metrics_str = msg.get_metrics_string()
        
        bottom_content_parts = []
        if metrics_str:
            bottom_content_parts.append(f" {metrics_str} ")
        actions_str = " ".join(action.format() for action in actions)
        bottom_content_parts.append(f" {actions_str} ")
        
        if len(bottom_content_parts) == 2:
            bottom_str = bottom_content_parts[0] + "│" + bottom_content_parts[1]
        else:
            bottom_str = bottom_content_parts[0]
        
        bottom_width = len(bottom_str)
        if bottom_width > available_width:
            return None  # Actions didn't fit, just border drawn
        
        left_border_width = available_width - bottom_width
        # Actions start after metrics (if present) in the bottom_str
        actions_start_in_str = 0
        if len(bottom_content_parts) == 2:
            actions_start_in_str = len(bottom_content_parts[0]) + len("│")
        
        # Absolute x where actions string starts
        actions_x_start = box.x + left_border_width + 1 + actions_start_in_str
        # Local x within the panel
        local_x = event_x - actions_x_start
        
        if local_x < 0:
            return None
        
        # Walk through actions to find which one was hit
        x_offset = 0
        for action in actions:
            formatted = action.format()
            region_end = x_offset + len(formatted)
            if x_offset <= local_x < region_end:
                return action
            x_offset = region_end + 1  # +1 for space separator
        
        return None

    def _cached_hit_test(self, screen_y: int) -> tuple[Optional[int], Optional[int]]:
        """Map a screen y coordinate to (msg_index, local_y) using a cached line map.
        
        Returns (None, None) if the y is on a gap or outside content.
        """
        # Build cache key from scroll state + message count
        if self.auto_scroll or self.anchored_start_y is None:
            anchor = None
        else:
            anchor = self.anchored_start_y
        cache_key = (self.auto_scroll, anchor, len(self.messages))
        
        if self._line_map_cache_key != cache_key:
            self._line_map_cache = self._build_line_map()
            self._line_map_cache_key = cache_key
        
        line_map = self._line_map_cache
        total_height = len(line_map)
        max_scroll = max(0, total_height - self.height)
        
        if self.auto_scroll or self.anchored_start_y is None:
            start_y = max_scroll
        else:
            start_y = self.anchored_start_y
        
        virtual_y = (screen_y - self.y) + start_y
        if 0 <= virtual_y < len(line_map):
            entry = line_map[virtual_y]
            if entry is not None:
                msg_index, local_y = entry
                return msg_index, local_y
        return None, None

    def _screen_to_display_col(self, msg, box, content_y: int, screen_x: int) -> Optional[int]:
        """Convert a screen x coordinate to a display column within a message's wrapped content.
        
        Returns the display column index, or None if the position is outside content.
        """
        panel_x = screen_x - self.x
        box_x = panel_x - msg.left_margin
        content_x = box_x - 1  # subtract left border
        
        md_component = getattr(box, 'child', box)
        left_pad = getattr(md_component, 'left_pad', 0)
        wrapped_x = content_x - left_pad
        
        if wrapped_x < 0:
            return None
        
        wrapped_lines = getattr(md_component, '_wrapped_lines', None)
        if wrapped_lines is None:
            wrapped_lines = getattr(md_component, '_lines', None)
        if wrapped_lines is None or content_y >= len(wrapped_lines):
            return None
        
        return self._resolve_column(wrapped_lines[content_y], wrapped_x)

    def _auto_copy_selection(self):
        """Copy the current selection to clipboard (called on mouse release after drag)."""
        text = self.get_selection_text()
        if not text:
            return
        # Use the same clipboard logic as handle_copy_action
        import subprocess
        import logging
        logger = logging.getLogger("tui")
        try:
            for cmd in (['xclip', '-selection', 'clipboard'],
                         ['xsel', '--clipboard', '--input'],
                         ['wl-copy']):
                try:
                    subprocess.run(cmd, input=text.encode(), check=True, stderr=subprocess.DEVNULL)
                    logger.info(f"Selection copied to clipboard ({cmd[0]})")
                    return
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            logger.warning("No clipboard utility found for selection copy")
        except Exception as e:
            logger.error(f"Error copying selection: {e}")

    def start_inline_edit(self, message, initial_text: str, on_submit, on_cancel=None):
        """Replace the message's rendered content with an editable InputComponent.

        Args:
            message:      The Message to edit in-place.
            initial_text: Text to pre-populate the editor with.
            on_submit:    Callable(text: str) — called when the user confirms.
            on_cancel:    Optional callable() — called when the user presses Esc.
        """
        from pico_chat.ui.tui.components.input.input import InputComponent

        # Stop any previous inline edit first
        self.stop_inline_edit()

        editor = InputComponent(prompt="")
        editor.parent = message.box

        # Initial layout — will be corrected on the next render pass
        box = message.box
        inner_w = max(1, (box.width or 40) - 2)
        inner_h = max(1, (box.height or 3) - 2)
        editor.set_layout(box.x + 1, box.y + 1, inner_w, inner_h)
        editor.update(initial_text)
        editor.set_focused(True)

        def _submit_wrapper(text):
            self.stop_inline_edit()
            on_submit(text)

        editor.keyboard_handler.on_submit = _submit_wrapper

        message.box.inline_editor = editor
        message.box.mark_changed()
        self._inline_editing_msg = message
        self._inline_cancel_cb = on_cancel
        self._request_repaint()

    def stop_inline_edit(self):
        """Remove the active inline editor and restore normal message rendering."""
        if self._inline_editing_msg is not None:
            self._inline_editing_msg.box.inline_editor = None
            self._inline_editing_msg.box.mark_changed()
            self._inline_editing_msg = None
        self._inline_cancel_cb = None
        self._request_repaint()

    def move_focus_up(self) -> bool:
        """Move focus to the previous message.
        
        Returns:
            True if focus moved, False if at top or no messages
        """
        if not self.messages:
            return False
        
        if self.focused_message_index is None:
            # Focus the last message if nothing is focused
            self.set_focused_message(len(self.messages) - 1)
            self._scroll_to_show_message(self.focused_message_index, prefer_top=True)
            return True
        elif self.focused_message_index > 0:
            self.set_focused_message(self.focused_message_index - 1)
            self._scroll_to_show_message(self.focused_message_index, prefer_top=True)
            return True
        return False
    
    def move_focus_down(self) -> bool:
        """Move focus to the next message.
        
        Returns:
            True if focus moved, False if at bottom or no messages
        """
        if not self.messages:
            return False
        
        if self.focused_message_index is None:
            # Focus the first message if nothing is focused
            self.set_focused_message(0)
            self._scroll_to_show_message(self.focused_message_index, prefer_top=False)
            return True
        elif self.focused_message_index < len(self.messages) - 1:
            self.set_focused_message(self.focused_message_index + 1)
            self._scroll_to_show_message(self.focused_message_index, prefer_top=False)
            return True
        return False
    
    def clear_focus(self):
        """Clear the focused message."""
        self.set_focused_message(None)
    
    def set_keyboard_focus(self, has_focus: bool):
        """Set whether this panel should handle keyboard input."""
        self.has_keyboard_focus = has_focus
        if not has_focus:
            # Clear message focus when losing keyboard focus
            self.clear_focus()
        self._request_repaint()

    def set_layout(self, x: int, y: int, width: int, height: int):
        """Override to detect width changes and trigger reformat."""
        super().set_layout(x, y, width, height)
        
        # If width changed, notify the panels to reformat
        if width != self.max_width and width > 0:
            self.on_width_change(width)

    def on_width_change(self, new_width: int):
        """Called automatically when the component width changes.
        
        Args:
            new_width: The new width of the component
        """
        self.max_width = new_width
        
        # Reformat all messages with the new width (account for box borders -2)
        inner_width = new_width - 2
        if inner_width < 1:
            inner_width = 1
            
        for message in self.messages:
            # Account for box padding
            msg_inner_width = inner_width - message.left_pad - message.right_pad
            if msg_inner_width < 1:
                msg_inner_width = 1
            message.reformat(msg_inner_width)
        self._request_repaint()

    def _get_all_rows(self) -> int:
        """Calculate total number of rows across all message boxes."""
        total = 0
        for msg in self.messages:
            # Each box's height, accounting for its specific margin
            total += msg.get_component().get_preferred_height(self.max_width - msg.left_margin - msg.right_margin)
        return total
    
    def _build_line_map(self) -> list[Optional[tuple[int, int]]]:
        """Build a map of virtual y-coordinates to message references.
        
        Returns:
            A list where each index represents a virtual y-coordinate (relative to the top
            of the content area), and the value is either:
            - None for gap lines
            - (msg_index, local_y) tuple for lines belonging to a message,
              where local_y is the y-offset within that message's box
        """
        line_map = []
        gap = pico_cfg.config.ui_msg_v_margin
        
        for i, msg in enumerate(self.messages):
            # Add gap lines before this message (skip for the first message)
            if i > 0:
                for _ in range(gap):
                    line_map.append(None)
            
            # Add lines for this message
            child = msg.get_component()
            child_w = self.width - msg.left_margin - msg.right_margin
            child_h = child.get_preferred_height(child_w)
            
            for local_y in range(child_h):
                line_map.append((i, local_y))
        
        return line_map
    
    def _get_message_virtual_y_range(self, msg_index: int) -> tuple[int, int]:
        """Get the virtual y-coordinate range for a message.
        
        Args:
            msg_index: Index of the message
            
        Returns:
            Tuple of (start_y, end_y) in virtual coordinates (exclusive end)
        """
        if msg_index < 0 or msg_index >= len(self.messages):
            return (0, 0)
        
        gap = pico_cfg.config.ui_msg_v_margin
        virtual_y = 0
        
        for i, msg in enumerate(self.messages):
            # Add gap before this message (skip for the first message)
            if i > 0:
                virtual_y += gap
            
            if i == msg_index:
                # Found our message
                child = msg.get_component()
                child_w = self.width - msg.left_margin - msg.right_margin
                child_h = child.get_preferred_height(child_w)
                return (virtual_y, virtual_y + child_h)
            
            # Move past this message
            child = msg.get_component()
            child_w = self.width - msg.left_margin - msg.right_margin
            child_h = child.get_preferred_height(child_w)
            virtual_y += child_h
        
        return (0, 0)
    
    def _scroll_to_show_message(self, msg_index: int, prefer_top: bool = True):
        """Scroll to ensure a message is visible.
        
        Args:
            msg_index: Index of the message to show
            prefer_top: If True, prioritize showing the top of the message.
                       If False, prioritize showing the bottom.
        """
        if msg_index < 0 or msg_index >= len(self.messages):
            return
        
        # Get message's virtual position
        msg_start, msg_end = self._get_message_virtual_y_range(msg_index)
        msg_height = msg_end - msg_start
        
        # Calculate current visible range in virtual coordinates.
        # Derive start_y from auto_scroll/anchored_start_y (the source of truth used by
        # render() and the mouse wheel handler) rather than self.scroll_offset, which is
        # only refreshed inside render() and can be stale between renders (e.g. while the
        # last message is streaming and total_height/max_scroll keep growing). Using a
        # stale scroll_offset yields a wrong start_y, which makes the "already visible"
        # check pass incorrectly and the view fail to follow the newly focused message.
        line_map = self._build_line_map()
        total_height = len(line_map)
        max_scroll = max(0, total_height - self.height)
        if self.auto_scroll or self.anchored_start_y is None:
            start_y = max_scroll
        else:
            start_y = self.anchored_start_y
        end_y = start_y + self.height
        
        # Check if message is already fully visible
        if msg_start >= start_y and msg_end <= end_y:
            return  # Already visible
        
        if prefer_top:
            # Scrolling up - prioritize showing the top
            if msg_start < start_y:
                # Message top is above visible area, scroll up to show it
                new_start_y = msg_start
                self.anchored_start_y = new_start_y
                self.scroll_offset = max_scroll - new_start_y
                self.scroll_offset = max(0, min(max_scroll, self.scroll_offset))
            elif msg_end > end_y:
                # Message bottom is below visible area
                # Try to show the whole message, but prioritize the top
                if msg_height <= self.height:
                    # Message fits in view, show it all
                    new_start_y = msg_end - self.height
                else:
                    # Message is taller than view, show from the top
                    new_start_y = msg_start
                self.anchored_start_y = new_start_y
                self.scroll_offset = max_scroll - new_start_y
                self.scroll_offset = max(0, min(max_scroll, self.scroll_offset))
        else:
            # Scrolling down - prioritize showing the bottom
            if msg_end > end_y:
                # Message bottom is below visible area, scroll down to show it
                new_end_y = msg_end
                new_start_y = new_end_y - self.height
                self.anchored_start_y = new_start_y
                self.scroll_offset = max_scroll - new_start_y
                self.scroll_offset = max(0, min(max_scroll, self.scroll_offset))
            elif msg_start < start_y:
                # Message top is above visible area
                # Try to show the whole message, but prioritize the bottom
                if msg_height <= self.height:
                    # Message fits in view, show it all
                    new_end_y = msg_start + self.height
                    new_start_y = new_end_y - self.height
                else:
                    # Message is taller than view, show from the bottom
                    new_end_y = msg_end
                    new_start_y = new_end_y - self.height
                self.anchored_start_y = new_start_y
                self.scroll_offset = max_scroll - new_start_y
                self.scroll_offset = max(0, min(max_scroll, self.scroll_offset))
        
        self.auto_scroll = False

    def render(self, buffer: Buffer):
        """Custom render to handle scrolling/clipping of messages."""
        # Clear expired action flash
        if self._flash_until > 0 and time.monotonic() >= self._flash_until:
            if self._flash_msg is not None:
                self._flash_msg._flash_action_key = None
                self._flash_msg.box.mark_changed()
            self._flash_msg = None
            self._flash_action_key = None
            self._flash_until = 0.0
        
        # Set clipping region to this panel's bounds
        if hasattr(buffer, 'set_clip'):
            buffer.set_clip(self.x, self.y, self.width, self.height)

        # Clear background first (to prevent artifacts from previous frames/scrolls)
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=theme.get_bg())

        # Avoid building full per-line map on every render (expensive for long streams)
        total_height = self._get_all_rows()
        
        gap = pico_cfg.config.ui_msg_v_margin
        
        # Base offset (how much we need to scroll to see the bottom)
        max_scroll = max(0, total_height - self.height)
        
        # If auto-scroll is on, we always show the bottom
        if self.auto_scroll:
            self.scroll_offset = 0
            self.anchored_start_y = None  # Clear anchor when in auto-scroll mode
            start_y = max_scroll
        else:
            # When manually scrolled, use anchored position to stay stable
            # even when content grows at the bottom
            if self.anchored_start_y is None:
                # First time entering manual scroll mode, anchor current position
                self.anchored_start_y = max_scroll - self.scroll_offset
            
            # Clamp anchored position to valid range
            self.anchored_start_y = max(0, min(max_scroll, self.anchored_start_y))
            start_y = self.anchored_start_y
            
            # Keep scroll_offset in sync for compatibility
            self.scroll_offset = max_scroll - start_y
        
        # Reset any previous layout of the container children to prevent stale rendering
        curr_y = self.y - start_y
        viewport_top = self.y
        viewport_bottom = self.y + self.height
        for i, msg in enumerate(self.messages):
            # Add gap before this message (skip for the first message)
            if i > 0:
                curr_y += gap
            
            child = msg.get_component()
            child_w = self.width - msg.left_margin - msg.right_margin
            child_h = child.get_preferred_height(child_w)

            child_y = curr_y
            child_bottom = child_y + child_h

            # Skip fully offscreen messages (vertical culling)
            if child_bottom <= viewport_top or child_y >= viewport_bottom:
                curr_y += child_h
                continue

            child.set_layout(self.x + msg.left_margin, child_y, child_w, child_h)
            child.render(buffer)
            
            # Render selection highlight if this message has an active selection
            sel = self._selection
            if sel is not None and sel.msg is msg:
                self._render_selection(buffer, msg, child, child_y, child_w, child_h)
            
            curr_y += child_h
            
        # Clear clipping region
        if hasattr(buffer, 'clear_clip'):
            buffer.clear_clip()

    def _render_selection(self, buffer: Buffer, msg, box, box_y: int, box_w: int, box_h: int):
        """Overlay a highlight on the selected range within a message box.
        
        Uses segment-level display_width for speed; only walks characters
        when a segment partially overlaps the selection boundary.
        """
        sel = self._selection
        if sel is None or sel.msg is not msg:
            return
        
        sl, sc, el, ec = sel.get_normalized()
        
        md_component = getattr(box, 'child', box)  # unwrap Box → inner component
        wrapped_lines = getattr(md_component, '_wrapped_lines', None)
        if wrapped_lines is None:
            wrapped_lines = getattr(md_component, '_lines', None)
        if wrapped_lines is None:
            return
        
        left_pad = getattr(md_component, 'left_pad', 0)
        content_abs_y = box_y + 1  # skip top border
        
        for line_i in range(sl, el + 1):
            if line_i >= len(wrapped_lines):
                break
            
            screen_y = content_abs_y + line_i
            if screen_y < self.y or screen_y >= self.y + self.height:
                continue  # clipped off-screen
            
            line = wrapped_lines[line_i]
            col_start = sc if line_i == sl else 0
            col_end = ec if line_i == el else None
            
            screen_x_base = self.x + msg.left_margin + 1 + left_pad
            current_screen_x = screen_x_base
            current_col = 0
            
            if isinstance(line, str):
                # Simple string line — use slice-based highlight
                line_col_end = col_end if col_end is not None else len(line)
                if col_start < line_col_end:
                    start_x = current_screen_x + col_start
                    end_x = current_screen_x + min(line_col_end, len(line))
                    for x in range(max(0, start_x), min(buffer.width, end_x)):
                        if 0 <= screen_y < buffer.height:
                            buffer.cells[screen_y][x].reverse = True
            else:
                # List of StyledSegments — use segment display_width for fast skipping
                for seg in line:
                    seg_w = seg.display_width
                    seg_col_end = current_col + seg_w
                    
                    # Fast skip: segment entirely before selection
                    if col_end is not None and current_col >= col_end:
                        break
                    # Fast skip: segment entirely after selection
                    if seg_col_end <= col_start:
                        current_col = seg_col_end
                        current_screen_x += seg_w
                        continue
                    
                    # Segment overlaps selection — walk characters only if partial
                    seg_start_in_sel = current_col >= col_start
                    seg_end_in_sel = col_end is None or seg_col_end <= col_end
                    
                    if seg_start_in_sel and seg_end_in_sel:
                        # Entire segment is selected — highlight whole width at once
                        for dx in range(seg_w):
                            x = current_screen_x + dx
                            if 0 <= x < buffer.width and 0 <= screen_y < buffer.height:
                                buffer.cells[screen_y][x].reverse = True
                    else:
                        # Partial overlap — walk characters
                        from wcwidth import wcswidth as _wcswidth
                        char_col = current_col
                        char_x = current_screen_x
                        for ch in seg.text:
                            cw = _wcswidth(ch)
                            if cw < 0:
                                cw = 1
                            in_range = char_col >= col_start and (col_end is None or char_col < col_end)
                            if in_range:
                                for dx in range(cw):
                                    x = char_x + dx
                                    if 0 <= x < buffer.width and 0 <= screen_y < buffer.height:
                                        buffer.cells[screen_y][x].reverse = True
                            char_col += cw
                            char_x += cw
                    
                    current_col = seg_col_end
                    current_screen_x += seg_w

    def handle_input(self, event: Any) -> bool:
        """Handle mouse wheel for scrolling and keyboard navigation."""
        # --- In-place inline editor takes priority over all other input ---
        if isinstance(event, str) and self.has_keyboard_focus and self._inline_editing_msg is not None:
            editor = self._inline_editing_msg.box.inline_editor
            if editor is not None:
                if event == '\x1b':  # Esc → cancel edit
                    cb = self._inline_cancel_cb
                    self.stop_inline_edit()
                    if cb:
                        cb()
                    return True
                editor.handle_input(event)
                return True

        # Handle keyboard input only if this panel has keyboard focus
        if isinstance(event, str) and self.has_keyboard_focus:
            # 'y' yanks (copies) the current mouse selection, if any
            if event == 'y' and self._selection is not None:
                self._auto_copy_selection()
                return True
            
            if event == '\x1b[A':  # Up arrow
                return self.move_focus_up()
            elif event == '\x1b[B':  # Down arrow
                return self.move_focus_down()
            
            # Handle action keys when a message is focused
            if self.focused_message_index is not None:
                focused_msg = self.messages[self.focused_message_index]
                
                # Delete action
                if event == 'd' and MsgAction.DELETE in focused_msg.get_active_actions():
                    if self.on_delete_action:
                        self.on_delete_action(focused_msg)
                    else:
                        # Fallback: UI-only removal
                        self.remove_message_by_index(self.focused_message_index)
                    return True
                
                # Copy action
                elif event == 'c' and MsgAction.COPY in focused_msg.type.actions:
                    if self.on_copy_action:
                        self.on_copy_action(focused_msg)
                    return True
                
                # Edit action
                elif event == 'e' and MsgAction.EDIT in focused_msg.get_active_actions():
                    if self.on_edit_action:
                        self.on_edit_action(focused_msg)
                    return True
                
                # Retry action
                elif event == 'r' and MsgAction.RETRY in focused_msg.type.actions:
                    if self.on_retry_action:
                        self.on_retry_action(focused_msg)
                    return True
                
                # Stop action
                elif event == 's' and MsgAction.STOP in focused_msg.type.actions:
                    if self.on_stop_action:
                        self.on_stop_action(focused_msg)
                    return True
                
                # Allow action
                elif event == 'a' and MsgAction.ALLOW in focused_msg.type.actions:
                    if self.on_allow_action:
                        self.on_allow_action(focused_msg)
                    return True
                
                # Deny action
                elif event == 'x' and MsgAction.DENY in focused_msg.type.actions:
                    if self.on_deny_action:
                        self.on_deny_action(focused_msg)
                    return True
                
                # Output toggle action
                elif event == 'o' and MsgAction.OUTPUT in focused_msg.type.actions:
                    if self.on_output_action:
                        self.on_output_action(focused_msg)
                    return True

                # Steer action (queued UserMsg → inject as thinking prefill)
                # Use get_active_actions so it only fires when is_queued=True
                elif event == 't' and MsgAction.STEER in focused_msg.get_active_actions():
                    if self.on_steer_action:
                        self.on_steer_action(focused_msg)
                    return True

                # Pause action (live PicoMsg/ThinkingMsg)
                elif event == 'p' and MsgAction.PAUSE in focused_msg.get_active_actions():
                    if self.on_pause_action:
                        self.on_pause_action(focused_msg)
                    return True

                # Resume action (paused message)
                elif event == 'u' and MsgAction.RESUME in focused_msg.get_active_actions():
                    if self.on_resume_action:
                        self.on_resume_action(focused_msg)
                    return True
        
        # Handle mouse input
        if isinstance(event, MouseEvent):
            # Check if mouse is over this panel
            if self.x <= event.x < self.x + self.width and \
               self.y <= event.y < self.y + self.height:
                
                # --- Left button: click, drag, release ---
                if event.button == 0:

                    # Mouse press (not drag): start click
                    if event.pressed and not event.drag:
                        # Use cached line map (rebuilt only when needed)
                        msg_index, local_y = self._cached_hit_test(event.y)
                        
                        if msg_index is not None:
                            msg = self.messages[msg_index]
                            box = msg.get_component()
                            
                            # 1) Check if click landed on an action button (bottom border)
                            #    This works even when the message isn't focused yet.
                            clicked_action = self._hit_test_action_bar(msg, event.x, event.y)
                            if clicked_action is not None:
                                # Focus the message then dispatch the action
                                self.set_focused_message(msg_index)
                                self._dispatch_action(msg, clicked_action)
                                self._selection = None
                                self._selection_dragging = False
                                self._request_repaint()
                                return True
                            
                            # 2) Otherwise, focus the message and start text selection
                            self.set_focused_message(msg_index)
                            
                            content_y = local_y - 1  # subtract top border
                            if 0 <= content_y < box.height - 2:
                                display_col = self._screen_to_display_col(msg, box, content_y, event.x)
                                if display_col is not None:
                                    self.start_selection(msg_index, content_y, display_col)
                                else:
                                    self._selection_dragging = False
                            else:
                                self._selection_dragging = False
                        else:
                            # Clicked on a gap - clear focus and selection
                            self.clear_focus()
                            self._selection = None
                            self._selection_dragging = False
                        self._request_repaint()
                        return True

                    # Mouse drag: extend selection (throttled to ~30ms between repaints)
                    if event.pressed and event.drag and self._selection_dragging:
                        now = time.monotonic()
                        if now - self._selection_last_update < self._selection_throttle_interval:
                            return True  # Too soon — skip this frame, keep consuming
                        self._selection_last_update = now
                        
                        msg_index, local_y = self._cached_hit_test(event.y)
                        if msg_index is not None and self._selection is not None and \
                           self._selection.msg is self.messages[msg_index]:
                            msg = self.messages[msg_index]
                            box = msg.get_component()
                            content_y = local_y - 1
                            if 0 <= content_y < box.height - 2:
                                display_col = self._screen_to_display_col(msg, box, content_y, event.x)
                                if display_col is not None:
                                    self.update_selection(msg_index, content_y, display_col)
                        return True

                    # Left button release: finalize selection
                    if not event.pressed and not event.drag:
                        was_dragging = self._selection_dragging
                        self.end_selection()
                        
                        # If we actually dragged a selection (not just a click),
                        # auto-copy the selection to clipboard.
                        if was_dragging and self._selection is not None:
                            self._auto_copy_selection()
                        
                        # If we didn't drag (just clicked), clear selection
                        if self._selection and not was_dragging:
                            self._selection = None
                        return True

                # Handle released drag outside the panel (stop dragging)
                if event.button == 0 and not event.pressed and self._selection_dragging:
                    self.end_selection()
                    if self._selection is not None:
                        self._auto_copy_selection()
                    return True
                
                # Button 64 is scroll up, 65 is scroll down
                if event.button == 64: # Scroll Up
                    line_map = self._build_line_map()
                    total_height = len(line_map)
                    max_scroll = max(0, total_height - self.height)
                    
                    # Get current start_y
                    if self.auto_scroll or self.anchored_start_y is None:
                        current_start_y = max_scroll
                    else:
                        current_start_y = self.anchored_start_y
                    
                    # Scroll up by the coalesced delta (configurable lines per notch)
                    step = pico_cfg.config.ui_scroll_lines_per_notch * event.scroll_delta
                    new_start_y = max(0, current_start_y - step)
                    self.anchored_start_y = new_start_y
                    self.scroll_offset = max_scroll - new_start_y
                    self.auto_scroll = False # Scrolling up disables auto-scroll
                    # Invalidate cache on scroll
                    self._line_map_cache = None
                    self._request_repaint()
                    return True
                    
                elif event.button == 65: # Scroll Down
                    line_map = self._build_line_map()
                    total_height = len(line_map)
                    max_scroll = max(0, total_height - self.height)
                    
                    # Get current start_y
                    if self.anchored_start_y is None:
                        current_start_y = max_scroll
                    else:
                        current_start_y = self.anchored_start_y
                    
                    # Scroll down by the coalesced delta (configurable lines per notch)
                    step = pico_cfg.config.ui_scroll_lines_per_notch * event.scroll_delta
                    new_start_y = min(max_scroll, current_start_y + step)
                    self.anchored_start_y = new_start_y
                    self.scroll_offset = max_scroll - new_start_y
                    
                    # If we reached the bottom, enable auto-scroll
                    if self.scroll_offset == 0:
                        self.auto_scroll = True
                        self.anchored_start_y = None
                    # Invalidate cache on scroll
                    self._line_map_cache = None
                    self._request_repaint()
                    return True
                    
        return False


    @staticmethod
    def _should_render_markdown(msg_type: MsgType) -> bool:
        """Return True if this message type should render markdown."""
        from pico_chat.ui.tui.msg_types import PicoMsg, ThinkingMsg
        # ThinkingMsg intentionally excluded: thinking content is plain text,
        # markdown would misinterpret it and break trailing-newline stripping.
        return isinstance(msg_type, PicoMsg) and not isinstance(msg_type, ThinkingMsg)

    def new_message(self, message: str, *, msg_type: MsgType = None, title: str = None, frame_color: RGB = None, content_color: RGB = None, left_margin: int = 0, right_margin: int = 0, harness_message_ids: list = None, append=False) -> Message:
        """Create a new message. If append is True, add it to the chat history. Return the Message object for further manipulation.
        
        Args:
            message: The text to add
            msg_type: The type of message
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            content_color: Optional override for the box content color
            left_margin: Optional override for the box left margin
            right_margin: Optional override for the box right margin
            harness_message_ids: List of harness message IDs this UI message references
            
        Returns:
            The created Message object.
        """
        
        # Don't change auto_scroll state here - let it be controlled externally
        # This prevents unwanted scrolling when user has scrolled up
            
        # Create a new message
        # Account for box padding in initial max_width
        initial_max_width = self.max_width - 2 - self.left_pad - self.right_pad
        if initial_max_width < 1:
            initial_max_width = 1

        new_message = Message(
            message,
            msg_type=msg_type,
            max_width=initial_max_width,
            left_pad=self.left_pad,
            right_pad=self.right_pad,
            title=title,
            frame_color=frame_color,
            content_color=content_color,
            left_margin=left_margin,
            right_margin=right_margin,
            harness_message_ids=harness_message_ids,
            render_markdown=self._should_render_markdown(msg_type),
        )
        
        if append:
            self.messages.append(new_message)
            self.msg_container.children.append(new_message.get_component())
            self.msg_container.sizes.append("auto")
            new_message.get_component().parent = self
        
        # Keep only last max_messages
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
            self.msg_container.children = [m.get_component() for m in self.messages]
            self.msg_container.sizes = ["auto"] * len(self.messages)

        self._line_map_cache = None
        self._line_map_cache_key = None
        self._request_repaint()
        
        return new_message
    
    def remove_last_message(self):
        """Remove the last message from the chat history."""
        if self.messages:
            self.messages.pop()
            self.msg_container.children.pop()
            self.msg_container.sizes.pop()
            self._line_map_cache = None
            self._line_map_cache_key = None
            self._request_repaint()

    def remove_message(self, message: Message):
        """Remove a specific message from the chat history.
        
        Args:
            message: The message to remove
        """
        try:
            index = self.messages.index(message)
            self.remove_message_by_index(index)
        except ValueError:
            # Message not found, ignore
            pass
    
    def remove_message_by_index(self, index: int):
        """Remove a message by its index.
        
        Args:
            index: The index of the message to remove
        """
        if 0 <= index < len(self.messages):
            # Adjust focused message index if needed
            if self.focused_message_index is not None:
                if self.focused_message_index == index:
                    # Deleting the focused message - clear focus or move to adjacent
                    if len(self.messages) > 1:
                        # Move focus to the next message, or previous if at end
                        if index < len(self.messages) - 1:
                            new_focus = index  # Will focus what becomes the new message at this index
                        else:
                            new_focus = index - 1  # Focus previous message
                        self.focused_message_index = new_focus
                    else:
                        # Only one message, clear focus after deletion
                        self.focused_message_index = None
                elif self.focused_message_index > index:
                    # Adjust focus index if it's after the deleted message
                    self.focused_message_index -= 1
            
            # Remove the message
            self.messages.pop(index)
            self.msg_container.children.pop(index)
            self.msg_container.sizes.pop(index)
            self._line_map_cache = None
            self._line_map_cache_key = None
            
            # Update focus state after deletion
            if self.focused_message_index is not None and self.focused_message_index < len(self.messages):
                self.messages[self.focused_message_index].set_focused(True)
            self._request_repaint()

    def replace_message(self, current: Message, new: Message):
        """Replace a message with a new message.
        
        Args:
            current: The message to replace
            new: The new message to put in its place
        """
        try:
            index = self.messages.index(current)
            
            # Check if the current message is focused
            was_focused = (self.focused_message_index == index)
            
            # Clear focus from the old message if it was focused
            if was_focused:
                current.set_focused(False)
            
            # Replace the message
            self.messages[index] = new
            self.msg_container.children[index] = new.get_component()
            new.get_component().parent = self
            # sizes remain the same ("auto")
            
            # Transfer focus to the new message if the old one was focused
            if was_focused:
                new.set_focused(True)
                # focused_message_index stays the same (same index, different message)
            self._request_repaint()
            
        except ValueError:
            # Message not found, ignore
            pass

    def add_message(self, message: str, msg_type: MsgType = None, title: str = None, frame_color: RGB = None, content_color: RGB = None, left_margin: int = 0, right_margin: int = 0, harness_message_ids: list = None, command_text: str = None) -> Message:
        """Add a message to chat history and update UI.
        
        Args:
            message: The text to add
            msg_type: The type of message
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            left_margin: Optional override for the box left margin
            right_margin: Optional override for the box right margin
            harness_message_ids: List of harness message IDs this UI message references
            command_text: Original command text (for edit action on command errors)
        
        Returns:
            The created Message object.
        """
        msg = self.new_message(message, msg_type=msg_type, title=title, frame_color=frame_color, content_color=content_color, left_margin=left_margin, right_margin=right_margin, harness_message_ids=harness_message_ids, append=True)
        if command_text:
            msg.command_text = command_text
        return msg


    def clear(self):
        """Clear the chat history UI."""
        self.messages = []
        self.msg_container.children = []
        self.msg_container.sizes = []
        self.scroll_offset = 0
        self.auto_scroll = True
        self.anchored_start_y = None
        self._request_repaint()
        
    # def resize(self, new_width: int):
    #     """Resize the panel and reformat all messages.
        
    #     Args:
    #         new_width: The new maximum width for message wrapping
    #     """
    #     self.max_width = new_width
    #     inner_width = new_width - 2
        
    #     # Reformat all messages with the new width
    #     for message in self.messages:
    #         message.reformat(inner_width)
        
        # No implicit render call here

    def get_messages(self) -> list:
        """Get the list of Message objects."""
        return self.messages

    def get_component(self):
        """Get the component for layout."""
        return self


