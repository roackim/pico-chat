"""Chat history panel for the Pico-Chat TUI."""

import re
from typing import Optional, Any
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.layout_utils import display_width, wrap_text, strip_ansi

from pico_chat.ui.tui.component import TextComponent, Box
from pico_chat.ui.tui.container import Hsplit
from pico_chat.ui.tui.terminal import MouseEvent

# Simple markdown formatting with ANSI codes


WELCOME_MESSAGE = "Welcome to pico-chat!\n"


class Message:    
    """Represents a message in the chat history with formatting support."""
    
    def __init__(self, text: str, max_width: int = 80, padding_left: int = 1, padding_right: int = 1, title: str = "", frame_color: tuple[int, int, int] = None):
        """Initialize a message.
        
        Args:
            text: The raw message text
            max_width: Maximum width for line wrapping
            padding_left: Number of spaces to pad the left side
            padding_right: Number of spaces to pad the right side
            title: Title for the message box
            frame_color: RGB color for the box frame and title
        """
        self.base_text = text
        self.max_width = max_width
        self.padding_left = padding_left
        self.padding_right = padding_right
        self.title = title
        self.frame_color = frame_color
        self.formatted_text = self._format_line_wrap()
        self.component = TextComponent(self.formatted_text)
        self.box = Box(self.component, title=self.title, fg=self.frame_color)
    
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


class ChatHistoryTextComponent(TextComponent):
    """A TextComponent that notifies the panel when its width changes."""
    
    def __init__(self, text: str, panel, id: Optional[str] = None, **kwargs):
        super().__init__(text, id, **kwargs)
        self.panel = panel
        self._last_width = 0
    
    def set_layout(self, x: int, y: int, width: int, height: int):
        """Override to detect width changes and trigger reformat."""
        super().set_layout(x, y, width, height)
        
        # If width changed, notify the panel to reformat
        if width != self._last_width and width > 0:
            self._last_width = width
            self.panel.on_width_change(width)
        

class ChatHistoryPanel(TextComponent):
    """Manages the chat history display panel with dynamic width support."""

    def __init__(self, max_width: int = 80, padding_left: int = 1, padding_right: int = 1):
        """Initialize the chat history panel.
        
        Args:
            max_width: Initial maximum width for message line wrapping
            padding_left: Default number of spaces to pad the left side
            padding_right: Default number of spaces to pad the right side
        """
        super().__init__("", id="history")
        self.messages = []
        self.max_width = max_width
        self.padding_left = padding_left
        self.padding_right = padding_right
        self.max_messages = 150  # Maximum number of messages to keep
        self.scroll_offset = 0   # How many rows to scroll up from the bottom
        self.auto_scroll = True
        
        # Container for all message boxes
        self.msg_container = Hsplit([], [])
        
        # Add welcome message
        self.add_message(WELCOME_MESSAGE.rstrip())
        self.finalize_last_message()
        
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
        buffer.fill(self.x, self.y, self.width, self.height)

        total_height = self._get_all_rows()
        
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
        for i, child in enumerate(self.msg_container.children):
            child_h = child.get_preferred_height(self.width)
            
            # Draw child if it is within or partially within the vertical bounds of the panel
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

    def _render_messages(self) -> str:
        """DEPRECATED: No longer used with per-message boxes.
        
        Returns:
            The formatted chat history string
        """
        if not self.messages:
            return ""
        
        # We still keep this for internal logic if needed, but not for rendering
        rendered_lines = [msg.get_formatted() for msg in self.messages]
        return "\n".join(rendered_lines) + "\n"

    def add_message(self, message: str, append: bool = False, title: str = "", frame_color: tuple[int, int, int] = None, overwrite_last: bool = False):
        """Add a message to chat history and update UI.
        
        Args:
            message: The text to add
            append: If True, appends to the last message without creating a new one
            title: Optional title for the message box
            frame_color: Optional RGB color for the box frame
            overwrite_last: If True, replaces text of last message.
        """
        # If we are near the bottom (within a few pixels), stay at bottom
        if self.scroll_offset < 1 or self.auto_scroll:
            self.auto_scroll = True
            
        if overwrite_last and self.messages:
            last_msg = self.messages[-1]
            last_msg.base_text = message
            if title:
                last_msg.title = title
                last_msg.box.title = title
            last_msg.reformat(self.max_width - 2)
            return

        if append and self.messages:
            # Append to the last message
            last_msg = self.messages[-1]
            last_msg.base_text += message
            if title:
                last_msg.title = title
                last_msg.box.title = title
            # Reformat with current width (inner width)
            last_msg.reformat(self.max_width - 2)
        else:
            # Create a new message
            new_message = Message(
                message, 
                max_width=self.max_width - 2, 
                padding_left=self.padding_left,
                padding_right=self.padding_right,
                title=title,
                frame_color=frame_color
            )
            self.messages.append(new_message)
            self.msg_container.children.append(new_message.get_component())
            self.msg_container.sizes.append("auto")
            
            # Keep only last max_messages
            if len(self.messages) > self.max_messages:
                self.messages = self.messages[-self.max_messages:]
                self.msg_container.children = [m.get_component() for m in self.messages]
                self.msg_container.sizes = ["auto"] * len(self.messages)
            
        # No implicit render call here, compositor's main loop handles it

    def add_user_message(self, message: str, color: tuple[int, int, int] = None, title: str = "user"):
        """Add a user message with the appropriate header and formatting."""
        self.add_message(message, title=title, frame_color=color)

    def add_pico_message(self, message: str, color: tuple[int, int, int] = None, title: str = "pico"):
        """Add a Pico assistant message with the appropriate header and formatting."""
        self.add_message(message, title=title, frame_color=color)

    def add_system_message(self, message: str, color: tuple[int, int, int] = (100, 100, 100), title: str = "system"):
        """Add a system or command result message."""
        self.add_message(message, title=title, frame_color=color)

    def clear(self):
        """Clear the chat history UI."""
        self.messages = []
        self.msg_container.children = []
        self.msg_container.sizes = []
        self.scroll_offset = 0
        self.auto_scroll = True
        
        # Optionally re-add welcome message
        self.add_message(WELCOME_MESSAGE.rstrip())
        self.finalize_last_message()
    
    def finalize_last_message(self):
        """Finalize the last message after streaming is complete."""
        # Note: Markdown rendering logic has been moved to legacy_markdown_rendering.py
        pass

    def resize(self, new_width: int):
        """Resize the panel and reformat all messages.
        
        Args:
            new_width: The new maximum width for message wrapping
        """
        self.max_width = new_width
        inner_width = new_width - 2
        
        # Reformat all messages with the new width
        for message in self.messages:
            message.reformat(inner_width)
        
        # No implicit render call here

    def get_history(self) -> str:
        """Get the current chat history (deprecated)."""
        return ""

    def get_messages(self) -> list:
        """Get the list of Message objects."""
        return self.messages

    def get_component(self):
        """Get the component for layout."""
        return self
