# WARNING: Currently DEAD CODE - markdown rendering is disabled in the TUI for now. 
# This file is left here as a reference for future re-implementation.

import re
from pico_chat.ui.tui.layout_utils import strip_ansi

def _contains_markdown(text: str) -> bool:
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

def _apply_simple_markdown(text: str) -> str:
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
    
    # Headers: # → use theme warning color + bold
    from pico_chat.ui.tui.colors import theme
    header_color = str(theme.WARNING)
    reset = theme.reset()
    content = re.sub(r'^(#{1,6})\s+(.+)$', f'\\033[1m{header_color}\\2{reset}', content, flags=re.MULTILINE)
    
    # Bullet lists: - → •
    content = re.sub(r'^(\s*)[-*+]\s', r'\1• ', content, flags=re.MULTILINE)
    
    return clean_prefix + content
