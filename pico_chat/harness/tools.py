"""
Minimal tool implementations for LLM harness.

Provides 4 core tools:
- read: Read file content
- write: Write file content
- patch: Apply replace-block patch
- run: Execute shell command (sandboxed)
"""
import asyncio
import inspect
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from pico_chat.harness.patch_parser import parse_patch, apply_patch, PatchParseError
from pico_chat.harness.permissions import (
    SecurityChecker,
    ToolPermissionsProfile,
    file_permission,
    resolve_run_permissions,
    permissions as default_permissions,
)


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
    
    def read(
        self,
        path: str,
        offset: int = 0,
        limit: int | None = None,
        max_chars: int | None = None,
        include_line_numbers: bool = False,
    ) -> str:
        """
        Read file content.
        
        Args:
            path: File path relative to workspace or absolute
            offset: Zero-based first line to return
            limit: Optional number of lines to return
            max_chars: Optional maximum size of the returned content
            include_line_numbers: Prefix each returned line with its source line
                number
            
        Returns:
            File content as string
            
        Raises:
            ToolError: If permission denied or file cannot be read
            
        Example:
            >>> tools.read("config.py")
            'import os\\n...'
        """
        for name, value in (("offset", offset), ("limit", limit), ("max_chars", max_chars)):
            minimum = 0 if name == "offset" else 1
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < minimum):
                expectation = "a non-negative integer" if name == "offset" else "a positive integer"
                raise ToolError(f"Invalid {name}: expected {expectation}")

        target, is_inside = self._validate_path(path)
        
        # Check permissions
        permission = file_permission(self.permissions, "read", is_inside)
        if permission == "deny":
            location = "inside repo" if is_inside else "outside repo"
            raise ToolError(f"Permission denied: read {location} is not allowed")
        # Note: "ask" permission is handled by harness before calling tool
        
        if not target.exists():
            raise ToolError(f"File not found: {path}")
        
        if not target.is_file():
            raise ToolError(f"Not a file: {path}")
        
        try:
            content = target.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            raise ToolError(f"File is not UTF-8 text: {path}")
        except Exception as e:
            raise ToolError(f"Error reading file: {e}")

        # Keep line endings while slicing so a selected block can be copied
        # directly into the patch tool.
        lines = content.splitlines(keepends=True)
        first = offset
        last = offset + limit if limit is not None else len(lines)
        selected = lines[first:last]

        if include_line_numbers:
            selected = [f"{number:>6}\t{line}" for number, line in zip(range(first + 1, last + 1), selected)]

        result = "".join(selected)
        if max_chars is not None and len(result) > max_chars:
            result = result[:max_chars] + f"\n[truncated: showing {max_chars} of {len(result)} characters]"
        return result
    
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
        permission = file_permission(self.permissions, "write", is_inside)
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
        permission = file_permission(self.permissions, "patch", is_inside)
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
        self.run_permissions = resolve_run_permissions(self.permissions)

        # Create security checker with permissions if not provided
        if security_checker:
            self.security_checker = security_checker
        else:
            self.security_checker = SecurityChecker(
                permissions=self.run_permissions,
                confirmation_callback=confirmation_callback
            )
        
        # Handle to the currently-running command (for stop/cancellation).
        self._active_proc: Optional["asyncio.subprocess.Process"] = None
        
        # Check bwrap availability if containerization is enabled
        self._bwrap_available = None
        if self.run_permissions.use_container:
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
        
        # Add /run if it exists (needed for DNS resolution via systemd-resolved)
        if Path('/run').exists():
            bwrap_args.extend(['--ro-bind', '/run', '/run'])
        
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
        if self.run_permissions.container_network:
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
        if self.run_permissions.use_container:
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
                cwd=None if self.run_permissions.use_container else self.workspace,
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

    async def run_async(self, command: str, timeout: int = 30) -> str:
        """Cancellable async version of :meth:`run`.

        Runs the command as a subprocess whose handle is stored on
        ``self._active_proc`` so a "stop" request can terminate it
        mid-flight. Returns the same formatted output as :meth:`run`.
        """
        import asyncio

        allowed, message = self.security_checker.check_chain(command)
        if not allowed:
            raise ToolError(message)

        if self.run_permissions.use_container:
            if self._bwrap_available is False:
                raise ToolError(
                    "Containerization enabled but bubblewrap (bwrap) is not available. "
                    "Install bubblewrap or disable containerization in permissions."
                )
            exec_args = self._build_bwrap_command(command)
            shell = False
            cwd = None
        else:
            exec_args = command
            shell = True
            cwd = self.workspace

        try:
            if shell:
                proc = await asyncio.create_subprocess_shell(
                    exec_args,
                    shell=True,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,  # own process group so stop kills children
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *exec_args,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
            self._active_proc = proc

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                self._kill_process_group(proc)
                await proc.communicate()
                raise ToolError(f"Command timed out after {timeout}s")
            finally:
                if self._active_proc is proc:
                    self._active_proc = None

            stdout = (stdout or b"").decode("utf-8", errors="replace").rstrip()
            stderr = (stderr or b"").decode("utf-8", errors="replace").rstrip()

            output_parts = []
            if stdout:
                output_parts.append(f"[stdout]\n{stdout}")
            if stderr:
                output_parts.append(f"[stderr]\n{stderr}")
            output_parts.append(f"[exit:{proc.returncode}]")
            return '\n'.join(output_parts) if output_parts else "[exit:0]"
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Command execution failed: {e}")

    def cancel_active(self) -> bool:
        """Terminate the currently-running command, if any.

        Kills the whole process group so child processes (e.g. ``sleep``)
        are terminated too. Returns True if a process was terminated.
        """
        if self._active_proc is not None and self._active_proc.returncode is None:
            try:
                self._kill_process_group(self._active_proc)
                return True
            except Exception:
                return False
        return False

    @staticmethod
    def _kill_process_group(proc) -> None:
        """Kill a subprocess and its entire process group (best effort)."""
        import os
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


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
    
    def read(
        self,
        path: str,
        offset: int = 0,
        limit: int | None = None,
        max_chars: int | None = None,
        include_line_numbers: bool = False,
    ) -> str:
        """Read all or part of a file."""
        return self.file_tools.read(
            path,
            offset=offset,
            limit=limit,
            max_chars=max_chars,
            include_line_numbers=include_line_numbers,
        )
    
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

    async def run_async(self, command: str, timeout: int = 30) -> str:
        """Execute shell command asynchronously (cancellable)."""
        return await self.shell_tool.run_async(command, timeout)

    def cancel_active_run(self) -> bool:
        """Terminate the currently-running shell command, if any."""
        return self.shell_tool.cancel_active()


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
                return (
                    f"[search_web] No results found for query: '{query}'\n\n"
                    "Suggestions:\n"
                    "- Try different keywords or a more specific query\n"
                    "- Check spelling and try alternative terms\n"
                    "- Use the search_wiki tool for encyclopedia topics"
                )
            
            # Format results
            results = []
            for idx, (url, title, snippet) in enumerate(matches[:max_results], 1):
                # Clean HTML entities and tags
                clean_title = unescape(re.sub(r'<.*?>', '', title)).strip()
                clean_snippet = unescape(re.sub(r'<.*?>', '', snippet)).strip()
                clean_url = unescape(url)
                
                # DuckDuckGo uses redirect URLs - extract real URL from uddg parameter
                if 'uddg=' in clean_url:
                    from urllib.parse import parse_qs, urlparse, unquote
                    try:
                        # Parse the redirect URL
                        parsed = urlparse(clean_url if clean_url.startswith('http') else 'https:' + clean_url)
                        params = parse_qs(parsed.query)
                        if 'uddg' in params:
                            clean_url = unquote(params['uddg'][0])
                    except:
                        pass  # Keep original URL if parsing fails
                
                # Ensure URL has scheme
                if clean_url.startswith('//'):
                    clean_url = 'https:' + clean_url
                elif not clean_url.startswith(('http://', 'https://')):
                    clean_url = 'https://' + clean_url
                
                results.append(
                    f"[{idx}] {clean_title}\n"
                    f"URL: {clean_url}\n"
                    f"{clean_snippet}"
                )
            
            if results:
                header = f"DuckDuckGo search results for: {query}\n" + "=" * 60 + "\n\n"
                return header + "\n\n".join(results)
            else:
                return (
                    f"[search_web] No valid results found for query: '{query}'\n\n"
                    "The search returned some matches but they could not be parsed. "
                    "Try a different query or use search_wiki for encyclopedia topics."
                )
                
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
                return (
                    f"[search_wiki] No Wikipedia articles found for query: '{query}'\n\n"
                    "Suggestions:\n"
                    "- Try different keywords or check spelling\n"
                    "- Use search_web for general web searches\n"
                    "- Wikipedia may not have an article on this specific topic"
                )
            
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


# ---------------------------------------------------------------------------
# Tool registry
#
# Each tool is declared once with the ``@tool`` decorator, which carries its
# name, LLM-facing schema, permission policy and handler.  ``create_toolset``
# binds those definitions to a :class:`ToolContext` and returns the
# harness-facing objects.  There is no separate wrapper module anymore.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolPolicySpec:
    """Policy metadata owned by a registered tool."""

    profile_kind: str = "simple"
    default_permission: str = "ask"
    default_settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolDefinition:
    """A registered tool: schema, policy metadata and handler(s)."""

    name: str
    description: str
    parameters: dict
    policy: ToolPolicySpec
    handler: Callable[["ToolContext", Any], Any]
    async_handler: Optional[Callable[["ToolContext", Any], Any]] = None
    is_blocking: bool = False
    include: Optional[Callable[["ToolContext"], bool]] = None


@dataclass
class ToolContext:
    """Shared resources and per-build state for tool instances."""

    toolset: Optional[MinimalToolset] = None
    workspace: Optional[Path] = None
    depth: int = 0
    pending_subagents: list = field(default_factory=list)
    search_tools: Optional[SearchTools] = None
    search_max_results: int = 3
    search_limit: Optional[int] = None
    state: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, ToolDefinition] = {}


