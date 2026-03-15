"""Chat history panel for the Pico-Chat TUI."""

import re
from typing import Optional

from pico_chat.ui.tui.component import TextComponent, Box


WELCOME_MESSAGE = "Welcome to Pico-Chat!\n"

# ANSI escape code pattern for stripping colors when calculating width
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return ANSI_ESCAPE.sub('', text)


class Message:    
    """Represents a message in the chat history with formatting support."""
    
    def __init__(self, text: str, max_width: int = 80, left_padding: int = 0):
        """Initialize a message.
        
        Args:
            text: The raw message text
            max_width: Maximum width for line wrapping
            left_padding: Number of spaces to pad continuation lines
        """
        self.base_text = text
        self.max_width = max_width
        self.left_padding = left_padding
        self.formatted_text = self._format_line_wrap()
    
    def _format_line_wrap(self) -> str:
        """Format the message text with smart word wrapping.
        
        Implements smart line breaking at word boundaries and adds left padding
        to continuation lines to align text after the name prefix.
        
        TODO: (hard) find a way to handle ANSI color codes correctly in all cases
              (currently strips them for width calculation and preserves them in output)
        """
        if self.max_width is None or self.max_width <= 0:
            return self.base_text
        
        # Detect if there's a prefix like "user: " or "pico: " at the start
        # and calculate appropriate padding for continuation lines
        padding_width = self.left_padding
        if padding_width == 0:
            # Auto-detect common patterns like "name: "
            match = re.match(r'^[^:]+:\s', strip_ansi(self.base_text))
            if match:
                padding_width = len(match.group())
        
        # Split into words but preserve newlines from the original text
        lines = []
        paragraphs = self.base_text.split('\n')
        
        for para_idx, paragraph in enumerate(paragraphs):
            if not paragraph:
                # Preserve empty lines
                lines.append("")
                continue
                
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            
            current_line = ""
            is_first_line = (para_idx == 0)  # Only first line of first paragraph gets no padding
            line_max_width = self.max_width
            
            for word_idx, word in enumerate(words):
                # Use ANSI-stripped version for width calculations
                word_display_width = len(strip_ansi(word))
                current_display_width = len(strip_ansi(current_line))
                
                # Check if adding this word would exceed the width
                space_needed = 1 if current_line else 0
                
                if current_display_width + space_needed + word_display_width <= line_max_width:
                    # Word fits on current line
                    if current_line:
                        current_line += " " + word
                    else:
                        current_line = word
                else:
                    # Word doesn't fit, start a new line
                    if current_line:
                        lines.append(current_line)
                    
                    # Start new line with padding (except for the very first line)
                    if is_first_line:
                        is_first_line = False
                        line_max_width = self.max_width - padding_width
                    
                    current_line = " " * padding_width + word
            
            # Add any remaining text
            if current_line:
                lines.append(current_line)
        
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
        return self.formatted_text
    
    def get_formatted(self) -> str:
        """Get the current formatted text."""
        return self.formatted_text


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
        

class ChatHistoryPanel:
    """Manages the chat history display panel with dynamic width support."""

    def __init__(self, max_width: int = 80, left_padding: int = 0):
        """Initialize the chat history panel.
        
        Args:
            max_width: Initial maximum width for message line wrapping (will be updated dynamically)
            left_padding: Number of spaces to pad continuation lines (0 = auto-detect)
        """
        self.messages = []
        self.max_width = max_width
        self.left_padding = left_padding
        self.max_messages = 150  # Maximum number of messages to keep
        
        # Add welcome message
        welcome_msg = Message(WELCOME_MESSAGE.rstrip(), max_width=max_width, left_padding=0)
        self.messages.append(welcome_msg)
        
        # Initialize UI components - use custom component that detects width changes
        self.chat_history = self._render_messages()
        self.component = ChatHistoryTextComponent(
            self.chat_history, 
            panel=self,
            id="history", 
            auto_scroll_bottom=True
        )
        self.box = Box(self.component, title="Chat History")
        self.compositor: Optional[object] = None

    def set_compositor(self, compositor):
        """Set the compositor for updates."""
        self.compositor = compositor

    def on_width_change(self, new_width: int):
        """Called automatically when the component width changes.
        
        Args:
            new_width: The new width of the component
        """
        if new_width == self.max_width:
            return
            
        self.max_width = new_width
        
        # Reformat all messages with the new width
        for message in self.messages:
            message.reformat(new_width)
        
        # Update the rendered history
        self.chat_history = self._render_messages()
        
        # Update the component directly (compositor will pick it up)
        self.component.text = self.chat_history

    def _render_messages(self) -> str:
        """Render all messages to a single string.
        
        Returns:
            The formatted chat history string
        """
        if not self.messages:
            return ""
        
        rendered_lines = [msg.get_formatted() for msg in self.messages]
        return "\n".join(rendered_lines) + "\n"

    def add_message(self, message: str, append: bool = False):
        """Add a message to chat history and update UI.
        
        Args:
            message: The text to add
            append: If True, appends to the last message without creating a new one
        """
        if append and self.messages:
            # Append to the last message
            last_msg = self.messages[-1]
            last_msg.base_text += message
            last_msg.formatted_text = last_msg._format_line_wrap()
        else:
            # Create a new message with padding
            new_message = Message(message, max_width=self.max_width, left_padding=self.left_padding)
            self.messages.append(new_message)
            
            # Keep only last max_messages
            if len(self.messages) > self.max_messages:
                self.messages = self.messages[-self.max_messages:]
        
        # Update the rendered history
        self.chat_history = self._render_messages()
            
        if self.compositor:
            self.compositor.update_component("history", self.chat_history)

    def resize(self, new_width: int):
        """Resize the panel and reformat all messages.
        
        Args:
            new_width: The new maximum width for message wrapping
        """
        self.max_width = new_width
        
        # Reformat all messages with the new width
        for message in self.messages:
            message.reformat(new_width)
        
        # Update the rendered history
        self.chat_history = self._render_messages()
        
        if self.compositor:
            self.compositor.update_component("history", self.chat_history)

    def get_history(self) -> str:
        """Get the current chat history."""
        return self.chat_history

    def get_messages(self) -> list:
        """Get the list of Message objects."""
        return self.messages

    def get_component(self):
        """Get the box component for layout."""
        return self.box
