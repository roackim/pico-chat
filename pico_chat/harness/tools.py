"""
Minimal tool implementations for LLM harness.

Provides 4 core tools:
- read: Read file content
- write: Write file content
- patch: Apply replace-block patch
- run: Execute shell command (sandboxed)
"""
import subprocess
import shlex
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

    MAX_PATCH_REPLACEMENT_CHARS = 100_000
    MAX_PATCH_LINE_DELTA = 500
    
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
        # Note: "ask" permission is handled by harness before calling tool
        
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
        # Note: "ask" permission is handled by harness before calling tool
        
        # Create parent directories if needed
        target.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            target.write_text(content, encoding='utf-8')
            byte_count = len(content.encode('utf-8'))
            return f"[OK] Wrote {byte_count} bytes to {path}"
        except Exception as e:
            raise ToolError(f"Error writing file: {e}")
    
    def patch(
        self,
        patch_content: str | None = None,
        path: str | None = None,
        search: str | None = None,
        replace: str | None = None,
    ) -> str:
        """
        Apply patch to file.
        
        Args:
            patch_content: Legacy patch in replace-block format
            path: Target file path (preferred API)
            search: Exact text to replace (preferred API)
            replace: Replacement text (preferred API)
            
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
        # Parse patch (legacy string format or structured fields)
        if patch_content:
            try:
                patch = parse_patch(patch_content)
            except PatchParseError as e:
                raise ToolError(f"Invalid patch format: {e}")

            if path and path != patch.filename:
                raise ToolError(
                    f"Invalid patch arguments: path '{path}' does not match patch target '{patch.filename}'"
                )
        else:
            if not path:
                raise ToolError("Invalid patch arguments: missing 'path'")
            if search is None:
                raise ToolError("Invalid patch arguments: missing 'search'")
            if replace is None:
                raise ToolError("Invalid patch arguments: missing 'replace'")
            patch = parse_patch(
                f"{path}\n"
                "<<<<<<< SEARCH\n"
                f"{search}\n"
                "=======\n"
                f"{replace}\n"
                ">>>>>>> REPLACE"
            )

        # Guardrails: replacement size and line delta constraints
        replacement_chars = len(patch.replace_text)
        if replacement_chars > self.MAX_PATCH_REPLACEMENT_CHARS:
            raise ToolError(
                f"Patch rejected: replacement too large ({replacement_chars} chars > {self.MAX_PATCH_REPLACEMENT_CHARS})"
            )

        search_line_count = patch.search_text.count('\n') + 1 if patch.search_text else 0
        replace_line_count = patch.replace_text.count('\n') + 1 if patch.replace_text else 0
        line_delta = abs(replace_line_count - search_line_count)
        if line_delta > self.MAX_PATCH_LINE_DELTA:
            raise ToolError(
                f"Patch rejected: line delta too large ({line_delta} lines > {self.MAX_PATCH_LINE_DELTA})"
            )
        
        # Check permissions before reading
        target, is_inside = self._validate_path(patch.filename)
        permission = self.permissions.get_patch_permission(is_inside)
        if permission == "deny":
            location = "inside repo" if is_inside else "outside repo"
            raise ToolError(f"Permission denied: patch {location} is not allowed")
        # Note: "ask" permission is handled by harness before calling tool
        
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
        permissions: Optional[ToolPermissionsProfile] = None,
        confirmation_callback: Optional[Callable[[str], bool]] = None
    ):
        """
        Args:
            workspace_path: Working directory for command execution
            security_checker: Security checker for command validation (deprecated, will be created from permissions)
            permissions: Tool permissions profile (uses default if not provided)
            confirmation_callback: Callback for user confirmation
        """
        self.workspace = Path(workspace_path).resolve()
        self.permissions = permissions or default_permissions
        
        # Create security checker with permissions if not provided
        if security_checker:
            self.security_checker = security_checker
        else:
            self.security_checker = SecurityChecker(
                permissions=self.permissions.run,
                confirmation_callback=confirmation_callback
            )
        
        # Check bwrap availability if containerization is enabled
        self._bwrap_available = None
        if self.permissions.run.use_container:
            self._bwrap_available = self._check_bwrap_available()
    
    @staticmethod
    def _check_bwrap_available() -> bool:
        """Check if bubblewrap (bwrap) is available on the system."""
        try:
            result = subprocess.run(
                ['bwrap', '--version'],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _build_bwrap_command(self, command: str) -> list[str]:
        """
        Build bubblewrap command for containerized execution.
        
        Filesystem access:
        - READ-WRITE: Workspace directory only
        - READ-ONLY: Home directory and system directories
        - Network: Controlled by container_network flag
        
        Args:
            command: Shell command to execute
            
        Returns:
            List of command arguments for bwrap execution
        """
        home = str(Path.home())
        workspace = str(self.workspace)
        
        bwrap_args = [
            'bwrap',
            '--unshare-all',      # Start with full isolation
            '--die-with-parent',  # Cleanup if parent process dies
            
            # System directories (read-only)
            '--ro-bind', '/usr', '/usr',
            '--ro-bind', '/lib', '/lib',
            '--ro-bind', '/bin', '/bin',
            '--ro-bind', '/sbin', '/sbin',
            '--ro-bind', '/etc', '/etc',
        ]
        
        # Add lib64 if it exists (not on all systems)
        if Path('/lib64').exists():
            bwrap_args.extend(['--ro-bind', '/lib64', '/lib64'])
        
        # Home directory (read-only)
        bwrap_args.extend(['--ro-bind', home, home])
        
        # Handle /tmp carefully - if workspace is under /tmp, bind it; otherwise use tmpfs
        workspace_under_tmp = str(self.workspace).startswith('/tmp')
        if workspace_under_tmp:
            # Workspace is under /tmp (e.g., pytest temp dirs)
            # Bind /tmp as-is to preserve workspace path
            bwrap_args.extend(['--bind', '/tmp', '/tmp'])
        else:
            # Workspace is elsewhere, use isolated tmpfs for /tmp
            bwrap_args.extend(['--tmpfs', '/tmp'])
        
        # Workspace (read-write) - if not already bound via /tmp
        if not workspace_under_tmp:
            bwrap_args.extend(['--bind', workspace, workspace])
        
        # Virtual filesystems
        bwrap_args.extend([
            '--proc', '/proc',     # Process information
            '--dev', '/dev',       # Device files
        ])
        
        # Network access
        if self.permissions.run.container_network:
            bwrap_args.append('--share-net')
        # Note: --unshare-all already includes --unshare-net
        
        # Set working directory
        bwrap_args.extend(['--chdir', workspace])
        
        # Execute command via shell
        bwrap_args.extend(['--', 'sh', '-c', command])
        
        return bwrap_args
    
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
        # Security check (now handles all permission logic)
        allowed, message = self.security_checker.check_chain(command)
        if not allowed:
            raise ToolError(message)
        
        # Check containerization requirements
        if self.permissions.run.use_container:
            if self._bwrap_available is False:
                raise ToolError(
                    "Containerization enabled but bubblewrap (bwrap) is not available. "
                    "Install bubblewrap or disable containerization in permissions."
                )
            
            # Build containerized command
            exec_args = self._build_bwrap_command(command)
            shell_mode = False  # bwrap args are already a list
        else:
            # Execute directly with shell
            exec_args = command
            shell_mode = True
        
        # Execute command
        try:
            result = subprocess.run(
                exec_args,
                shell=shell_mode,
                cwd=None if self.permissions.run.use_container else self.workspace,
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
        self.shell_tool = ShellTool(
            workspace,
            permissions=perms,
            confirmation_callback=confirmation_callback
        )
        
        self.permissions = perms
    
    def read(self, path: str) -> str:
        """Read file content"""
        return self.file_tools.read(path)
    
    def write(self, path: str, content: str) -> str:
        """Write file content"""
        return self.file_tools.write(path, content)
    
    def patch(
        self,
        patch_content: str | None = None,
        path: str | None = None,
        search: str | None = None,
        replace: str | None = None,
    ) -> str:
        """Apply patch (preferred: path/search/replace, legacy: patch_content)."""
        return self.file_tools.patch(
            patch_content=patch_content,
            path=path,
            search=search,
            replace=replace,
        )
    
    def run(self, command: str, timeout: int = 30) -> str:
        """Execute shell command"""
        return self.shell_tool.run(command, timeout)


class SearchTools:
    """Web search operations using DuckDuckGo and Wikipedia"""
    
    def __init__(self):
        """Initialize search tools with no configuration required."""
        pass
    
    def search_web(self, query: str, max_results: int = 3, time_range: Optional[str] = None) -> str:
        """
        Search the web using DuckDuckGo.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return (default: 3)
            time_range: Optional time filter: "day", "week", "month", "year" (default: None)
            
        Returns:
            Formatted search results as text
            
        Example:
            >>> tools.search_web("python asyncio tutorial", max_results=3)
            '[1] Python asyncio Tutorial\\nURL: https://example.com\\nSnippet: ...'
        """
        try:
            import httpx
            import re
            from html import unescape
            
            # Build URL with optional time range
            params = {'q': query}
            if time_range:
                time_map = {'day': 'd', 'week': 'w', 'month': 'm', 'year': 'y'}
                if time_range in time_map:
                    params['df'] = time_map[time_range]
            
            # Make request
            headers = {'User-Agent': 'Mozilla/5.0 (compatible)'}
            response = httpx.get(
                'https://html.duckduckgo.com/html/',
                params=params,
                headers=headers,
                timeout=10.0,
                follow_redirects=True
            )
            response.raise_for_status()
            
            html = response.text
            
            # Parse results using regex (lightweight alternative to HTML parser)
            # DuckDuckGo HTML structure: results are in divs with class="result"
            result_pattern = r'<a[^>]+class="result__a"[^>]+href="(.*?)"[^>]*>(.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>'
            matches = re.findall(result_pattern, html, re.DOTALL)
            
            if not matches:
                return f"[search_web] No results found for: {query}"
            
            # Format results
            results = []
            for idx, (url, title, snippet) in enumerate(matches[:max_results], 1):
                # Clean HTML entities and tags
                clean_title = unescape(re.sub(r'<.*?>', '', title)).strip()
                clean_snippet = unescape(re.sub(r'<.*?>', '', snippet)).strip()
                clean_url = unescape(url)
                
                results.append(
                    f"[{idx}] {clean_title}\n"
                    f"URL: {clean_url}\n"
                    f"{clean_snippet}"
                )
            
            if results:
                header = f"DuckDuckGo search results for: {query}\n" + "=" * 60 + "\n\n"
                return header + "\n\n".join(results)
            else:
                return f"[search_web] No results found for: {query}"
                
        except ImportError:
            raise ToolError("httpx library not available - required for search functionality")
        except httpx.TimeoutException:
            raise ToolError(f"Search timed out for query: {query}")
        except httpx.HTTPError as e:
            raise ToolError(f"Search request failed: {e}")
        except Exception as e:
            raise ToolError(f"Search error: {e}")
    
    def search_wiki(self, query: str, max_results: int = 3) -> str:
        """
        Search Wikipedia using the MediaWiki API.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return (default: 3)
            
        Returns:
            Formatted search results as text
            
        Example:
            >>> tools.search_wiki("Python programming language", max_results=3)
            '[1] Python (programming language)\\nURL: https://en.wikipedia.org/wiki/Python_(programming_language)\\nSnippet: ...'
        """
        try:
            import httpx
            
            # Use Wikipedia API
            params = {
                'action': 'query',
                'list': 'search',
                'srsearch': query,
                'srlimit': max_results,
                'srprop': 'snippet',
                'format': 'json',
                'utf8': 1
            }
            
            headers = {'User-Agent': 'pico-chat/0.8.0 (Educational AI assistant)'}
            response = httpx.get(
                'https://en.wikipedia.org/w/api.php',
                params=params,
                headers=headers,
                timeout=10.0
            )
            response.raise_for_status()
            
            data = response.json()
            search_results = data.get('query', {}).get('search', [])
            
            if not search_results:
                return f"[search_wiki] No results found for: {query}"
            
            # Format results
            import re
            from html import unescape
            
            results = []
            for idx, item in enumerate(search_results[:max_results], 1):
                title = item.get('title', 'Unknown')
                snippet = item.get('snippet', 'No description available')
                
                # Clean HTML tags from snippet
                clean_snippet = unescape(re.sub(r'<.*?>', '', snippet)).strip()
                
                # Build Wikipedia URL
                url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                
                results.append(
                    f"[{idx}] {title}\n"
                    f"URL: {url}\n"
                    f"{clean_snippet}"
                )
            
            if results:
                header = f"Wikipedia search results for: {query}\n" + "=" * 60 + "\n\n"
                return header + "\n\n".join(results)
            else:
                return f"[search_wiki] No results found for: {query}"
                
        except ImportError:
            raise ToolError("httpx library not available - required for search functionality")
        except httpx.TimeoutException:
            raise ToolError(f"Wikipedia search timed out for query: {query}")
        except httpx.HTTPError as e:
            raise ToolError(f"Wikipedia search request failed: {e}")
        except Exception as e:
            raise ToolError(f"Wikipedia search error: {e}")