def tool(
    *,
    name: str,
    description: str,
    parameters: dict,
    policy: Optional[ToolPolicySpec] = None,
    async_handler: Optional[Callable] = None,
    is_blocking: bool = False,
    include: Optional[Callable[[ToolContext], bool]] = None,
    key: Optional[str] = None,
):
    """Register a tool definition.  One decorator per tool — the single
    definition site for its name, schema, permission and settings.

    ``key`` lets the registry key differ from the LLM-facing ``name`` (e.g.
    the ``run`` tool is registered as ``run_command``).
    """

    def decorator(handler):
        _REGISTRY[key or name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            policy=policy or ToolPolicySpec(),
            handler=handler,
            async_handler=async_handler,
            is_blocking=is_blocking,
            include=include,
        )
        return handler

    return decorator


class RegisteredTool:
    """A registry tool bound to a :class:`ToolContext`."""

    def __init__(self, definition: ToolDefinition, context: ToolContext):
        self._definition = definition
        self._context = context
        self.name = definition.name
        self.description = definition.description
        self.parameters = definition.parameters
        self.is_blocking = definition.is_blocking
        self.policy_spec = definition.policy
        self.toolset = context.toolset

    @property
    def context(self) -> ToolContext:
        """The resources and configuration this tool was bound to."""
        return self._context

    def get_schema(self) -> dict:
        """Return the OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def cancel_active_run(self) -> bool:
        """Terminate the tool's active subprocess, if it owns one."""
        cancel = getattr(self.toolset, "cancel_active_run", None)
        return cancel() if callable(cancel) else False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RegisteredTool {self.name}>"


