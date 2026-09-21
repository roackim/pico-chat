"""Server commands.

Servers are defined in ``pico.toml``. There is no in-TUI editor for them:
``/server edit`` opens the file in ``$EDITOR`` and the config is reloaded when
the editor exits. ``/server use`` selects an endpoint at runtime.
"""

from __future__ import annotations

import asyncio
from typing import List

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol, Command, Param, server_name_completions


def _activate_endpoint(ui: ChatUIProtocol, endpoint) -> None:
    """Switch the agent to ``endpoint`` and refresh/prewarm the status bar."""
    ui.agent.switch_server(endpoint)
    from pico_chat.harness.endpoint import prewarm_local_resolution

    prewarm_local_resolution(endpoint._original_base_url)

    async def _prewarm():
        await endpoint.prewarm_model_name()
        if hasattr(ui, "refresh_status_bar"):
            ui.refresh_status_bar()

    asyncio.ensure_future(_prewarm())
    if hasattr(ui, "refresh_status_bar"):
        ui.refresh_status_bar()


class ServerListCommand(Command):
    def __init__(self):
        super().__init__("list", "List all configured servers")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        servers = pico_cfg.config.servers
        if not servers:
            ui.chat_history_panel.add_message(
                "No servers configured.\n\n"
                "Add one by editing your config: /config",
                msg_type=SysMsg(), title="server")
            return
        color, muted, active, reset = (
            str(theme.DEFAULT), str(theme.MUTED), str(theme.SUCCESS), theme.reset())
        active_name = pico_cfg.config.active_server
        lines = [f"{color}Configured servers:{reset}", ""]
        for name, cfg in sorted(servers.items()):
            server_type = cfg.get("type", "unknown")
            detail = cfg.get("model", cfg.get("base_url", "unknown"))
            marker = "*" if name == active_name else " "
            lines.append(
                f"{marker} {active if name == active_name else color}{name}{reset} "
                f"{muted}({server_type}) - {detail}{reset}")
        ui.chat_history_panel.add_message("\n".join(lines), msg_type=SysMsg())


class ServerUseCommand(Command):
    def __init__(self):
        super().__init__("use", "Switch to a configured server",
                         params=[Param("NAME", completions=server_name_completions)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /server use <name>", msg_type=SysMsgError())
            return
        name = args[0]
        if name not in pico_cfg.config.servers:
            ui.chat_history_panel.add_message(
                f"Server '{name}' not found.\n\nUse '/server list' to see configured servers.",
                msg_type=SysMsgError(), title="server")
            return
        from pico_chat.harness.endpoint import get_endpoint

        pico_cfg.config.set_active_server(name)
        endpoint = get_endpoint(name)
        if endpoint is None:
            ui.chat_history_panel.add_message(
                f"Failed to parse server '{name}'.", msg_type=SysMsgError(), title="server")
            return
        _activate_endpoint(ui, endpoint)
        ui.chat_history_panel.add_message(f"Switched to '{name}'.", msg_type=SysMsg(), title="server")


class ServerEditCommand(Command):
    def __init__(self):
        super().__init__("edit", "Open pico.toml in your editor and reload it")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.ui.external_editor import open_editor

        path = pico_cfg.config.ensure_config_file()
        open_editor(ui, path)
        errors = pico_cfg.reload_config()
        if errors:
            ui.chat_history_panel.add_message(
                "Config reloaded with errors:\n" + "\n".join(errors),
                msg_type=SysMsgError(), title="server")
        else:
            ui.chat_history_panel.add_message("Config reloaded.", msg_type=SysMsg(), title="server")


class ServerRemoveCommand(Command):
    def __init__(self):
        super().__init__("remove", "Remove a server configuration",
                         params=[Param("SERVER_NAME", completions=server_name_completions)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /server remove <name>", msg_type=SysMsgError())
            return
        name = args[0]
        was_active = pico_cfg.config.active_server == name
        if not pico_cfg.config.remove_server(name):
            ui.chat_history_panel.add_message(f"Server '{name}' not found.", msg_type=SysMsgError())
            return
        message = f"Removed server '{name}'"
        if was_active:
            from pico_chat.harness.endpoint import get_active_endpoint

            _activate_endpoint(ui, get_active_endpoint())
            message += f"\nSwitched to '{pico_cfg.config.active_server}'"
        ui.chat_history_panel.add_message(message, msg_type=SysMsg(), title="server")


class ServerInfoCommand(Command):
    def __init__(self):
        super().__init__("info", "Show full details for a server configuration",
                         params=[Param("SERVER_NAME", completions=server_name_completions)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /server info <name>", msg_type=SysMsgError())
            return
        cfg = pico_cfg.config.servers.get(args[0])
        if cfg is None:
            ui.chat_history_panel.add_message(f"Server '{args[0]}' not found.", msg_type=SysMsgError())
            return
        reset, color = theme.reset(), str(theme.WARNING)
        fields = [
            ("Name", args[0]),
            ("Type", cfg.get("type", "unknown")),
            ("Base URL", cfg.get("base_url", "unknown")),
            ("Model", cfg.get("model", "-")),
            ("Timeout", f"{cfg.get('timeout', 30.0)}s"),
            ("Retry attempts", cfg.get("retry_attempts", 3)),
        ]
        msg = "\n".join(f"{color}{label:<17}: {reset}{value}" for label, value in fields)
        ui.chat_history_panel.add_message(msg, msg_type=SysMsg(), title="server")


class ServerDiagnoseCommand(Command):
    def __init__(self):
        super().__init__("diagnose", "Test connectivity to a server and show the reason on failure",
                         params=[Param("SERVER_NAME", completions=server_name_completions)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /server diagnose <name>", msg_type=SysMsgError())
            return
        from pico_chat.harness.endpoint import get_endpoint

        endpoint = get_endpoint(args[0])
        if endpoint is None:
            ui.chat_history_panel.add_message(
                f"Server '{args[0]}' not found.\n\nUse '/server list' to see available servers.",
                msg_type=SysMsgError())
            return
        diagnosis = await endpoint.diagnose_connection()
        ui.chat_history_panel.add_message(diagnosis.message(), msg_type=SysMsg())
        if hasattr(ui, "refresh_status_bar"):
            ui.refresh_status_bar()


class ServerCommand(Command):
    def __init__(self):
        remove = ServerRemoveCommand()
        super().__init__("server", "Manage LLM server configurations", subcommands={
            "list": ServerListCommand(),
            "use": ServerUseCommand(),
            "edit": ServerEditCommand(),
            "info": ServerInfoCommand(),
            "remove": remove, "rm": remove,
            "diagnose": ServerDiagnoseCommand(),
        })

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            await self.subcommands["list"].execute(ui, [])
            return
        name = args[0].lower()
        if name in self.subcommands:
            await self.subcommands[name].execute(ui, args[1:])
        else:
            ui.chat_history_panel.add_message(
                f"Unknown subcommand: {name}\nAvailable: {', '.join(sorted(self.subcommands))}",
                msg_type=SysMsgError())


__all__ = [
    "ServerCommand", "ServerListCommand", "ServerUseCommand", "ServerEditCommand",
    "ServerRemoveCommand", "ServerInfoCommand", "ServerDiagnoseCommand",
]
