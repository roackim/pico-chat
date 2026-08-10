"""Commands for discovering and selecting models on the active endpoint."""

from __future__ import annotations

from typing import List

from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol, Command, Param


class ModelListCommand(Command):
    def __init__(self):
        super().__init__("list", "List models exposed by the active endpoint")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.server_service import ServerService

        try:
            models = await ServerService().list_models()
        except Exception as exc:
            ui.chat_history_panel.add_message(
                f"Could not list models: {exc}", msg_type=SysMsgError(), title="model")
            return

        selected = getattr(getattr(ui.agent, "server", None), "selected_model", None)
        if not models:
            ui.chat_history_panel.add_message(
                "No models were discovered on the active endpoint.", msg_type=SysMsg())
            return

        lines = [f"{str(theme.DEFAULT)}Models:{theme.reset()}"]
        for model in models:
            marker = "*" if model.id == selected else " "
            context = f" ({model.context_window:,} tokens)" if model.context_window else ""
            lines.append(f"{marker} {model.id}{context}")
        ui.chat_history_panel.add_message("\n".join(lines), msg_type=SysMsg(), title="model")


class ModelUseCommand(Command):
    def __init__(self):
        super().__init__("use", "Select a model on the active endpoint",
                         params=[Param("MODEL", required=True)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /model use <model>", msg_type=SysMsgError())
            return

        model = " ".join(args).strip()
        try:
            ui.agent.switch_model(model)
            from pico_chat.harness.server_service import ServerService
            ServerService().select_model(model)
            if hasattr(ui, "refresh_status_bar"):
                ui.refresh_status_bar()
            ui.chat_history_panel.add_message(
                f"Selected model {model} on {ui.agent.server.config.name}.",
                msg_type=SysMsg(), title="model")
        except Exception as exc:
            ui.chat_history_panel.add_message(
                f"Could not select model: {exc}", msg_type=SysMsgError(), title="model")


class ModelCommand(Command):
    def __init__(self):
        super().__init__("model", "Discover and select models", subcommands={
            "list": ModelListCommand(),
            "use": ModelUseCommand(),
        })

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            await self.subcommands["list"].execute(ui, [])
            return
        subcommand = self.subcommands.get(args[0].lower())
        if subcommand is None:
            ui.chat_history_panel.add_message(
                "Usage: /model [list|use <model>]", msg_type=SysMsgError())
            return
        await subcommand.execute(ui, args[1:])


__all__ = ["ModelCommand", "ModelListCommand", "ModelUseCommand"]
