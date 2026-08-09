"""Server configuration commands."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol, Command, Param, server_name_completions


class ServerAddCommand(Command):
    def __init__(self):
        super().__init__("add", "Add a named LLM server configuration", params=[
            Param("NAME", required=True),
            Param("TYPE", completions=["openrouter", "llamacpp"], required=True),
            Param("MODEL_OR_URL", required=True),
            Param("PROVIDER"),
        ])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            self._show_form(ui)
            return
        if len(args) < 3:
            ui.chat_history_panel.add_message(
                "Usage: /server add <name> <type> <model/url> [provider]",
                msg_type=SysMsgError())
            return
        await self._execute_add(ui, args[0], args[1].lower(), args[2],
                                args[3] if len(args) > 3 else None)

    def _show_form(self, ui: ChatUIProtocol):
        from pico_chat.ui.tui.components.form import TextField, RadioListField

        fields = [
            TextField("Name", required=True, placeholder="my-server"),
            RadioListField("Type", options=["openrouter", "llamacpp"], value=0, required=True),
            TextField("Model or URL", required=True, placeholder="anthropic/claude-3.5-sonnet"),
            TextField("Provider", placeholder="(optional, OpenRouter only)"),
        ]

        def submit(values):
            server_type = "openrouter" if values.get("Type") == 0 else "llamacpp"
            name = values.get("Name", "").strip()
            model_url = values.get("Model or URL", "").strip()
            provider = values.get("Provider", "").strip() or None
            if not name or not model_url:
                ui.chat_history_panel.add_message(
                    "Name and Model/URL are required.", msg_type=SysMsgError(), title="server")
                return
            asyncio.ensure_future(self._execute_add(ui, name, server_type, model_url, provider))

        ui.show_form_popup("Add Server", fields, submit)

    async def _execute_add(self, ui: ChatUIProtocol, name: str, server_type: str,
                           model_url: str, provider: Optional[str]):
        from pico_chat.harness.server_service import ServerService
        service = ServerService()
        if server_type == "openrouter":
            result = await service.add_openrouter(name, model_url, provider)
        elif server_type == "llamacpp":
            result = await service.add_llamacpp(name, model_url)
        else:
            ui.chat_history_panel.add_message(
                f"Unknown server type: {server_type}", msg_type=SysMsgError(), title="server")
            return
        ui.chat_history_panel.add_message(
            result.message, msg_type=SysMsg() if result.ok else SysMsgError(), title="server")


class ServerListCommand(Command):
    def __init__(self):
        super().__init__("list", "List all configured servers")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.server_service import ServerService
        servers = ServerService().list_servers()
        if not servers:
            ui.chat_history_panel.add_message("No servers configured.", msg_type=SysMsg())
            return
        color, muted, active, reset = str(theme.DEFAULT), str(theme.MUTED), str(theme.SUCCESS), theme.reset()
        lines = [f"{color}Configured servers:{reset}", ""]
        for name, server_type, is_active in servers:
            cfg = pico_cfg.config.servers[name]
            line = f"{active if is_active else color}{name}{reset} {muted}({server_type}){reset}"
            line += f" {muted}- {cfg.get('model', cfg.get('base_url', 'unknown'))}{reset}"
            lines.append(line)
        ui.chat_history_panel.add_message("\n".join(lines), msg_type=SysMsg())


class ServerUseCommand(Command):
    def __init__(self):
        super().__init__("use", "Switch to a different server configuration",
                         params=[Param("SERVER_NAME", completions=server_name_completions)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /server use <name>", msg_type=SysMsgError())
            return
        from pico_chat.harness.server_service import ServerService
        result = ServerService().switch_server(args[0])
        if not result.ok:
            ui.chat_history_panel.add_message(result.message, msg_type=SysMsgError())
            return
        try:
            ui.agent.switch_server(result.new_config)
            ui.chat_history_panel.add_message(result.message, msg_type=SysMsg())
        except Exception as exc:
            ui.chat_history_panel.add_message(f"Error switching server: {exc}", msg_type=SysMsgError())


class ServerRemoveCommand(Command):
    def __init__(self):
        super().__init__("remove", "Remove a server configuration",
                         params=[Param("SERVER_NAME", completions=server_name_completions)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /server remove <name>", msg_type=SysMsgError())
            return
        from pico_chat.harness.server_service import ServerService
        result = ServerService().remove_server(args[0])
        if not result.ok:
            ui.chat_history_panel.add_message(result.message, msg_type=SysMsgError())
            return
        if result.new_config is not None:
            ui.agent.switch_server(result.new_config)
        ui.chat_history_panel.add_message(result.message, msg_type=SysMsg())


class ServerInfoCommand(Command):
    def __init__(self):
        super().__init__("info", "Show full details for a server configuration",
                         params=[Param("SERVER_NAME", completions=server_name_completions)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /server info <name>", msg_type=SysMsgError())
            return
        from pico_chat.harness.server_service import ServerService
        info = ServerService().get_server_info(args[0])
        if info is None:
            ui.chat_history_panel.add_message(f"Server '{args[0]}' not found.", msg_type=SysMsgError())
            return
        reset, color = theme.reset(), str(theme.WARNING)
        msg = f"{color}Name             : {reset}{info.name}"
        msg += f"\n{color}Type             : {reset}{info.server_type}"
        msg += f"\n{color}Base URL         : {reset}{info.base_url or 'unknown'}"
        msg += f"\n{color}Timeout          : {reset}{info.timeout}s"
        msg += f"\n{color}Retry Attempts   : {reset}{info.retry_attempts}"
        ui.chat_history_panel.add_message(msg, msg_type=SysMsg(), title="server")


class ServerCommand(Command):
    def __init__(self):
        remove = ServerRemoveCommand()
        super().__init__("server", "Manage LLM server configurations", subcommands={
            "add": ServerAddCommand(), "list": ServerListCommand(), "use": ServerUseCommand(),
            "info": ServerInfoCommand(), "remove": remove, "rm": remove,
        })

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /server <subcommand> [options]", msg_type=SysMsgError())
            return
        name = args[0].lower()
        if name in self.subcommands:
            await self.subcommands[name].execute(ui, args[1:])
        else:
            ui.chat_history_panel.add_message(
                f"Unknown subcommand: {name}\nAvailable: {', '.join(sorted(self.subcommands))}",
                msg_type=SysMsgError())

__all__ = [
    "ServerCommand", "ServerAddCommand", "ServerListCommand",
    "ServerUseCommand", "ServerRemoveCommand", "ServerInfoCommand",
]
