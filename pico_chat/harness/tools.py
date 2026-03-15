"""
Minimal tool implementations for LLM harness.

Provides 4 core tools:
- read: Read file content
- write: Write file content
- patch: Apply replace-block patch
- run: Execute shell command (sandboxed)
"""
import subprocess
from pathlib import Path
from typing import Callable, Optional

from pico_chat.harness.patch_parser import parse_patch, apply_patch, PatchParseError
from pico_chat.harness.security import SecurityChecker


class ToolError(Exception):
    """Base exception for tool errors"""
    pass


class FileTools:
    """File operation tools (read, write, patch)"""
    
    def __init__(self, workspace_path: str | Path):
        """
        Args:
            workspace_path: Root directory for file operations
        """
        self.workspace = Path(workspace_path).resolve()
        
    def _validate_path(self, path: str) -> Path:
        """
        Validate and resolve path within workspace.
        
        Args:
            path: File path (relative to workspace)
            
        Returns:
            Absolute resolved path
            
        Raises:
            ToolError: If path is invalid or outside workspace
        """
        try:
            # Convert to Path and resolve
            target = (self.workspace / path).resolve()
            
            # Ensure it's within workspace
            if not str(target).startswith(str(self.workspace)):
                raise ToolError(f"Path '{path}' is outside workspace")
            
            return target
        except Exception as e:
            raise ToolError(f"Invalid path '{path}': {e}")
    
    def read(self, path: str) -> str:
        """
        Read file content.
        
        Args:
            path: File path relative to workspace
            
        Returns:
            File content as string
            
        Example:
            >>> tools.read("config.py")
            'import os\\n...'
        """
        target = self._validate_path(path)
        
        if not target.exists():
            raise ToolError(f"File not found: {path}")
        
        if not target.is_file():
            raise ToolError(f"Not a file: {path}")
        
        try:
            return target.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            raise ToolError(f"File is not UTF-8 text: {path}")
        except Exception as e:
            raise ToolError(f"Error reading file: {e}")
    
    def write(self, path: str, content: str) -> str:
        """
        Write file content (creates or overwrites).
        
        Args:
            path: File path relative to workspace
            content: Content to write
            
        Returns:
            Success message
            
        Example:
            >>> tools.write("script.py", "print('hello')")
            '[OK] Wrote 14 bytes to script.py'
        """
        target = self._validate_path(path)
        
        # Create parent directories if needed
        target.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            target.write_text(content, encoding='utf-8')
            byte_count = len(content.encode('utf-8'))
            return f"[OK] Wrote {byte_count} bytes to {path}"
        except Exception as e:
            raise ToolError(f"Error writing file: {e}")
    
    def patch(self, patch_content: str) -> str:
        """
        Apply replace-block patch to file.
        
        Args:
            patch_content: Patch in replace-block format
            
        Returns:
            Success or error message
            
        Example:
            >>> tools.patch('''app.py
            ... <<<<<<< SEARCH
            ... old code
            ... =======
            ... new code
            ... >>>>>>> REPLACE
            ... ''')
            '[OK] Applied patch to app.py (1 replacement)'
        """
        # Parse patch
        try:
            patch = parse_patch(patch_content)
        except PatchParseError as e:
            raise ToolError(f"Invalid patch format: {e}")
        
        # Read current file
        try:
            current_content = self.read(patch.filename)
        except ToolError as e:
            raise ToolError(f"Cannot read file for patching: {e}")
        
        # Apply patch
        new_content, message = apply_patch(current_content, patch)
        
        # If successful, write back
        if message.startswith('[OK]'):
            self.write(patch.filename, new_content)
        
        return message


class ShellTool:
    """Execute shell commands with security checks"""
    
    def __init__(
        self,
        workspace_path: str | Path,
        security_checker: Optional[SecurityChecker] = None
    ):
        """
        Args:
            workspace_path: Working directory for command execution
            security_checker: Security checker for command validation
        """
        self.workspace = Path(workspace_path).resolve()
        self.security_checker = security_checker or SecurityChecker()
    
    def run(self, command: str, timeout: int = 30) -> str:
        """
        Execute shell command in workspace.
        
        Args:
            command: Shell command to execute
            timeout: Maximum execution time in seconds
            
        Returns:
            Command output (stdout/stderr combined) with metadata
            
        Example:
            >>> tool.run("ls -la")
            '[stdout]\\nfile.txt\\n[exit:0 | 0.1ms]'
        """
        # Security check
        allowed, message = self.security_checker.check_chain(command)
        if not allowed:
            raise ToolError(message)
        
        # Execute command
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            # Format output
            output_parts = []
            
            if result.stdout:
                output_parts.append(f"[stdout]\n{result.stdout.rstrip()}")
            
            if result.stderr:
                output_parts.append(f"[stderr]\n{result.stderr.rstrip()}")
            
            # Add exit code and timing
            output_parts.append(f"[exit:{result.returncode}]")
            
            return '\n'.join(output_parts) if output_parts else "[exit:0]"
            
        except subprocess.TimeoutExpired:
            raise ToolError(f"Command timed out after {timeout}s")
        except Exception as e:
            raise ToolError(f"Command execution failed: {e}")


class MinimalToolset:
    """
    Complete minimal toolset for LLM agents.
    
    Provides read, write, patch, and run tools.
    """
    
    def __init__(
        self,
        workspace_path: str | Path,
        confirmation_callback: Optional[Callable[[str], bool]] = None
    ):
        """
        Args:
            workspace_path: Root directory for all operations
            confirmation_callback: Function to prompt user for command confirmation
        """
        workspace = Path(workspace_path).resolve()
        
        self.file_tools = FileTools(workspace)
        
        security_checker = SecurityChecker(confirmation_callback)
        self.shell_tool = ShellTool(workspace, security_checker)
    
    def read(self, path: str) -> str:
        """Read file content"""
        return self.file_tools.read(path)
    
    def write(self, path: str, content: str) -> str:
        """Write file content"""
        return self.file_tools.write(path, content)
    
    def patch(self, patch_content: str) -> str:
        """Apply replace-block patch"""
        return self.file_tools.patch(patch_content)
    
    def run(self, command: str, timeout: int = 30) -> str:
        """Execute shell command"""
        return self.shell_tool.run(command, timeout)