class _SyncTool(RegisteredTool):
    def execute(self, **kwargs):
        return self._definition.handler(self._context, **kwargs)


class _AsyncTool(RegisteredTool):
    async def execute(self, **kwargs):
        return await self._definition.handler(self._context, **kwargs)


class _AsyncCapableTool(_SyncTool):
    async def execute_async(self, **kwargs):
        return await self._definition.async_handler(self._context, **kwargs)


def _build_tool(name: str, context: ToolContext) -> RegisteredTool:
    definition = _REGISTRY[name]
    if inspect.iscoroutinefunction(definition.handler):
        return _AsyncTool(definition, context)
    if definition.async_handler is not None:
        return _AsyncCapableTool(definition, context)
    return _SyncTool(definition, context)


def registered_tool_specs() -> dict[str, ToolPolicySpec]:
    """Return policy metadata for every registered tool."""
    return {name: definition.policy for name, definition in _REGISTRY.items()}


# --- Tool handlers ---------------------------------------------------------

@tool(
    name="read",
    description=(
        "Read all or part of a UTF-8 text file from the workspace. "
        "Use offset/limit for large files or targeted inspection. Offset "
        "is zero-based and limit is the number of lines. Use "
        "include_line_numbers when you need stable references for a patch."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to workspace (e.g., 'config.py' or 'src/main.py')",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "Optional zero-based first line to return (defaults to 0)",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional number of lines to return",
            },
            "max_chars": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional maximum number of characters to return",
            },
            "include_line_numbers": {
                "type": "boolean",
                "description": "Prefix each returned line with its source line number",
            },
        },
        "required": ["path"],
    },
    policy=ToolPolicySpec("file", "allow", {"outside_repo": "deny"}),
)
def _read_tool(
    ctx: ToolContext,
    path: str,
    offset: int = 0,
    limit: int | None = None,
    max_chars: int | None = None,
    include_line_numbers: bool = False,
) -> str:
    try:
        return ctx.toolset.read(
            path,
            offset=offset,
            limit=limit,
            max_chars=max_chars,
            include_line_numbers=include_line_numbers,
        )
    except ToolError as e:
        return str(e)


