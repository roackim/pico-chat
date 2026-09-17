"""OpenRouter settings page builder.

Wires an OpenRouter server's model allowlist and per-model provider routing
to form fields. Shared by the settings tab so the surface stays behaviorally
identical to the rest of the settings pages.

The page lets the user:
- pick which OpenRouter server to configure
- add / remove enabled models (OpenRouter models are disabled by default)
- set per-model provider routing (whitelist = only these providers,
  blacklist = all except these)

Edits are persisted with the Save action. When the edited server is the one
the active conversation is using, the running server is rebuilt from the fresh
config so provider routing / enabled models take effect immediately instead of
waiting for a restart.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError


def _noop_notify(message: str, msg_type=SysMsg()):
    pass


def _refresh_active_server(server: str, runtime: Any, agent: Any) -> bool:
    """Rebuild the live server if the active conversation uses ``server``.

    Returns True when a running server was refreshed. Without this, editing
    provider routing or enabled models would only affect the next launch.
    """
    active_agent = getattr(runtime, "agent", None) if runtime is not None else agent
    if active_agent is None:
        return False
    live = getattr(active_agent, "server", None)
    live_name = getattr(getattr(live, "config", None), "name", None)
    if live is None or live_name != server:
        return False
    from pico_chat.harness.llm_server_config import get_server_config_by_name

    fresh = get_server_config_by_name(server)
    if fresh is None:
        return False
    active_agent.switch_server(fresh)
    return True


def build_openrouter_fields(
    notify: Callable[[str, object], None] = _noop_notify,
    runtime: Any = None,
    agent: Any = None,
) -> Tuple[list, Callable[[], None]]:
    """Build the OpenRouter settings fields plus their save callback.

    ``notify(message, msg_type)`` receives user-facing status messages; it
    defaults to no-op so the fields can be embedded outside a chat history
    (e.g. in the settings tab). ``runtime``/``agent`` let the save callback
    refresh the live server when it matches the edited one.
    """
    from pico_chat.harness.server_service import ServerService
    from pico_chat.ui.tui.components.form import (
        FormActionField, FormSectionTitle, InlineChoiceField, RadioListField, TextField,
    )

    service = ServerService()
    servers = service.openrouter_servers()

    def _notify(message: str, msg_type=SysMsg()):
        if notify is not None:
            notify(message, msg_type)

    # If no OpenRouter server is configured, show a hint field.
    if not servers:
        fields = [
            FormSectionTitle("OpenRouter"),
            TextField("No OpenRouter server configured", value="",
                      placeholder="Add one with /server add <name> openrouter <model>"),
        ]
        return fields, lambda: None

    server_options = servers
    server_field = RadioListField("Server", options=server_options, value=0)

    # Enabled models for the selected server.
    def _enabled(server: str) -> List[str]:
        cfg = service.get_openrouter_config(server) or {}
        return list(cfg.get("enabled_models", []) or [])

    enabled_field = TextField("Enabled models (comma-separated)",
                              value=", ".join(_enabled(server_options[0])))

    # Provider routing for the selected model.
    provider_mode_field = InlineChoiceField(
        "Provider mode", options=["default", "whitelist", "blacklist"], value=0)
    provider_field = TextField("Providers (comma-separated)", value="")

    def _selected_server() -> str:
        idx = server_field.get_value()
        return server_options[idx] if idx is not None else server_options[0]

    def _selected_model() -> str:
        # The model the provider routing applies to is the first enabled one
        # (or the server's default model). A richer per-model editor can be
        # added later; for now routing applies to the active model.
        enabled = _enabled(_selected_server())
        if enabled:
            return enabled[0]
        cfg = service.get_openrouter_config(_selected_server()) or {}
        return cfg.get("model", "")

    def _sync_provider_fields():
        model = _selected_model()
        entry = service.get_model_providers(_selected_server(), model)
        mode = entry.get("mode", "default")
        providers = ", ".join(entry.get("providers", []))
        provider_mode_field.set_value(["default", "whitelist", "blacklist"].index(mode))
        provider_field.set_value(providers)

    def _on_server_change(_value):
        enabled_field.set_value(", ".join(_enabled(_selected_server())))
        _sync_provider_fields()

    server_field._on_change = _on_server_change

    def save(*_args) -> None:
        """Persist enabled models and provider routing for the selected server."""
        server = _selected_server()
        try:
            # Enabled models.
            raw = enabled_field.get_value()
            models = [m.strip() for m in raw.split(",") if m.strip()]
            service.set_enabled_models(server, models)

            # Provider routing for the selected model.
            model = _selected_model()
            mode = ["default", "whitelist", "blacklist"][provider_mode_field.get_index()]
            providers = [p.strip() for p in provider_field.get_value().split(",") if p.strip()]
            if mode == "default" or not providers:
                service.set_model_providers(server, model, "whitelist", [])
            else:
                service.set_model_providers(server, model, mode, providers)

            refreshed = _refresh_active_server(server, runtime, agent)
            suffix = " Applied to the active conversation." if refreshed else ""
            _notify(f"OpenRouter settings saved for '{server}'.{suffix}", SysMsg())
        except (KeyError, OSError, ValueError, TypeError) as exc:
            _notify(str(exc), SysMsgError())

    fields = [
        FormSectionTitle("OpenRouter"),
        server_field,
        enabled_field,
        FormSectionTitle("Provider routing (per model)"),
        provider_mode_field,
        provider_field,
        FormActionField("Save OpenRouter settings", on_activate=lambda: save()),
    ]

    _sync_provider_fields()

    return fields, save


__all__ = ["build_openrouter_fields"]
