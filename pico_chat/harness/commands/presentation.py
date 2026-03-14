import os
from typing import Tuple

def is_binary(data: str) -> bool:
    """Detect if content is binary using common signals."""
    if '\x00' in data:
        return True
    
    # Check ratio of high-entropy control characters
    if not data:
        return False
        
    # sample some content
    sample = data[:8192]
    control_chars = sum(1 for c in sample if ord(c) < 32 and c not in '\n\r\t')
    return (control_chars / len(sample)) > 0.1

def format_result(stdout: str, stderr: str, exit_code: int, duration_ms: float) -> str:
    """
    Layer 2: Logic for the LLM. 
    Handles truncation, binary guards, and metadata.
    """
    
    # 1. Binary Guard
    if is_binary(stdout):
        size_kb = len(stdout) / 1024
        stdout = f"[binary output ({size_kb:.1f}KB) - suggest using 'cat -b' if you really need to see it]"

    # 2. Overflow Mode (Context Budget Protection)
    MAX_LINES = 200
    MAX_CHARS = 50_000
    
    lines = stdout.splitlines()
    truncated = False
    
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        truncated = True
        
    final_stdout = "\n".join(lines)
    if not truncated and len(final_stdout) > MAX_CHARS:
        final_stdout = final_stdout[:MAX_CHARS]
        truncated = True
        
    if truncated:
        final_stdout += f"\n\n--- output truncated ({len(lines)} lines shown) ---\n"
        final_stdout += "Use 'tail', 'head', or 'grep' to explore specific parts of the output."

    # 3. Combine with stderr
    output = final_stdout
    if stderr:
        output += f"\n\n[stderr]\n{stderr}"
        
    # 4. Metadata Footer
    output += f"\n[exit:{exit_code} | {duration_ms:.1f}ms]"
    
    return output
