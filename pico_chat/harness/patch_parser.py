"""
Patch parser for replace-block format.

Implements Aider-style search/replace blocks:

    filename.py
    <<<<<<< SEARCH
    old code
    =======
    new code
    >>>>>>> REPLACE
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class PatchBlock:
    """Parsed patch block"""
    filename: str
    search_text: str
    replace_text: str


class PatchParseError(Exception):
    """Error parsing patch block"""
    pass


def parse_patch(content: str) -> PatchBlock:
    """
    Parse a replace-block format patch.
    
    Args:
        content: Patch content with markers
        
    Returns:
        PatchBlock with filename, search, and replace text
        
    Raises:
        PatchParseError: If patch format is invalid
        
    Example:
        >>> patch = parse_patch('''app.py
        ... <<<<<<< SEARCH
        ... def foo():
        ...     pass
        ... =======
        ... def foo():
        ...     return 42
        ... >>>>>>> REPLACE
        ... ''')
        >>> patch.filename
        'app.py'
    """
    lines = content.strip().split('\n')
    
    if not lines:
        raise PatchParseError("Empty patch content")
    
    # First line is filename
    filename = lines[0].strip()
    if not filename:
        raise PatchParseError("Missing filename on first line")
    
    # Validate filename is not a marker
    if any(marker in filename for marker in ['<<<<<<< SEARCH', '=======', '>>>>>>> REPLACE']):
        raise PatchParseError("Missing filename on first line (found marker instead)")
    
    # Find markers
    search_marker = '<<<<<<< SEARCH'
    divider_marker = '======='
    replace_marker = '>>>>>>> REPLACE'
    
    search_start = None
    divider = None
    replace_end = None
    
    for i, line in enumerate(lines[1:], start=1):
        if search_marker in line:
            if search_start is not None:
                raise PatchParseError("Multiple SEARCH markers found")
            search_start = i
        elif divider_marker in line:
            if divider is not None:
                raise PatchParseError("Multiple divider markers found")
            divider = i
        elif replace_marker in line:
            if replace_end is not None:
                raise PatchParseError("Multiple REPLACE markers found")
            replace_end = i
    
    # Validate markers found
    if search_start is None:
        raise PatchParseError("Missing '<<<<<<< SEARCH' marker")
    if divider is None:
        raise PatchParseError("Missing '=======' marker")
    if replace_end is None:
        raise PatchParseError("Missing '>>>>>>> REPLACE' marker")
    
    # Validate order
    if not (search_start < divider < replace_end):
        raise PatchParseError("Markers in wrong order (must be SEARCH, =======, REPLACE)")
    
    # Extract content
    search_lines = lines[search_start + 1:divider]
    replace_lines = lines[divider + 1:replace_end]
    
    search_text = '\n'.join(search_lines)
    replace_text = '\n'.join(replace_lines)
    
    return PatchBlock(
        filename=filename,
        search_text=search_text,
        replace_text=replace_text
    )


def apply_patch(file_content: str, patch: PatchBlock) -> Tuple[str, str]:
    """
    Apply a patch to file content.
    
    Args:
        file_content: Original file content
        patch: Parsed patch block
        
    Returns:
        Tuple of (new_content, message)
        - new_content: Modified content (or original if no match)
        - message: Success or error message
        
    Examples:
        >>> content = "def foo():\\n    pass"
        >>> patch = PatchBlock("test.py", "def foo():\\n    pass", "def foo():\\n    return 42")
        >>> new, msg = apply_patch(content, patch)
        >>> "return 42" in new
        True
    """
    # Look for exact match
    if patch.search_text not in file_content:
        # Try to find similar content for helpful error message
        search_lines = patch.search_text.split('\n')
        if search_lines:
            first_line = search_lines[0]
            if first_line in file_content:
                # Find line number
                for i, line in enumerate(file_content.split('\n'), start=1):
                    if first_line in line:
                        return file_content, f"[ERROR] Search block not found. Similar content at line {i}: '{line.strip()}'"
        
        return file_content, "[ERROR] Search block not found in file. Ensure exact match including whitespace."
    
    # Count occurrences
    occurrences = file_content.count(patch.search_text)
    
    if occurrences > 1:
        return file_content, f"[ERROR] Search block matches {occurrences} locations. Add more context to make it unique."
    
    # Apply replacement
    new_content = file_content.replace(patch.search_text, patch.replace_text)
    
    return new_content, f"[OK] Applied patch to {patch.filename} (1 replacement)"