@tool(
    name="write",
    description="Write content to a file in the workspace (creates or overwrites)",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to workspace"},
            "content": {"type": "string", "description": "Content to write to the file"},
        },
        "required": ["path", "content"],
    },
    policy=ToolPolicySpec("file", "allow", {"outside_repo": "deny"}),
)
def _write_tool(ctx: ToolContext, path: str, content: str) -> str:
    try:
        return ctx.toolset.write(path, content)
    except ToolError as e:
        return str(e)


@tool(
    name="patch",
    description=(
        "Modify an existing file by replacing one exact code block. "
        "Preferred format: provide path + search + replace. "
        "Use write only for creating new files or full rewrites."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to workspace"},
            "search": {
                "type": "string",
                "description": "Exact existing text block to replace (include enough context to be unique)",
            },
            "replace": {"type": "string", "description": "Replacement text block"},
            "patch_content": {
                "type": "string",
                "description": "Legacy replace-block format (backward compatible)",
            },
        },
        "required": ["path", "search", "replace"],
    },
    policy=ToolPolicySpec("file", "allow", {"outside_repo": "deny"}),
)
def _patch_tool(
    ctx: ToolContext,
    path: str = None,
    search: str = None,
    replace: str = None,
    patch_content: str = None,
) -> str:
    try:
        return ctx.toolset.patch(path=path, search=search, replace=replace, patch_content=patch_content)
    except ToolError as e:
        return str(e)


async def _run_tool_async(ctx: ToolContext, command: str) -> str:
    try:
        return await ctx.toolset.run_async(command)
    except ToolError as e:
        return str(e)


@tool(
    name="run",
    description=(
        "Execute a shell command in the workspace. "
        "Supports pipes (|), command chaining (&&, ||, ;). "
        "Safe commands are auto-allowed. Some commands require user confirmation. "
        "Blocked commands will be rejected."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute (e.g., 'ls -la', 'cat file.txt | grep pattern')",
            }
        },
        "required": ["command"],
    },
    policy=ToolPolicySpec(
        "run",
        "deny",
        {"others": "deny", "chain_policy": "ask", "use_container": False, "container_network": False},
    ),
    async_handler=_run_tool_async,
    key="run_command",
)
def _run_tool(ctx: ToolContext, command: str) -> str:
    try:
        return ctx.toolset.run(command)
    except ToolError as e:
        return str(e)


@tool(
    name="search_web",
    description=(
        "Search the web using DuckDuckGo. Returns top search results with titles, URLs, and snippets. "
        "Use this for: library documentation, API references, recent news, troubleshooting, "
        "technical queries, comparisons, and general web searches. "
        "Prefer this over search_wiki for most queries unless searching for a specific entity or concept."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'python asyncio tutorial', 'rust error handling best practices')",
            },
            "time_range": {
                "type": "string",
                "enum": ["day", "week", "month", "year"],
                "description": "Optional: filter results by recency (useful for news or recent library updates)",
            },
        },
        "required": ["query"],
    },
    policy=ToolPolicySpec("search", "allow"),
)
def _search_web_tool(ctx: ToolContext, query: str, time_range: Optional[str] = None) -> str:
    limit = ctx.search_limit
    if limit is not None and ctx.state.get("search_web_count", 0) >= limit:
        return f"[search_web] Rate limit reached ({limit} searches per session)"
    ctx.state["search_web_count"] = ctx.state.get("search_web_count", 0) + 1
    try:
        return ctx.search_tools.search_web(query, max_results=ctx.search_max_results, time_range=time_range)
    except ToolError as e:
        return f"[search_web] {str(e)}"


