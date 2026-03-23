"""Chat history panel for the Pico-Chat TUI."""

import re
from typing import Optional, Any
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.layout_utils import display_width, wrap_text, strip_ansi

from pico_chat.ui.tui.components import TextComponent, Box
from pico_chat.ui.tui.container import Hsplit
from pico_chat.ui.tui.terminal import MouseEvent

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme, RGB
from pico_chat.ui.tui.msg_types import MsgType, UserMsg, PicoMsg, SysMsg, SysMsgError, SysMsgWarning


WELCOME_MESSAGE = "Welcome to pico-chat!\n"

class Message:
    """Represents a message in the chat history with formatting support."""
    
    def __init__(self,
                 text: str,
                 msg_type: MsgType = None,
                 max_width: int = 80,
                 left_pad: int = pico_cfg.config.ui_msg_h_padding,
                 right_pad: int = pico_cfg.config.ui_msg_h_padding,
                 title: str = None,
                 frame_color: RGB = None,
                 content_color: RGB = None,
                 left_margin: int = 0,
                 right_margin: int = 0,
):
        """Initialize a message.
        
        Args:
            text: The raw message text
            msg_type: The type of message (determines default formatting)
            max_width: Maximum width for line wrapping
            left_pad: Number of spaces to pad the left side
            right_pad: Number of spaces to pad the right side
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            content_color: Optional override for the content text color
            left_margin: Number of spaces to pad the left side of the box
            right_margin: Number of spaces to pad the right side of the box
        """
        
        self.type = msg_type or MsgType()
        
        # Resolve defaults from msg_type if not provided
        if title is None:
            title = self.type.title
        
        if frame_color is None:
            color_name = self.type.frame_color
            frame_color = getattr(theme, color_name, theme.DEFAULT)
            
        if content_color is None and self.type.content_color:
            color_name = self.type.content_color
            content_color = getattr(theme, color_name, None)
        
        self.base_text = text
        self.max_width = max_width
        self.left_pad = left_pad
        self.right_pad = right_pad
        self.title = title
        self.frame_color = frame_color
        self.left_margin = left_margin
        self.right_margin = right_margin
        self.formatted_text = self._format_line_wrap()
        self.component = TextComponent(self.formatted_text, fg=content_color)
        self.box = Box(self.component, title=self.title, fg=self.frame_color, actions=self.type.actions)
    
    def set_title(self, title: str):
        """Update the title of the message box."""
        self.title = title
        self.box.title = title

    def set_frame_color(self, color: RGB):
        """Update the frame color of the message box."""
        self.frame_color = color
        self.box.fg = color

    def set_content_color(self, color: RGB):
        """Update the content color of the message."""
        self.component.fg = color
    
    def set_focused(self, focused: bool):
        """Set the focused state of this message."""
        self.box.set_focused(focused)
    
    def _format_line_wrap(self) -> str:
        """Format the message text with smart word wrapping and padding.
        
        Uses the provided left and right padding for each line.
        """
        if self.max_width is None or self.max_width <= 0:
            return self.base_text
        
        # Calculate available width for content after padding
        content_width = self.max_width - self.left_pad - self.right_pad
        if content_width < 1:
            content_width = 1
        
        # Wrap text into lines based on content_width
        # We wrap each line of base_text separately to preserve existing newlines
        lines = []
        base_text = self.base_text.rstrip('\n')
        for line in base_text.split('\n'):
            if not line:
                # Add an empty line if there's a newline in the middle of text
                lines.append("")
                continue
                
            # Wrap the line
            wrapped = wrap_text(line, content_width, padding_width=0, first_line_padding=False)
            for w_line in wrapped.split('\n'):
                # Apply left padding
                lines.append(" " * self.left_pad + w_line)
        
        return "\n".join(lines)
    
    def reformat(self, max_width: int) -> str:
        """Reformat the message with a new maximum width.
        
        Args:
            max_width: New maximum width for line wrapping
            
        Returns:
            The newly formatted text
        """
        self.max_width = max_width
        self.formatted_text = self._format_line_wrap()
        self.component.text = self.formatted_text
        return self.formatted_text
    
    def get_formatted(self) -> str:
        """Get the current formatted text."""
        return self.formatted_text

    def get_component(self):
        """Get the TUI component for this message."""
        return self.box

    def set_text(self, new_text: str):
        """Set new text for the message and reformat."""
        self.base_text = new_text
        self.reformat(self.max_width)

    def append(self, text: str):
        """Append text to the message and reformat."""
        # If message is currently empty or whitespace-only, strip leading whitespace from first append
        if not self.base_text.strip():
            text = text.lstrip()
        self.base_text += text
        self.reformat(self.max_width)
        

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
        self.focused_message_index: Optional[int] = None  # Index of the currently focused message
        self.has_keyboard_focus = False  # Track if this panel should handle keyboard input
        
        # Container for all message boxes
        self.msg_container = Hsplit([], [])
        
        # Add welcome message
        # self.add_message(WELCOME_MESSAGE.rstrip())
        
        # Initial component - self is now the component
        self.compositor: Optional[object] = None

    def set_compositor(self, compositor):
        """Set the compositor for updates."""
        self.compositor = compositor
    
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
            # Disable auto-scroll when focusing a message
            self.auto_scroll = False
    
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
            return True
        elif self.focused_message_index > 0:
            self.set_focused_message(self.focused_message_index - 1)
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
            return True
        elif self.focused_message_index < len(self.messages) - 1:
            self.set_focused_message(self.focused_message_index + 1)
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

    def render(self, buffer: Buffer):
        """Custom render to handle scrolling/clipping of messages."""
        # Set clipping region to this panel's bounds
        if hasattr(buffer, 'set_clip'):
            buffer.set_clip(self.x, self.y, self.width, self.height)

        # Clear background first (to prevent artifacts from previous frames/scrolls)
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=theme.get_bg())

        # Build line map for efficient coordinate mapping
        line_map = self._build_line_map()
        total_height = len(line_map)
        
        gap = pico_cfg.config.ui_msg_v_margin
        
        # Base offset (how much we need to scroll to see the bottom)
        max_scroll = max(0, total_height - self.height)
        
        # If auto-scroll is on, we always show the bottom
        if self.auto_scroll:
            self.scroll_offset = 0
            
        # Actual offset from the TOP of the content
        # scroll_offset 0 means we are at the bottom.
        # scroll_offset > 0 means we are scrolled up.
        start_y = max_scroll - self.scroll_offset
        
        # Reset any previous layout of the container children to prevent stale rendering
        curr_y = self.y - start_y
        for i, msg in enumerate(self.messages):
            # Add gap before this message (skip for the first message)
            if i > 0:
                curr_y += gap
            
            child = msg.get_component()
            child_w = self.width - msg.left_margin - msg.right_margin
            child_h = child.get_preferred_height(child_w)
            
            child.set_layout(self.x + msg.left_margin, curr_y, child_w, child_h)
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
                    start_y = max_scroll - self.scroll_offset
                    
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
                    self.scroll_offset = min(max_scroll, self.scroll_offset + 3)
                    self.auto_scroll = False # Scrolling up disables auto-scroll
                    return True
                    
                elif event.button == 65: # Scroll Down
                    self.scroll_offset = max(0, self.scroll_offset - 3)
                    if self.scroll_offset == 0:
                        self.auto_scroll = True # Back at bottom enables auto-scroll
                    return True
                    
        return False


    def new_message(self, message: str, *, msg_type: MsgType = None, title: str = None, frame_color: RGB = None, content_color: RGB = None, left_margin: int = 0, right_margin: int = 0) -> Message:
        """Create a new message and append it to the chat history.
        
        Args:
            message: The text to add
            msg_type: The type of message
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            content_color: Optional override for the box content color
            left_margin: Optional override for the box left margin
            right_margin: Optional override for the box right margin
            
        Returns:
            The created Message object.
        """
        
        # If we are near the bottom (within a few pixels), stay at bottom
        if self.scroll_offset < 1 or self.auto_scroll:
            self.auto_scroll = True
            
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
            right_margin=right_margin
        )
        self.messages.append(new_message)
        self.msg_container.children.append(new_message.get_component())
        self.msg_container.sizes.append("auto")
        
        # Keep only last max_messages
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
            self.msg_container.children = [m.get_component() for m in self.messages]
            self.msg_container.sizes = ["auto"] * len(self.messages)
        
        return new_message
    
    def remove_last_message(self):
        """Remove the last message from the chat history."""
        if self.messages:
            self.messages.pop()
            self.msg_container.children.pop()
            self.msg_container.sizes.pop()

    def add_message(self, message: str, msg_type: MsgType = None, title: str = None, frame_color: RGB = None, content_color: RGB = None, left_margin: int = 0, right_margin: int = 0) -> Message:
        """Add a message to chat history and update UI.
        
        Args:
            message: The text to add
            msg_type: The type of message
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            left_margin: Optional override for the box left margin
            right_margin: Optional override for the box right margin
        
        Returns:
            The created Message object.
        """
        return self.new_message(message, msg_type=msg_type, title=title, frame_color=frame_color, content_color=content_color, left_margin=left_margin, right_margin=right_margin)


    def clear(self):
        """Clear the chat history UI."""
        self.messages = []
        self.msg_container.children = []
        self.msg_container.sizes = []
        self.scroll_offset = 0
        self.auto_scroll = True
        
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


