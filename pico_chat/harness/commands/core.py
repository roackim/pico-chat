import os
import re
from typing import List, Optional, Tuple
from pico_chat.harness.commands.router import router

@router.command("ls", description="List directory contents. Usage: ls [path]")
def ls_command(args: List[str], stdin: Optional[str] = None) -> Tuple[str, str, int]:
    path = args[0] if args else "."
    try:
        if not os.path.exists(path):
            return "", f"ls: {path}: No such file or directory", 1
        
        if os.path.isfile(path):
            return path, "", 0
            
        items = os.listdir(path)
        # Simple formatting: one per line for easy piping
        return "\n".join(sorted(items)), "", 0
    except Exception as e:
        return "", f"ls: error: {str(e)}", 1

@router.command("cat", description="Read file content. Usage: cat <path>")
def cat_command(args: List[str], stdin: Optional[str] = None) -> Tuple[str, str, int]:
    if not args and not stdin:
        return "", "usage: cat <path> OR echo content | cat", 1
        
    if not args: # Reading from stdin
        return stdin or "", "", 0
        
    path = args[0]
    try:
        if not os.path.exists(path):
            return "", f"cat: {path}: No such file or directory", 1
        if os.path.isdir(path):
            return "", f"cat: {path}: Is a directory", 1
            
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return content, "", 0
    except Exception as e:
        return "", f"cat: error: {str(e)}", 1

@router.command("write", description="Write content to file. Usage: write <path> [content] OR echo text | write <path>")
def write_command(args: List[str], stdin: Optional[str] = None) -> Tuple[str, str, int]:
    if not args:
        return "", "usage: write <path> [content]", 1
    
    path = args[0]
    # Accept content from either stdin OR as second argument
    if len(args) > 1:
        content = " ".join(args[1:])
    elif stdin is not None:
        content = stdin
    else:
        content = ""
    
    try:
        # Create directory if it doesn't exist
        dir_path = os.path.dirname(os.path.abspath(path))
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {path}", "", 0
    except Exception as e:
        return "", f"write: error: {str(e)}", 1

@router.command("grep", description="Search for pattern in stdin or file. Usage: grep <pattern> [path]")
def grep_command(args: List[str], stdin: Optional[str] = None) -> Tuple[str, str, int]:
    if not args:
        return "", "usage: grep <pattern> [path]", 1
        
    pattern = args[0]
    content = ""
    
    if len(args) > 1:
        path = args[1]
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception as e:
            return "", f"grep: {path}: {str(e)}", 1
    elif stdin is not None:
        content = stdin
    else:
        return "", "grep: no input provided (provide path or use pipe)", 1
        
    try:
        regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        matches = [line for line in content.splitlines() if regex.search(line)]
        return "\n".join(matches), "", 0
    except Exception as e:
        return "", f"grep: invalid pattern: {str(e)}", 1

@router.command("echo", description="Print text to stdout. Usage: echo <text>")
def echo_command(args: List[str], stdin: Optional[str] = None) -> Tuple[str, str, int]:
    if args:
        return " ".join(args), "", 0
    elif stdin is not None:
        return stdin, "", 0
    else:
        return "", "", 0

@router.command("help", description="Show available commands.")
def help_command(args: List[str], stdin: Optional[str] = None) -> str:
    return router.get_help()
