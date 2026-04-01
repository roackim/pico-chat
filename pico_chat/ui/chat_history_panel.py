"""Chat history panel for the Pico-Chat TUI."""

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
        
        # Calculate current visible range in virtual coordinates
        line_map = self._build_line_map()
        total_height = len(line_map)
        max_scroll = max(0, total_height - self.height)
        start_y = max_scroll - self.scroll_offset
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
            
            curr_y += child_h
            
        # Clear clipping region
        if hasattr(buffer, 'clear_clip'):
            buffer.clear_clip()

    def handle_input(self, event: Any) -> bool:
        """Handle mouse wheel for scrolling and keyboard navigation."""
        # Handle keyboard input only if this panel has keyboard focus
        if isinstance(event, str) and self.has_keyboard_focus:
            if event == '\x1b[A':  # Up arrow
                return self.move_focus_up()
            elif event == '\x1b[B':  # Down arrow
                return self.move_focus_down()
            
            # Handle action keys when a message is focused
            if self.focused_message_index is not None:
                focused_msg = self.messages[self.focused_message_index]
                
                # Delete action
                if event == 'd' and MsgAction.DELETE in focused_msg.type.actions:
                    self.remove_message_by_index(self.focused_message_index)
                    return True
                
                # Copy action
                elif event == 'c' and MsgAction.COPY in focused_msg.type.actions:
                    if self.on_copy_action:
                        self.on_copy_action(focused_msg)
                    return True
                
                # Edit action
                elif event == 'e' and MsgAction.EDIT in focused_msg.type.actions:
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
        
        # Handle mouse input
        if isinstance(event, MouseEvent):
            # Check if mouse is over this panel
            if self.x <= event.x < self.x + self.width and \
               self.y <= event.y < self.y + self.height:
                
                # Handle clicks to focus messages
                if event.pressed and event.button == 0:  # Left click
                    # Build line map and find which message was clicked
                    line_map = self._build_line_map()
                    total_height = len(line_map)
                    gap = pico_cfg.config.ui_msg_v_margin
                    max_scroll = max(0, total_height - self.height)
                    
                    # Get current start_y (consistent with render)
                    if self.auto_scroll or self.anchored_start_y is None:
                        start_y = max_scroll
                    else:
                        start_y = self.anchored_start_y
                    
                    # Convert screen y to virtual y coordinate
                    virtual_y = (event.y - self.y) + start_y
                    
                    # Look up which message this corresponds to
                    if 0 <= virtual_y < len(line_map):
                        entry = line_map[virtual_y]
                        if entry is not None:
                            msg_index, local_y = entry
                            self.set_focused_message(msg_index)
                        else:
                            # Clicked on a gap - clear focus
                            self.clear_focus()
                        return True
                    else:
                        # Clicked outside content bounds - clear focus
                        self.clear_focus()
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
                    
                    # Scroll up by 3 lines
                    new_start_y = max(0, current_start_y - 3)
                    self.anchored_start_y = new_start_y
                    self.scroll_offset = max_scroll - new_start_y
                    self.auto_scroll = False # Scrolling up disables auto-scroll
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
                    
                    # Scroll down by 3 lines
                    new_start_y = min(max_scroll, current_start_y + 3)
                    self.anchored_start_y = new_start_y
                    self.scroll_offset = max_scroll - new_start_y
                    
                    # If we reached the bottom, enable auto-scroll
                    if self.scroll_offset == 0:
                        self.auto_scroll = True
                        self.anchored_start_y = None
                    self._request_repaint()
                    return True
                    
        return False


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
            harness_message_ids=harness_message_ids
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

        self._request_repaint()
        
        return new_message
    
    def remove_last_message(self):
        """Remove the last message from the chat history."""
        if self.messages:
            self.messages.pop()
            self.msg_container.children.pop()
            self.msg_container.sizes.pop()
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

    def add_message(self, message: str, msg_type: MsgType = None, title: str = None, frame_color: RGB = None, content_color: RGB = None, left_margin: int = 0, right_margin: int = 0, harness_message_ids: list = None) -> Message:
        """Add a message to chat history and update UI.
        
        Args:
            message: The text to add
            msg_type: The type of message
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            left_margin: Optional override for the box left margin
            right_margin: Optional override for the box right margin
            harness_message_ids: List of harness message IDs this UI message references
        
        Returns:
            The created Message object.
        """
        return self.new_message(message, msg_type=msg_type, title=title, frame_color=frame_color, content_color=content_color, left_margin=left_margin, right_margin=right_margin, harness_message_ids=harness_message_ids, append=True)


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


