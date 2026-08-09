"""
Permission gate for tool execution.

Encapsulates the permission-checking logic that was previously inlined in
``Harness._check_tool_permission`` and ``Harness._build_permission_prompt``.

Responsibilities:
- Resolve whether a file path is inside the workspace (deduplicating the
  read/write/patch path-resolution logic).
- Check tool permissions against the active ``ToolPermissionsProfile``.
- Build human-readable permission prompts for the UI.
- Manage the async user-response queue for interactive permission prompts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from pico_chat.harness import tool_permissions as _tp_module
from pico_chat.harness.tool_permissions import ToolPermissionsProfile


class PermissionGate:
    """Checks tool permissions and manages user-confirmation prompts.

    Owns the ``_user_response_queue`` so the Harness doesn't have to.
    """

    def __init__(
        self,
        workspace: str,
        permissions: Optional[ToolPermissionsProfile] = None,
        enabled_tools: Optional[set[str]] = None,
    ):
        self._workspace = workspace
        self._workspace_resolved = Path(workspace).resolve()
        self._permissions = permissions  # None = use global default
        self._enabled_tools = enabled_tools
        self._user_response_queue: asyncio.Queue[str] = asyncio.Queue()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def permissions(self) -> ToolPermissionsProfile:
        """The active permission profile (falls back to the global default)."""
        return self._permissions if self._permissions is not None else _tp_module.permissions

    def set_user_response(self, text: str):
        """Called by the UI when a response to a tool's prompt is ready."""
        self._user_response_queue.put_nowait(text)

    def set_policy(self, permissions: ToolPermissionsProfile, enabled_tools: set[str]) -> None:
        """Replace the active role policy for a conversation."""
        self._permissions = permissions
        self._enabled_tools = set(enabled_tools)

    async def wait_for_user_input(self, prompt: str) -> str:
        """Wait for the user to provide text via the UI."""
        return await self._user_response_queue.get()

    def check(self, tool_name: str, args: dict) -> str:
        """Check tool permission status.

        Returns:
            ``"allow"`` — auto-approve
            ``"ask"`` — need user permission
            ``"deny"`` — auto-deny
        """
        tool_name = "run_command" if tool_name == "run" else tool_name
        if self._enabled_tools is not None and tool_name not in self._enabled_tools:
            return "deny"

        perms = self.permissions

        if tool_name in ("read", "write", "patch"):
            path = args.get("path", "")
            is_inside = self._is_inside_workspace(path)
            if tool_name == "read":
                return perms.get_read_permission(is_inside)
            elif tool_name == "write":
                return perms.get_write_permission(is_inside)
            else:
                return perms.get_patch_permission(is_inside)

        elif tool_name == "run_command":
            return self._check_run_permission(args, perms)

        elif tool_name in ("search_web", "search_wiki"):
            return perms.get_search_permission()

        elif tool_name in ("subagent", "wait_for_subagents"):
            # Delegation can execute tools in a child harness, so it must not
            # bypass the active profile's approval policy.
            return "ask"

        return "ask"  # Default to asking

    @staticmethod
    def build_prompt(tool_name: str, args: dict) -> str:
        """Build a human-readable permission prompt for a tool call."""
        if tool_name == "read":
            return f"Allow reading file: {args.get('path', 'unknown')}?"
        elif tool_name == "write":
            return f"Allow writing to file: {args.get('path', 'unknown')}?"
        elif tool_name == "patch":
            return f"Allow patching file: {args.get('path', 'unknown')}?"
        elif tool_name in ("run", "run_command"):
            command = args.get("command", "unknown")
            return f"Allow running command: {command}?"
        return f"Allow {tool_name}?"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_inside_workspace(self, path: str) -> bool:
        """Resolve a path and check if it's inside the workspace root."""
        try:
            if Path(path).is_absolute():
                target = Path(path).resolve()
            else:
                target = (self._workspace_resolved / path).resolve()
            target.relative_to(self._workspace_resolved)
            return True
        except Exception:
            return False

    def _check_run_permission(self, args: dict, perms: ToolPermissionsProfile) -> str:
        """Check shell command permission via SecurityChecker."""
        from pico_chat.harness.security import SecurityChecker

        command = args.get("command", "")
        run_perms = perms.get_run_permission()
        checker = SecurityChecker(run_perms, confirmation_callback=None)
        allowed, message = checker.check_chain(command)

        if not allowed:
            # Distinguish hard-deny from ask based on the message content.
            # TODO: push a typed return into SecurityChecker so we don't
            # string-parse here.
            lower = message.lower()
            if "blocked" in lower or "not in allowlist" in lower:
                return "deny"
            return "ask"
        return "allow"
