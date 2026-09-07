"""Commands for discovering and selecting models across all servers.

The unit of selection is a ``(server, model)`` pair. ``/model <model>``
resolves the model against the discovery catalog, shows which server serves
it, and — if unambiguous — switches to that server and selects the model.
"""

from __future__ import annotations

from typing import List, Optional

from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol, Command, Param


def _model_completions() -> List[str]:
    """Return model ids across all servers for fuzzy completion."""
    from pico_chat.harness.server_service import ServerService
    return ServerService().model_completions()


class ModelListCommand(Command):
    def __init__(self):
        super().__init__("list", "List models across all servers")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.server_service import ServerService

        service = ServerService()
        # Discover live from every reachable server, falling back to the cache.
        models = await service.discover_all_models()
        if not models:
            ui.chat_history_panel.add_message(
                "No models discovered yet.\n\n"
                "Add a server with '/server add' or check that a configured "
                "endpoint is reachable.",
                msg_type=SysMsg(), title="model")
            return

        active_server = getattr(getattr(ui.agent, "server", None), "config", None)
        active_name = getattr(active_server, "name", None)
        selected = getattr(getattr(ui.agent, "server", None), "selected_model", None)

        lines = [f"{str(theme.DEFAULT)}Models:{theme.reset()}"]
        for model in sorted(models, key=lambda m: (m.metadata.get("_server", ""), m.id)):
            server = model.metadata.get("_server", "?")
            marker = "*" if (server == active_name and model.id == selected) else " "
            context = f" ({model.context_window:,} tokens)" if model.context_window else ""
            lines.append(f"{marker} {model.id}{context} {str(theme.MUTED)}[{server}]{theme.reset()}")
        ui.chat_history_panel.add_message("\n".join(lines), msg_type=SysMsg(), title="model")


def _split_server_model(raw: str, service) -> tuple[Optional[str], str]:
    """Split an input into (server, model), or (None, raw) if no server prefix.

    Supports the explicit ``<server>:<model>`` form. The model id may itself
    contain colons (e.g. an Ollama tag like ``Qwen3.8-27B-think:low``), so we
    only split on the first occurrence of a known server name followed by
    ``:``. Returns ``(None, raw)`` when the arg is just a model id.
    """
    from pico_chat import pico_cfg
    for server_name in sorted(pico_cfg.config.servers.keys(), key=len, reverse=True):
        prefix = f"{server_name}:"
        if raw.startswith(prefix) and len(raw) > len(prefix):
            return server_name, raw[len(prefix):]
    return None, raw


class ModelUseCommand(Command):
    def __init__(self):
        super().__init__("use", "Select a model, switching to the server that serves it",
                         params=[Param("MODEL", completions=_model_completions, required=True)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /model <model>", msg_type=SysMsgError())
            return

        from pico_chat.harness.server_service import ServerService
        service = ServerService()

        raw = " ".join(args).strip()
        # Support an explicit "<server>:<model>" form where the model id may
        # itself contain colons (e.g. Ollama quantized tags like
        # "metallama:Qwen3.8-27B-think:low"). We only split on the FIRST
        # occurrence of "<known-server>:"; otherwise the whole arg is a model.
        server_hint, model = _split_server_model(raw, service)
        if server_hint is None:
            servers = service.resolve_model_servers(model)
            if not servers:
                # Discovery is fast — bootstrap discovery so /model works
                # immediately after /server add.
                try:
                    await service.discover_all_models()
                    servers = service.resolve_model_servers(model)
                except Exception:
                    servers = service.resolve_model_servers(model)
        else:
            servers = [server_hint]

        if not servers:
            ui.chat_history_panel.add_message(
                f"Model '{model}' not found on any configured server.\n\n"
                "Run '/model list' to see discovered models, or add a server "
                "with '/server add'.",
                msg_type=SysMsgError(), title="model")
            return

        if len(servers) > 1:
            # Prefer the active server if it serves the model, so the common
            # case resolves without ambiguity.
            active_name = getattr(getattr(ui.agent, "server", None), "config", None)
            active_name = getattr(active_name, "name", None)
            if active_name in servers:
                server = active_name
            else:
                ui.chat_history_panel.add_message(
                    f"Model '{model}' is served by multiple servers:\n"
                    + "\n".join(f"  - {s}" for s in servers) + "\n\n"
                    "Run '/model list' to see which server each model is "
                    "served by, then select the one you want.",
                    msg_type=SysMsgError(), title="model")
                return
        else:
            server = servers[0]

        try:
            # Switch the harness to the serving server, then select the model.
            from pico_chat.harness.llm_server_config import get_server_config_by_name
            config = get_server_config_by_name(server)
            if config is None:
                ui.chat_history_panel.add_message(
                    f"Server '{server}' not found.", msg_type=SysMsgError(), title="model")
                return
            ui.agent.switch_server(config)
            ui.agent.switch_model(model)
            service.select_model(model, server=server)
            # Pre-warm the new server's connection and model name so the
            # status bar reflects it (green) instead of staying "checking".
            srv = getattr(ui.agent, "server", None)
            if srv is not None:
                from pico_chat.harness.llm_server import prewarm_local_resolution
                prewarm_local_resolution(srv._original_base_url)
                import asyncio
                async def _prewarm_and_refresh():
                    await srv.prewarm_model_name()
                    if hasattr(ui, "refresh_status_bar"):
                        ui.refresh_status_bar()
                asyncio.ensure_future(_prewarm_and_refresh())
            if hasattr(ui, "refresh_status_bar"):
                ui.refresh_status_bar()
            ui.chat_history_panel.add_message(
                f"Selected {model} on {server}.", msg_type=SysMsg(), title="model")
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
            # Bare `/model <model>` — treat the first arg as a model id.
            await self.subcommands["use"].execute(ui, args)
            return
        await subcommand.execute(ui, args[1:])


__all__ = ["ModelCommand", "ModelListCommand", "ModelUseCommand"]
