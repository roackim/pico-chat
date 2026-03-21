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
from pico_chat.harness.tool_permissions import ToolPermissionsProfile, permissions as default_permissions


class ToolError(Exception):
    """Base exception for tool errors"""
    pass


class FileTools:
    """File operation tools (read, write, patch)"""
    
    def __init__(
        self,
        workspace_path: str | Path,
        permissions: Optional[ToolPermissionsProfile] = None
    ):
        """
        Args:
            workspace_path: Root directory for file operations
            permissions: Tool permissions profile (uses default if not provided)
        """
        self.workspace = Path(workspace_path).resolve()
        self.permissions = permissions or default_permissions
    
    def _is_inside_repo(self, target: Path) -> bool:
        """
        Check if a path is inside the workspace/repo.
        
        Args:
            target: Resolved absolute path
            
        Returns:
            True if path is inside workspace, False otherwise
        """
        try:
            target.relative_to(self.workspace)
            return True
        except ValueError:
            return False
    
    def _validate_path(self, path: str) -> tuple[Path, bool]:
        """
        Validate and resolve path.
        
        Args:
            path: File path (relative to workspace or absolute)
            
        Returns:
            Tuple of (absolute resolved path, is_inside_repo)
            
        Raises:
            ToolError: If path is invalid
        """
        try:
            # Convert to Path and resolve
            if Path(path).is_absolute():
                target = Path(path).resolve()
            else:
                target = (self.workspace / path).resolve()
            
            # Check if inside repo
            is_inside = self._is_inside_repo(target)
            
            return target, is_inside
        except Exception as e:
            raise ToolError(f"Invalid path '{path}': {e}")
    
    def read(self, path: str) -> str:
        """
        Read file content.
        
        Args:
            path: File path relative to workspace or absolute
            
        Returns:
            File content as string
            
        Raises:
            ToolError: If permission denied or file cannot be read
            
        Example:
            >>> tools.read("config.py")
            'import os\\n...'
        """
        target, is_inside = self._validate_path(path)
        
        # Check permissions
        permission = self.permissions.get_read_permission(is_inside)
        if permission == "deny":
            location = "inside repo" if is_inside else "outside repo"
            raise ToolError(f"Permission denied: read {location} is not allowed")
        elif permission == "ask":
            # TODO: Implement user confirmation callback
            raise ToolError(f"Permission required: read {path} requires user confirmation (not yet implemented)")
        
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
            path: File path relative to workspace or absolute
            content: Content to write
            
        Returns:
            Success message
            
        Raises:
            ToolError: If permission denied or file cannot be written
            
        Example:
            >>> tools.write("script.py", "print('hello')")
            '[OK] Wrote 14 bytes to script.py'
        """
        target, is_inside = self._validate_path(path)
        
        # Check permissions
        permission = self.permissions.get_write_permission(is_inside)
        if permission == "deny":
            location = "inside repo" if is_inside else "outside repo"
            raise ToolError(f"Permission denied: write {location} is not allowed")
        elif permission == "ask":
            # TODO: Implement user confirmation callback
            raise ToolError(f"Permission required: write {path} requires user confirmation (not yet implemented)")
        
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
            
        Raises:
            ToolError: If permission denied or patch cannot be applied
            
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
        
        # Check permissions before reading
        target, is_inside = self._validate_path(patch.filename)
        permission = self.permissions.get_patch_permission(is_inside)
        if permission == "deny":
            location = "inside repo" if is_inside else "outside repo"
            raise ToolError(f"Permission denied: patch {location} is not allowed")
        elif permission == "ask":
            # TODO: Implement user confirmation callback
            raise ToolError(f"Permission required: patch {patch.filename} requires user confirmation (not yet implemented)")
        
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
        security_checker: Optional[SecurityChecker] = None,
        permissions: Optional[ToolPermissionsProfile] = None
    ):
        """
        Args:
            workspace_path: Working directory for command execution
            security_checker: Security checker for command validation
            permissions: Tool permissions profile (uses default if not provided)
        """
        self.workspace = Path(workspace_path).resolve()
        self.security_checker = security_checker or SecurityChecker()
        self.permissions = permissions or default_permissions
    
    def run(self, command: str, timeout: int = 30) -> str:
        """
        Execute shell command in workspace.
        
        Args:
            command: Shell command to execute
            timeout: Maximum execution time in seconds
            
        Returns:
            Command output (stdout/stderr combined) with metadata
            
        Raises:
            ToolError: If permission denied or command execution fails
            
        Example:
            >>> tool.run("ls -la")
            '[stdout]\\nfile.txt\\n[exit:0 | 0.1ms]'
        """
        # Check permissions
        permission = self.permissions.get_run_permission()
        if permission == "deny":
            raise ToolError("Permission denied: run command is not allowed")
        elif permission == "ask":
            # Security check handles ask permission via confirmation callback
            pass
        
        # Security check
        allowed, message = self.security_checker.check_chain(command)
        if not allowed:
            raise ToolError(message)
        
        # TODO: Implement containerization when use_container is enabled
        # if self.permissions.run.use_container:
        #     command = self._containerize_command(command)
        
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
    
    Provides read, write, patch, and run tools with configurable permissions.
    """
    
    def __init__(
        self,
        workspace_path: str | Path,
        confirmation_callback: Optional[Callable[[str], bool]] = None,
        permissions: Optional[ToolPermissionsProfile] = None
    ):
        """
        Args:
            workspace_path: Root directory for all operations
            confirmation_callback: Function to prompt user for command confirmation
            permissions: Tool permissions profile (uses default if not provided)
        """
        workspace = Path(workspace_path).resolve()
        perms = permissions or default_permissions
        
        self.file_tools = FileTools(workspace, permissions=perms)
        
        security_checker = SecurityChecker(confirmation_callback)
        self.shell_tool = ShellTool(workspace, security_checker, permissions=perms)
        
        self.permissions = perms
    
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
