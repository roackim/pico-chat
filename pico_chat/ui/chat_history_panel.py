"""Chat history panel for the Open-Clank TUI."""

from typing import Optional

from pico_chat.ui.tui.component import TextComponent, Box


WELCOME_MESSAGE = "[System]: Welcome to Open-Clank!\n"

# NOTE: TODO: Continue chat history format refactor
class Message:    
    """Base class for messages in the chat history."""
    def __init__(self, text: str):
        self.text = text
    
    def _format_line_wrap(self, max_width: int|None) -> str:
        """Format the message text with line wrapping. If max_width is None, end with '‥' to indicate truncation."""
        if max_width is None:
            return self.text + "‥"
        
        words = self.text.split()
        lines = []
        current_line = ""
        
        for word in words:
            if len(current_line) + len(word) + 1 <= max_width:
                current_line += (word + " ")
            else:
                lines.append(current_line.rstrip())
                current_line = word + " "
        
        if current_line:
            lines.append(current_line.rstrip())
        
        return "\n".join(lines)
        

class ChatHistoryPanel:
    """Manages the chat history display panel."""

    def __init__(self):
        """Initialize the chat history panel."""
        self.conversation = []
        self.chat_history = WELCOME_MESSAGE
        self.component = TextComponent(self.chat_history, id="history", auto_scroll_bottom=True)
        self.box = Box(self.component, title="Chat History")
        self.compositor: Optional[object] = None

    def set_compositor(self, compositor):
        """Set the compositor for updates."""
        self.compositor = compositor

    def add_message(self, message: str, append: bool = False):
        """Add a message to chat history and update UI.
        
        Args:
            message: The text to add
            append: If True, appends to the last line without a newline
        """
        if append:
            self.chat_history += message
        else:
            self.chat_history += message + "\n"
            
        # Keep only last 150 lines
        lines = self.chat_history.splitlines()
        if len(lines) > 150:
            self.chat_history = "\n".join(lines[-150:]) + "\n"
            
        if self.compositor:
            self.compositor.update_component("history", self.chat_history)

    def get_history(self) -> str:
        """Get the current chat history."""
        return self.chat_history

    def get_component(self):
        """Get the box component for layout."""
        return self.box
