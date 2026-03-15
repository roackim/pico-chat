"""Example of how to integrate markdown rendering into messages.

This shows how you could extend the Message class to support markdown rendering.
"""

from pico_chat.ui.chat_history_panel import Message as BaseMessage, display_width
from pico_chat.ui.markdown_formatter import render_markdown


class MarkdownMessage(BaseMessage):
    """A message that can optionally render markdown."""
    
    def __init__(self, text: str, max_width: int = 80, left_padding: int = 0, render_markdown: bool = False):
        """Initialize a markdown-capable message.
        
        Args:
            text: The raw message text
            max_width: Maximum width for line wrapping
            left_padding: Number of spaces to pad continuation lines
            render_markdown: If True, render text as markdown with syntax highlighting
        """
        self.render_markdown_enabled = render_markdown
        
        # If markdown enabled, pre-render it
        if render_markdown and self._contains_markdown(text):
            # Render markdown to ANSI string
            rendered = render_markdown(text, width=max_width)
            # Remove trailing newlines that rich adds
            text = rendered.rstrip('\n')
        
        # Call parent constructor with processed text
        super().__init__(text, max_width, left_padding)
    
    def _contains_markdown(self, text: str) -> bool:
        """Quick check if text likely contains markdown."""
        markdown_indicators = ['**', '*', '`', '```', '#', '- ', '1. ', '[', '](']
        return any(indicator in text for indicator in markdown_indicators)
    
    def _format_line_wrap(self) -> str:
        """Override to handle markdown that's already formatted."""
        if self.render_markdown_enabled:
            # Markdown is already formatted by rich, just return it
            # Note: This is a simple approach; you might want more sophisticated handling
            return self.base_text
        else:
            # Use normal wrapping
            return super()._format_line_wrap()


# Example usage
if __name__ == "__main__":
    print("=== Regular Message ===\n")
    msg1 = MarkdownMessage(
        "user: This is a regular message with no markdown.",
        max_width=60,
        render_markdown=False
    )
    print(msg1.get_formatted())
    
    print("\n=== Markdown Message ===\n")
    msg2 = MarkdownMessage(
        """pico: Here's your code:

```python
def hello():
    print("Hello, World!")
```

**Note:** This is syntax highlighted! 🎨""",
        max_width=60,
        render_markdown=True
    )
    print(msg2.get_formatted())
    
    print("\n✓ Both message types working!")
