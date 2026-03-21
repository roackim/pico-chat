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
                 padding_left: int = pico_cfg.config.ui_msg_h_padding,
                 padding_right: int = pico_cfg.config.ui_msg_h_padding,
                 title: str = None,
                 frame_color: RGB = None,
                 content_color: RGB = None,
):
        """Initialize a message.
        
        Args:
            text: The raw message text
            msg_type: The type of message (determines default formatting)
            max_width: Maximum width for line wrapping
            padding_left: Number of spaces to pad the left side
            padding_right: Number of spaces to pad the right side
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            content_color: Optional override for the content text color
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
        self.padding_left = padding_left
        self.padding_right = padding_right
        self.title = title
        self.frame_color = frame_color
        self.formatted_text = self._format_line_wrap()
        self.component = TextComponent(self.formatted_text, fg=content_color)
        self.box = Box(self.component, title=self.title, fg=self.frame_color)
    
    def set_title(self, title: str):
        """Update the title of the message box."""
        self.title = title
        self.box.title = title
    
    def _format_line_wrap(self) -> str:
        """Format the message text with smart word wrapping and padding.
        
        Uses the provided left and right padding for each line.
        """
        if self.max_width is None or self.max_width <= 0:
            return self.base_text
        
        # Calculate available width for content after padding
        content_width = self.max_width - self.padding_left - self.padding_right
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
                lines.append(" " * self.padding_left + w_line)
        
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

    def append(self, text: str):
        """Append text to the message and reformat."""
        self.base_text += text
        self.reformat(self.max_width)


# class ChatHistoryTextComponent(TextComponent):
#     """A TextComponent that notifies the panel when its width changes."""
    
#     def __init__(self, text: str, panel, id: Optional[str] = None, **kwargs):
#         super().__init__(text, id, **kwargs)
#         self.panel = panel
#         self._last_width = 0
    
#     def set_layout(self, x: int, y: int, width: int, height: int):
#         """Override to detect width changes and trigger reformat."""
#         super().set_layout(x, y, width, height)
        
#         # If width changed, notify the panel to reformat
#         if width != self._last_width and width > 0:
#             self._last_width = width
#             self.panel.on_width_change(width)
        

class ChatHistoryPanel(TextComponent):
    """Manages the chat history display panel with dynamic width support."""

    def __init__(self, max_width: int = 80):
        """Initialize the chat history panel.
        
        Args:
            max_width: Initial maximum width for message line wrapping
            padding_left: Default number of spaces to pad the left side
            padding_right: Default number of spaces to pad the right side
        """
        super().__init__("", id="history")
        self.messages = []
        self.max_width = max_width
        self.padding_left = pico_cfg.config.ui_msg_h_padding
        self.padding_right = pico_cfg.config.ui_msg_h_padding
        self.max_messages = 150  # Maximum number of messages to keep
        self.scroll_offset = 0   # How many rows to scroll up from the bottom
        self.auto_scroll = True
        
        # Container for all message boxes
        self.msg_container = Hsplit([], [])
        
        # Add welcome message
        self.add_message(WELCOME_MESSAGE.rstrip())
        
        # Initial component - self is now the component
        self.compositor: Optional[object] = None

    def set_compositor(self, compositor):
        """Set the compositor for updates."""
        self.compositor = compositor

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
            message.reformat(inner_width)

    def _get_all_rows(self) -> int:
        """Calculate total number of rows across all message boxes."""
        total = 0
        for msg in self.messages:
            # Each box's height
            total += msg.get_component().get_preferred_height(self.max_width)
        return total

    def render(self, buffer: Buffer):
        """Custom render to handle scrolling/clipping of messages."""
        # Clear background first (to prevent artifacts from previous frames/scrolls)
        buffer.fill(self.x, self.y, self.width, self.height, " ", bg=theme.get_bg())

        # number of messages
        msg_nbr = len(self.messages)
        gap = pico_cfg.config.ui_v_padding

        total_height = self._get_all_rows() + (msg_nbr - 1) * pico_cfg.config.ui_v_padding
        
        # Base offset (how much we need to scroll to see the bottom)
        max_scroll = max(0, total_height - self.height + gap) # introduce a gap to prevent last message from sticking to the bottom edge
        
        # If auto-scroll is on, we always show the bottom
        if self.auto_scroll:
            self.scroll_offset = -gap
            
        # Actual offset from the TOP of the content
        # scroll_offset 0 means we are at the bottom.
        # scroll_offset > 0 means we are scrolled up.
        start_y = max_scroll - self.scroll_offset
        
        # Reset any previous layout of the container children to prevent stale rendering
        curr_y = self.y - start_y
        for i, child in enumerate(self.msg_container.children):
            child_h = child.get_preferred_height(self.width)
            
            # Draw child if it is within or partially within the vertical bounds of the panel
            curr_y += gap
            
            child.set_layout(self.x, curr_y, self.width, child_h)
            child.render(buffer)
            
            curr_y += child_h

    def handle_input(self, event: Any) -> bool:
        """Handle mouse wheel for scrolling."""
        if isinstance(event, MouseEvent):
            # Check if mouse is over this panel
            if self.x <= event.x < self.x + self.width and \
               self.y <= event.y < self.y + self.height:
                
                # Button 64 is scroll up, 65 is scroll down
                if event.button == 64: # Scroll Up
                    total_height = self._get_all_rows()
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


    def new_message(self, message: str, *, msg_type: MsgType = None, title: str = None, frame_color: RGB = None, content_color: RGB = None) -> Message:
        """Create a new message and append it to the chat history.
        
        Args:
            message: The text to add
            msg_type: The type of message
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
            content_color: Optional override for the box content color
            
        Returns:
            The created Message object.
        """
        
        # If we are near the bottom (within a few pixels), stay at bottom
        if self.scroll_offset < 1 or self.auto_scroll:
            self.auto_scroll = True
            
        # Create a new message
        new_message = Message(
            message,
            msg_type=msg_type,
            max_width=self.max_width - 2,
            padding_left=self.padding_left,
            padding_right=self.padding_right,
            title=title,
            frame_color=frame_color,
            content_color=content_color
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

    def add_message(self, message: str, msg_type: MsgType = None, title: str = None, frame_color: RGB = None, content_color: RGB = None) -> Message:
        """Add a message to chat history and update UI.
        
        Args:
            message: The text to add
            msg_type: The type of message
            title: Optional override for the message box title
            frame_color: Optional override for the box frame color
        
        Returns:
            The created Message object.
        """
        return self.new_message(message, msg_type=msg_type, title=title, frame_color=frame_color, content_color=content_color)


    def clear(self):
        """Clear the chat history UI."""
        self.messages = []
        self.msg_container.children = []
        self.msg_container.sizes = []
        self.scroll_offset = 0
        self.auto_scroll = True
        
        # Optionally re-add welcome message
        self.new_message(WELCOME_MESSAGE.rstrip())
    
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

