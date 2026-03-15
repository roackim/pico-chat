"""Markdown formatting for terminal output using rich library."""

from io import StringIO
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax


def render_markdown(text: str, width: int = 80) -> str:
    """Render markdown text to ANSI-formatted string.
    
    Supports:
    - **bold**, *italic*, `inline code`
    - Headers (# ## ###)
    - Lists (bullet and numbered)
    - Code blocks with syntax highlighting
    - Links, blockquotes
    
    Args:
        text: Markdown text to render
        width: Maximum width for rendering (default 80)
        
    Returns:
        ANSI-formatted string ready for terminal display
    """
    # Create a string buffer and console that writes to it
    string_buffer = StringIO()
    console = Console(
        file=string_buffer,
        width=width,
        force_terminal=True,  # Ensure ANSI codes are generated
        legacy_windows=False,
        color_system="truecolor"
    )
    
    # Render the markdown
    md = Markdown(text, code_theme="monokai")
    console.print(md)
    
    # Get the rendered output
    return string_buffer.getvalue()


def render_code(code: str, language: str = "python", width: int = 80, theme: str = "monokai") -> str:
    """Render syntax-highlighted code.
    
    Args:
        code: Source code to highlight
        language: Programming language (python, javascript, bash, etc.)
        width: Maximum width
        theme: Color theme (monokai, dracula, github-dark, etc.)
        
    Returns:
        ANSI-formatted string with syntax highlighting
    """
    string_buffer = StringIO()
    console = Console(
        file=string_buffer,
        width=width,
        force_terminal=True,
        legacy_windows=False,
        color_system="truecolor"
    )
    
    syntax = Syntax(code, language, theme=theme, line_numbers=False, word_wrap=True)
    console.print(syntax)
    
    return string_buffer.getvalue()


def strip_trailing_newlines(text: str) -> str:
    """Remove excessive trailing newlines from rich output."""
    return text.rstrip('\n') + '\n' if text.strip() else text


# Example usage
if __name__ == "__main__":
    example = """
Here's your LCG PRNG implementation!

**Key features:**
- Uses standard glibc parameters (a=1664525, c=1013904223, m=2^32)
- `next()` returns the next integer
- `normalized()` returns a float between 0.0 and 1.0
- Includes a reset method to restart with seed

To test it:
```python
class LCG:
    def __init__(self, seed=0):
        self.state = seed
    
    def next(self):
        # LCG formula: X[n+1] = (a * X[n] + c) mod m
        a = 1664525
        c = 1013904223
        m = 2**32
        self.state = (a * self.state + c) % m
        return self.state
```

Pretty cool, right? 😊
"""
    
    print("=== Markdown Rendering Demo ===\n")
    rendered = render_markdown(example, width=70)
    print(rendered)
