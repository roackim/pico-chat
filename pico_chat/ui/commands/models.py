"""Model discovery and selection commands.

The unit of selection is a ``(server, model)`` pair. Discovery is live: the
cached catalog in ``state.toml`` is only a convenience for completion and
offline fallback, never the source of truth.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError

from .base import ChatUIProtocol, Command, Param


def _known_model_ids() -> List[str]:
    """Model ids for fuzzy completion, from the cache and server defaults."""
    ids = set()
    for models in pico_cfg.config.models_by_server.values():
        ids.update(m.get("id") for m in models if m.get("id"))
    for cfg in pico_cfg.config.servers.values():
        if cfg.get("model"):
            ids.add(cfg["model"])
    return sorted(ids)


async def _discover_all() -> List[Tuple[str, "ModelInfo"]]:
    """Discover models live from every configured endpoint.

    Offline servers fall back to their cached catalog. Returns ``(server,
    model)`` pairs and refreshes the cache.
    """
    from pico_chat.harness.endpoint import ModelInfo, get_endpoint

    pairs: List[Tuple[str, ModelInfo]] = []
    for name in list(pico_cfg.config.servers):
        endpoint = get_endpoint(name)
        if endpoint is None:
            continue
        try:
            models = await endpoint.discover_models()
        except Exception:
            models = [ModelInfo.from_dict(m) for m in pico_cfg.config.models_by_server.get(name, [])]
        pico_cfg.config.models_by_server[name] = [m.to_dict() for m in models]
        pairs.extend((name, model) for model in models)
    pico_cfg.config.save_model_catalog()
    return pairs


def _split_server_model(raw: str) -> Tuple[Optional[str], str]:
    """Split ``<server>:<model>`` using known server names.

    Model ids may contain colons (e.g. Ollama tags), so only split on the first
    occurrence of a known server name followed by ``:``.
    """
    for server_name in sorted(pico_cfg.config.servers, key=len, reverse=True):
        prefix = f"{server_name}:"
        if raw.startswith(prefix) and len(raw) > len(prefix):
            return server_name, raw[len(prefix):]
    return None, raw


def _activate(ui: ChatUIProtocol, server: str, model: str) -> None:
    """Persist the selection, switch the endpoint, and prewarm the status bar."""
    from pico_chat.harness.endpoint import get_endpoint, prewarm_local_resolution

    pico_cfg.config.save_model_selection(server, model)
    pico_cfg.config.set_active_server(server)
    endpoint = get_endpoint(server)
    if endpoint is None:
        return
    ui.agent.switch_server(endpoint)
    ui.agent.switch_model(model)
    prewarm_local_resolution(endpoint._original_base_url)

    import asyncio

    async def _prewarm():
        await endpoint.prewarm_model_name()
        if hasattr(ui, "refresh_status_bar"):
            ui.refresh_status_bar()

    asyncio.ensure_future(_prewarm())
    if hasattr(ui, "refresh_status_bar"):
        ui.refresh_status_bar()


class ModelListCommand(Command):
    def __init__(self):
        super().__init__("list", "List models across all servers")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        pairs = await _discover_all()
        if not pairs:
            ui.chat_history_panel.add_message(
                "No models discovered.\n\n"
                "Configure a server with '/config', then check it is reachable "
                "with '/server diagnose <name>'.",
                msg_type=SysMsg(), title="model")
            return

        active_endpoint = getattr(ui.agent, "endpoint", None)
        active_name = getattr(active_endpoint, "name", None)
        selected = getattr(active_endpoint, "selected_model", None)

        lines = [f"{str(theme.DEFAULT)}Models:{theme.reset()}"]
        for server, model in sorted(pairs, key=lambda p: (p[0], p[1].id)):
            marker = "*" if (server == active_name and model.id == selected) else " "
            context = f" ({model.context_window:,} tokens)" if model.context_window else ""
            lines.append(
                f"{marker} {model.id}{context} {str(theme.MUTED)}[{server}]{theme.reset()}")
        ui.chat_history_panel.add_message("\n".join(lines), msg_type=SysMsg(), title="model")


class ModelUseCommand(Command):
    def __init__(self):
        super().__init__("use", "Select a model, switching to the server that serves it",
                         params=[Param("MODEL", completions=_known_model_ids, required=True)])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message("Usage: /model <model>", msg_type=SysMsgError())
            return

        from pico_chat.harness.endpoint import get_endpoint

        raw = " ".join(args).strip()
        server_hint, model = _split_server_model(raw)

        if server_hint is not None:
            if server_hint not in pico_cfg.config.servers:
                ui.chat_history_panel.add_message(
                    f"Server '{server_hint}' not found.\n\n"
                    "Use '/server list' to see configured servers.",
                    msg_type=SysMsgError(), title="model")
                return
            servers = [server_hint]
        else:
            pairs = await _discover_all()
            servers = [server for server, info in pairs if info.id == model]

        if not servers:
            ui.chat_history_panel.add_message(
                f"Model '{model}' not found on any configured server.\n\n"
                "Run '/model list' to see discovered models.",
                msg_type=SysMsgError(), title="model")
            return

        if len(servers) > 1:
            active_name = getattr(getattr(ui.agent, "endpoint", None), "name", None)
            if active_name in servers:
                server = active_name
            else:
                ui.chat_history_panel.add_message(
                    f"Model '{model}' is served by multiple servers:\n"
                    + "\n".join(f"  - {s}" for s in servers)
                    + "\n\nUse '/model <server>:<model>' to disambiguate.",
                    msg_type=SysMsgError(), title="model")
                return
        else:
            server = servers[0]

        try:
            _activate(ui, server, model)
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
