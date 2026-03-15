"""Chat history panel for the Pico-Chat TUI."""

import re
from typing import Optional
from pico_chat.ui.tui.layout_utils import display_width, wrap_text, strip_ansi

from pico_chat.ui.tui.component import TextComponent, Box

# Simple markdown formatting with ANSI codes


WELCOME_MESSAGE = "Welcome to Pico-Chat!\n"


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
    
    def _contains_markdown(self, text: str) -> bool:
        """Detect if text contains markdown syntax.
        
        Looks for common markdown patterns:
        - Code blocks (```)
        - Bold (**text**)
        - Italic (*text*)
        - Inline code (`code`)
        - Headers (# ## ###)
        - Lists (- or 1.)
        """
        markdown_patterns = [
            r'```',           # Code blocks
            r'\*\*\w',        # Bold
            r'\*\w',          # Italic (but not just *)
            r'`\w',           # Inline code
            r'^\s*#{1,6}\s',  # Headers
            r'^\s*[-*+]\s',   # Bullet lists
            r'^\s*\d+\.\s',   # Numbered lists
        ]
        
        for pattern in markdown_patterns:
            if re.search(pattern, text, re.MULTILINE):
                return True
        return False
    
    def _format_line_wrap(self) -> str:
        """Format the message text with smart word wrapping.
        
        Implements smart line breaking at word boundaries and adds left padding
        to continuation lines to align text after the name prefix.
        Properly handles emojis and wide Unicode characters using wcwidth.
        Long words that exceed max_width are broken into chunks.
        """
        if self.max_width is None or self.max_width <= 0:
            return self.base_text
        
        # Determine padding
        padding_width = self.left_padding
        if padding_width == 0:
            # Auto-detect common patterns like "name: "
            match = re.match(r'^[^:]+:\s', strip_ansi(self.base_text))
            if match:
                padding_width = display_width(match.group())
        
        return wrap_text(self.base_text, self.max_width, padding_width, first_line_padding=False)
    
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

    def __init__(self, max_width: int = 80, left_padding: int = 0, enable_markdown: bool = True):
        """Initialize the chat history panel.
        
        Args:
            max_width: Initial maximum width for message line wrapping (will be updated dynamically)
            left_padding: Number of spaces to pad continuation lines (0 = auto-detect)
            enable_markdown: Enable automatic markdown detection and rendering (default True)
        """
        self.messages = []
        self.max_width = max_width
        self.left_padding = left_padding
        self.enable_markdown = enable_markdown
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
            # Create a new message
            new_message = Message(
                message, 
                max_width=self.max_width, 
                left_padding=self.left_padding
            )
            self.messages.append(new_message)
            
            # Keep only last max_messages
            if len(self.messages) > self.max_messages:
                self.messages = self.messages[-self.max_messages:]
         
        # Update the rendered history
        self.chat_history = self._render_messages()
            
        if self.compositor:
            self.compositor.update_component("history", self.chat_history)
    
    def _contains_markdown(self, text: str) -> bool:
        """Detect if text contains markdown syntax.
        
        Looks for common markdown patterns:
        - Code blocks (```)
        - Bold (**text**)
        - Italic (*text*)
        - Inline code (`code`)
        - Headers (# ## ###)
        - Lists (- or 1.)
        """
        markdown_patterns = [
            r'```',           # Code blocks
            r'\*\*\w',        # Bold
            r'\*\w',          # Italic (but not just *)
            r'`\w',           # Inline code
            r'^\s*#{1,6}\s',  # Headers
            r'^\s*[-*+]\s',   # Bullet lists
            r'^\s*\d+\.\s',   # Numbered lists
        ]
        
        for pattern in markdown_patterns:
            if re.search(pattern, text, re.MULTILINE):
                return True
        return False
    
    def _apply_simple_markdown(self, text: str) -> str:
        """Apply simple markdown formatting using ANSI codes.
        
        Formats:
        - **bold** → ANSI bold
        - *italic* → ANSI italic
        - `code` → yellow color
        - ```code blocks``` → plain indented text (stub)
        - # Headers → yellow/gold color + bold
        - - Lists → bullet points (•)
        
        Args:
            text: Raw text with markdown
            
        Returns:
            Text with ANSI codes applied
        """
        # Strip any ANSI prefix (like "pico: ") and process separately
        prefix_pattern = r'^(\x1B\[[0-9;]*m)*([^:]+:)(\x1B\[[0-9;]*m)*\s'
        prefix_match = re.match(prefix_pattern, text)
        
        if prefix_match:
            # Get clean prefix without ANSI
            full_prefix = text[:prefix_match.end()]
            clean_prefix = strip_ansi(full_prefix)
            content = text[prefix_match.end():]
        else:
            clean_prefix = ""
            content = text
        
        # Process code blocks first (multiline) - just remove markers for now (stub)
        def format_code_block(match):
            lang = match.group(1) or 'text'
            code = match.group(2)
            # Stub: Just return code as-is, indented
            lines = code.split('\n')
            formatted_lines = [f' {line}' for line in lines]
            return '\n'.join(formatted_lines)
        
        content = re.sub(r'```(\w*)\n(.+?)\n```', format_code_block, content, flags=re.DOTALL)
        
        # Inline code: `code` → yellow
        # content = re.sub(r'`([^`]+)`', r'\033[38;5;227m\1\033[0m', content)
        
        # Bold: **text** → bold
        content = re.sub(r'\*\*(.+?)\*\*', r'\033[1m\1\033[22m', content)
        
        # Italic: *text* → italic
        content = re.sub(r'(?<!\*)\*([^\*]+?)\*(?!\*)', r'\033[3m\1\033[23m', content)
        
        # Headers: # → yellow/gold color + bold
        content = re.sub(r'^(#{1,6})\s+(.+)$', r'\033[1;38;5;220m\2\033[0m', content, flags=re.MULTILINE)
        
        # Bullet lists: - → •
        content = re.sub(r'^(\s*)[-*+]\s', r'\1• ', content, flags=re.MULTILINE)
        
        # Numbered lists: keep as-is but add space
        # (already formatted correctly)
        
        return clean_prefix + content
    
    def finalize_last_message(self):
        """Finalize the last message after streaming is complete.
        
        Applies simple markdown formatting with ANSI codes if enabled.
        """
        if not self.messages:
            return
        
        last_msg = self.messages[-1]
        
        # Only apply formatting if markdown is enabled and we detect markdown patterns
        if self.enable_markdown and self._contains_markdown(last_msg.base_text):
            # Apply simple inline markdown formatting
            last_msg.base_text = self._apply_simple_markdown(last_msg.base_text)
            # Reformat with line wrapping
            last_msg.formatted_text = last_msg._format_line_wrap()
        
        # Update display
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