@tool(
    name="search_wiki",
    description=(
        "Search Wikipedia for encyclopedic information. Returns top results with titles, URLs, and snippets. "
        "Use this for: named entities (people, places, organizations), concepts with canonical definitions, "
        "historical events, scientific concepts, algorithms, data structures, and programming paradigms. "
        "NOT recommended for library-specific documentation or recent news."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'Python programming language', 'Binary search algorithm')",
            }
        },
        "required": ["query"],
    },
    policy=ToolPolicySpec("search", "allow"),
)
def _search_wiki_tool(ctx: ToolContext, query: str) -> str:
    limit = ctx.search_limit
    if limit is not None and ctx.state.get("search_wiki_count", 0) >= limit:
        return f"[search_wiki] Rate limit reached ({limit} searches per session)"
    ctx.state["search_wiki_count"] = ctx.state.get("search_wiki_count", 0) + 1
    try:
        return ctx.search_tools.search_wiki(query, max_results=ctx.search_max_results)
    except ToolError as e:
        return f"[search_wiki] {str(e)}"


class _SubagentContextError(Exception):
    def __init__(self, tokens: int):
        self.tokens = tokens


async def _run_subagent(ctx: ToolContext, task: str) -> str:
    from pico_chat import pico_cfg
    from pico_chat.harness.harness import Harness
    from pico_chat.harness import chunks as chunk_types

    timeout = pico_cfg.config.subagent_timeout
    max_context = pico_cfg.config.subagent_max_context

    sub = Harness(workspace_path=str(ctx.workspace), depth=ctx.depth + 1)

    result_parts = []
    cumulative_tokens = 0
    last_call_tokens = 0
    in_assistant_turn = False

    async def _collect():
        nonlocal cumulative_tokens, last_call_tokens, in_assistant_turn
        async for chunk in sub.chat(task):
            if isinstance(chunk, chunk_types.MessageStart):
                if chunk.role == "assistant":
                    if in_assistant_turn:
                        cumulative_tokens += last_call_tokens
                        last_call_tokens = 0
                    in_assistant_turn = True
            elif isinstance(chunk, chunk_types.Content):
                result_parts.append(chunk.content)
            elif isinstance(chunk, chunk_types.GenerationMetrics):
                last_call_tokens = chunk.tokens
                if max_context and (cumulative_tokens + last_call_tokens) > max_context:
                    raise _SubagentContextError(cumulative_tokens + last_call_tokens)

    try:
        await asyncio.wait_for(_collect(), timeout=timeout)
    except asyncio.TimeoutError:
        return f"[subagent timed out after {timeout}s]"
    except _SubagentContextError as e:
        return f"[subagent aborted: context limit exceeded ({e.tokens} > {max_context} tokens)]"

    return "".join(result_parts) or "[subagent returned no response]"


def _subagent_available(ctx: ToolContext) -> bool:
    from pico_chat import pico_cfg

    return ctx.depth < pico_cfg.config.subagent_max_depth


@tool(
    name="subagent",
    description=(
        "Spawn a read-only scaffolding subagent to explore the codebase and return findings. "
        "The subagent can only read files — it cannot write, patch, or run commands. "
        "Set background=true to queue multiple subagents in parallel; "
        "collect their results with wait_for_subagents. "
        "Returns the subagent's complete text response (foreground) or a queue confirmation (background)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task for the subagent. Be explicit — it has no conversation history.",
            },
            "background": {
                "type": "boolean",
                "description": "If true, run in background and return immediately. Collect results with wait_for_subagents.",
            },
        },
        "required": ["task"],
    },
    policy=ToolPolicySpec("simple", "ask"),
    include=_subagent_available,
)
async def _subagent_tool(ctx: ToolContext, task: str, background: bool = False) -> str:
    from pico_chat import pico_cfg

    if ctx.depth >= pico_cfg.config.subagent_max_depth:
        return f"[subagent] Depth limit reached ({pico_cfg.config.subagent_max_depth})."

    if not background:
        return await _run_subagent(ctx, task)

    index = len(ctx.pending_subagents)
    future = asyncio.create_task(_run_subagent(ctx, task))
    ctx.pending_subagents.append({"index": index, "task": task, "future": future})
    return f"[subagent:{index}] Queued in background."


