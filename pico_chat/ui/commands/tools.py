"""Tool inspection commands."""

from __future__ import annotations

from typing import List

from .base import ChatUIProtocol


async def cmd_tools(ui: ChatUIProtocol, args: List[str]):
    role = getattr(getattr(ui, "agent", None), "role", None)
    if role is not None:
        lines = [f"role: {role.name}"]
        for tool_name in sorted(role.tools):
            lines.append(f"{tool_name.ljust(18)} - {_role_label(role, tool_name)}")
        ui.show_popup("tools", "\n".join(lines))
        return

    from pico_chat.harness.permissions import permissions

    available_tools: List[str] = []
    if hasattr(ui.agent, "tools_map") and isinstance(ui.agent.tools_map, dict):
        available_tools = sorted(ui.agent.tools_map.keys())
    if not available_tools:
        available_tools = ["read", "write", "patch", "run"]

    lines = [f"profile: {permissions.name}"]
    for tool_name in available_tools:
        lines.append(f"{tool_name.ljust(10)} - {_profile_label(permissions, tool_name)}")
    ui.show_popup("tools", "\n".join(lines))


def _role_label(role, tool_name: str) -> str:
    policy = role.policy_for(tool_name)
    if not policy.enabled:
        return "disabled"
    if tool_name in ("read", "write", "patch"):
        inside = policy.settings.get("inside_repo", policy.permission)
        outside = policy.settings.get("outside_repo", "deny")
        return f"enabled inside={inside} outside={outside}"
    if tool_name == "run_command":
        settings = policy.settings
        return (
            f"enabled allow={len(settings.get('allow', []))} "
            f"ask={len(settings.get('ask', []))} deny={len(settings.get('deny', []))} "
            f"others={settings.get('others', policy.permission)} "
            f"chain={settings.get('chain_policy', 'ask')}"
        )
    return f"enabled permission={policy.permission}"


def _profile_label(profile, tool_name: str) -> str:
    if tool_name == "read":
        return f"inside={profile.read.inside_repo} outside={profile.read.outside_repo}"
    if tool_name == "write":
        return f"inside={profile.write.inside_repo} outside={profile.write.outside_repo}"
    if tool_name == "patch":
        return f"inside={profile.patch.inside_repo} outside={profile.patch.outside_repo}"
    if tool_name == "run":
        return (
            f"allow={len(profile.run.allow)} ask={len(profile.run.ask)} "
            f"deny={len(profile.run.deny)} others={profile.run.others} "
            f"chain={profile.run.chain_policy}"
        )
    return "unknown"


__all__ = ["cmd_tools"]
