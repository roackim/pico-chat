"""Chat history panel for the Pico-Chat TUI."""

import re
from typing import Optional
from pico_chat.ui.tui.layout_utils import display_width, wrap_text, strip_ansi

from pico_chat.ui.tui.component import TextComponent, Box
from pico_chat.ui.tui.container import Hsplit

# Simple markdown formatting with ANSI codes


WELCOME_MESSAGE = "Welcome to Pico-Chat!\n"


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

    def __init__(self, max_width: int = 80, padding_left: int = 1, padding_right: int = 1, enable_markdown: bool = True):
        """Initialize the chat history panel.
        
        Args:
            max_width: Initial maximum width for message line wrapping
            padding_left: Default number of spaces to pad the left side
            padding_right: Default number of spaces to pad the right side
            enable_markdown: Enable automatic markdown detection and rendering
        """
        super().__init__("", id="history")
        self.messages = []
        self.max_width = max_width
        self.padding_left = padding_left
        self.padding_right = padding_right
        self.enable_markdown = enable_markdown
        self.max_messages = 150  # Maximum number of messages to keep
        
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
        total_height = self._get_all_rows()
        start_y = 0
        
        # Auto-scroll logic: if content exceeds panel height, offset start_y
        if total_height > self.height:
            start_y = total_height - self.height
        
        # Reset any previous layout of the container children to prevent stale rendering
        curr_y = self.y - start_y
        for i, child in enumerate(self.msg_container.children):
            child_h = child.get_preferred_height(self.width)
            
            # Draw child if it is within the vertical bounds of the panel
            # Buffer.write_str in child.render handles X bounds and Y bounds.
            child.set_layout(self.x, curr_y, self.width, child_h)
            child.render(buffer)
            
            curr_y += child_h

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

    def add_message(self, message: str, append: bool = False, title: str = "", frame_color: tuple[int, int, int] = None):
        """Add a message to chat history and update UI.
        
        Args:
            message: The text to add
            append: If True, appends to the last message without creating a new one
            title: Optional title for the message box
            frame_color: Optional RGB color for the box frame
        """
        if append and self.messages:
            # Append to the last message
            last_msg = self.messages[-1]
            last_msg.base_text += message
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

    def add_user_message(self, message: str, color: tuple[int, int, int] = None):
        """Add a user message with the appropriate header and formatting."""
        self.add_message(message, title="user", frame_color=color)

    def add_pico_message(self, message: str, color: tuple[int, int, int] = None):
        """Add a Pico assistant message with the appropriate header and formatting."""
        self.add_message(message, title="pico", frame_color=color)
    
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
            # Reformat with line wrapping (account for borders)
            last_msg.reformat(self.max_width - 2)
        
        # No implicit render call here

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