@tool(
    name="wait_for_subagents",
    description=(
        "Wait for all background subagents to finish and return their results. "
        "Call this after launching subagents with background=true."
    ),
    parameters={"type": "object", "properties": {}, "required": []},
    policy=ToolPolicySpec("simple", "ask"),
)
async def _wait_for_subagents_tool(ctx: ToolContext) -> str:
    if not ctx.pending_subagents:
        return "[wait_for_subagents] No pending subagents."

    pending = list(ctx.pending_subagents)
    futures = [p["future"] for p in pending]
    results = await asyncio.gather(*futures, return_exceptions=True)
    ctx.pending_subagents.clear()

    parts = []
    for p, result in zip(pending, results):
        if isinstance(result, Exception):
            parts.append(f"[subagent:{p['index']}] Error: {result}")
        else:
            parts.append(f"[subagent:{p['index']}] Task: {p['task']}\n{result}")

    return "\n\n".join(parts)


# --- Public factories (kept for direct construction/tests) -----------------

def RunTool(toolset: MinimalToolset) -> RegisteredTool:
    """Build the run tool bound to a toolset."""
    return _build_tool("run_command", ToolContext(toolset=toolset))


def SearchWebTool(search_tools: SearchTools, max_results: int = 3,
                  search_limit: Optional[int] = None) -> RegisteredTool:
    """Build the search_web tool bound to a search backend."""
    return _build_tool("search_web", ToolContext(
        search_tools=search_tools, search_max_results=max_results, search_limit=search_limit,
    ))


def SearchWikiTool(search_tools: SearchTools, max_results: int = 3,
                   search_limit: Optional[int] = None) -> RegisteredTool:
    """Build the search_wiki tool bound to a search backend."""
    return _build_tool("search_wiki", ToolContext(
        search_tools=search_tools, search_max_results=max_results, search_limit=search_limit,
    ))


def SubagentTool(workspace_path, depth: int, pending_subagents: list) -> RegisteredTool:
    """Build the subagent tool."""
    return _build_tool("subagent", ToolContext(
        workspace=Path(workspace_path).resolve() if workspace_path else None,
        depth=depth,
        pending_subagents=pending_subagents,
    ))


def WaitForSubagentsTool(pending_subagents: Optional[list] = None) -> RegisteredTool:
    """Build the wait_for_subagents tool."""
    return _build_tool("wait_for_subagents", ToolContext(
        pending_subagents=pending_subagents if pending_subagents is not None else [],
    ))


def create_toolset(
    workspace_path: str | Path,
    confirmation_callback: Optional[Callable[[str], bool]] = None,
    permissions=None,
    depth: int = 0,
    pending_subagents: Optional[list] = None,
) -> dict[str, RegisteredTool]:
    """
    Create the registered toolset with harness-compatible wrappers.

    Args:
        workspace_path: Root directory for all operations
        confirmation_callback: Function to prompt user for command confirmation
        permissions: Role or ToolPermissionsProfile to use (defaults to global)
        depth: Current subagent depth (0 = top-level harness)
        pending_subagents: Shared list for background subagent tracking

    Returns:
        Dict of tool name to registered tool
    """
    toolset = MinimalToolset(workspace_path, confirmation_callback, permissions=permissions)

    if depth > 0:
        # Subagent: more results per search, but limited number of searches
        search_max_results = 10
        search_limit = 3
    else:
        # Main agent: fewer results per search, unlimited searches
        search_max_results = 3
        search_limit = None

    context = ToolContext(
        toolset=toolset,
        workspace=Path(workspace_path).resolve(),
        depth=depth,
        pending_subagents=pending_subagents if pending_subagents is not None else [],
        search_tools=SearchTools(),
        search_max_results=search_max_results,
        search_limit=search_limit,
    )

    return {
        name: _build_tool(name, context)
        for name, definition in _REGISTRY.items()
        if definition.include is None or definition.include(context)
    }


__all__ = [
    "ToolError",
    "FileTools",
    "ShellTool",
    "MinimalToolset",
    "SearchTools",
    "ToolPolicySpec",
    "ToolContext",
    "RegisteredTool",
    "tool",
    "registered_tool_specs",
    "create_toolset",
    "RunTool",
    "SearchWebTool",
    "SearchWikiTool",
    "SubagentTool",
    "WaitForSubagentsTool",
]
