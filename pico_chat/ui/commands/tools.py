"""Tool inspection commands."""

from __future__ import annotations

from typing import List

from .base import ChatUIProtocol, Command


class ToolsCommand(Command):
    def __init__(self):
        super().__init__("tools", "Show available tools and their permissions")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.tool_permissions import permissions

        available_tools: List[str] = []
        if hasattr(ui.agent, 'tools_map') and isinstance(ui.agent.tools_map, dict):
            available_tools = sorted(ui.agent.tools_map.keys())

        if not available_tools:
            available_tools = ["read", "write", "patch", "run"]

        def permission_label(tool_name: str) -> str:
            if tool_name == "read":
                return f"inside={permissions.read.inside_repo} outside={permissions.read.outside_repo}"
            if tool_name == "write":
                return f"inside={permissions.write.inside_repo} outside={permissions.write.outside_repo}"
            if tool_name == "patch":
                return f"inside={permissions.patch.inside_repo} outside={permissions.patch.outside_repo}"
            if tool_name == "run":
                return (
                    f"allow={len(permissions.run.allow)} ask={len(permissions.run.ask)} "
                    f"deny={len(permissions.run.deny)} others={permissions.run.others} "
                    f"chain={permissions.run.chain_policy}"
                )
            return "unknown"

        lines = [f"profile: {permissions.name}"]
        for tool_name in available_tools:
            lines.append(f"{tool_name.ljust(10)} - {permission_label(tool_name)}")

        ui.show_popup("tools", "\n".join(lines))


__all__ = ["ToolsCommand"]
