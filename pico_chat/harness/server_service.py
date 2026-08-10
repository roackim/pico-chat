"""
Server management service.

Encapsulates server configuration operations (add, list, use, remove, info)
and OpenRouter API interactions, keeping business logic out of UI command
classes.  The UI layer calls these methods and handles message rendering.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pico_chat.harness.llm_server_config import (
    LLMServerConfig,
    get_server_config_by_name,
)

logger = logging.getLogger("tui")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ServerAddResult:
    """Result of adding a server."""
    ok: bool
    message: str
    server_name: Optional[str] = None
    server_type: Optional[str] = None
    model: Optional[str] = None
    url: Optional[str] = None
    context_window: Optional[int] = None


@dataclass
class ServerSwitchResult:
    """Result of switching to a server."""
    ok: bool
    message: str
    new_config: Optional[LLMServerConfig] = None


@dataclass
class ServerRemoveResult:
    """Result of removing a server."""
    ok: bool
    message: str
    switched_to: Optional[str] = None
    new_config: Optional[LLMServerConfig] = None  # if active server was removed and switched


@dataclass
class ServerInfo:
    """Detailed info about a configured server."""
    name: str
    server_type: str
    is_active: bool
    model: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout: float = 30.0
    retry_attempts: int = 3
    retry_delay: float = 2.0
    max_context: Optional[int] = None


@dataclass
class OpenRouterBalance:
    """OpenRouter account balance."""
    total_credits: float
    total_usage: float
    remaining: float


# ---------------------------------------------------------------------------
# ServerService
# ---------------------------------------------------------------------------

class ServerService:
    """Manages LLM server configurations.

    All methods are async (they may perform network requests for validation).
    Methods return structured result objects — the caller handles UI rendering.
    """

    # --- Add ---

    async def add_openrouter(
        self,
        server_name: str,
        model_id: str,
        provider: Optional[str] = None,
    ) -> ServerAddResult:
        """Add an OpenRouter server configuration.

        Validates the model ID against OpenRouter's catalog, tests the
        connection, and saves the config (without activating it).
        """
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return ServerAddResult(
                ok=False,
                message=(
                    "OpenRouter API key not found.\n"
                    "Set environment variable: export OPENROUTER_API_KEY=sk-or-...\n"
                    "Get your key at: https://openrouter.ai/keys"
                ),
            )

        # Validate model against OpenRouter catalog
        validation_error = await self._validate_openrouter_model(model_id, provider)
        if validation_error:
            return ServerAddResult(ok=False, message=validation_error)

        # Test connection
        test_config = LLMServerConfig(
            name=server_name,
            type="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            model=model_id,
            max_context=None,
            timeout=5.0,
            retry_attempts=1,
            retry_delay=1.0,
            provider=provider,
        )

        from pico_chat.harness.llm_server import create_server
        test_server = create_server(test_config)
        online = await test_server.check_connection()

        if not online:
            return ServerAddResult(
                ok=False,
                message=(
                    "Failed to connect to OpenRouter\n"
                    "Check your API key and internet connection.\n"
                    "Get your key at: https://openrouter.ai/keys"
                ),
            )

        # Save config
        server_config: Dict[str, Any] = {
            "type": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "model": model_id,
            "timeout": 30.0,
            "retry_attempts": 3,
            "retry_delay": 2.0,
        }
        if provider:
            server_config["provider"] = provider

        from pico_chat import pico_cfg
        pico_cfg.config.save_server(server_name, server_config, set_active=False)

        provider_msg = f"\nProvider: {provider}" if provider else ""
        return ServerAddResult(
            ok=True,
            message=(
                f"Added server '{server_name}'\n"
                f"Type: OpenRouter\n"
                f"Model: {model_id}{provider_msg}\n\n"
                f"Use '/server use {server_name}' to activate"
            ),
            server_name=server_name,
            server_type="openrouter",
            model=model_id,
        )

    async def add_llamacpp(
        self,
        server_name: str,
        url: str,
    ) -> ServerAddResult:
        """Add a llama.cpp server configuration.

        Normalises the URL, tests the connection, queries model info,
        and saves the config (without activating it).
        """
        # Normalize URL
        if not url.startswith("http"):
            url = f"http://{url}"
        if not url.endswith("/v1"):
            url = f"{url}/v1"

        test_config = LLMServerConfig(
            name=server_name,
            type="llamacpp",
            base_url=url,
            api_key="EMPTY",
            model=None,
            max_context=None,
            timeout=2.0,
            retry_attempts=3,
            retry_delay=1.0,
        )

        from pico_chat.harness.llm_server import create_server
        test_server = create_server(test_config)
        online = await test_server.check_connection()

        if not online:
            return ServerAddResult(
                ok=False,
                message=(
                    f"Failed to connect to {url}\n"
                    "Server is not responding. Check the URL and ensure the server is running."
                ),
            )

        model_name = await test_server.get_model_name()
        context_window = await test_server.get_context_window()

        server_config: Dict[str, Any] = {
            "type": "llamacpp",
            "base_url": url,
            "api_key": "EMPTY",
            "timeout": 30.0,
            "retry_attempts": 3,
            "retry_delay": 2.0,
        }

        from pico_chat import pico_cfg
        pico_cfg.config.save_server(server_name, server_config, set_active=False)

        return ServerAddResult(
            ok=True,
            message=(
                f"Added server '{server_name}'\n"
                f"Type: llamacpp\n"
                f"URL: {url}\n"
                f"Model: {model_name}\n"
                f"Context: {context_window:,} tokens\n\n"
                f"Use '/server use {server_name}' to activate"
            ),
            server_name=server_name,
            server_type="llamacpp",
            url=url,
            context_window=context_window,
        )

    async def add_ollama(
        self,
        server_name: str,
        url: str,
        model: Optional[str] = None,
    ) -> ServerAddResult:
        """Add an Ollama endpoint, optionally with a default model."""
        if not url.startswith("http"):
            url = f"http://{url}"
        base_url = url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        test_config = LLMServerConfig(
            name=server_name,
            type="ollama",
            base_url=f"{base_url}/v1",
            api_key="ollama",
            model=model or None,
            max_context=None,
            timeout=5.0,
            retry_attempts=1,
            retry_delay=1.0,
        )

        from pico_chat.harness.llm_server import create_server
        test_server = create_server(test_config)
        if not await test_server.check_connection():
            return ServerAddResult(
                ok=False,
                message=(
                    f"Failed to connect to Ollama at {base_url}\n"
                    "Ensure Ollama is running and the URL is correct."
                ),
            )

        models = await test_server.list_models()
        selected = model or (models[0].id if models else None)
        server_config: Dict[str, Any] = {
            "type": "ollama",
            "base_url": f"{base_url}/v1",
            "api_key": "ollama",
            "timeout": 30.0,
            "retry_attempts": 3,
            "retry_delay": 2.0,
        }
        if selected:
            server_config["model"] = selected

        from pico_chat import pico_cfg
        pico_cfg.config.save_server(server_name, server_config, set_active=False)
        model_text = selected or "none discovered"
        return ServerAddResult(
            ok=True,
            message=(
                f"Added server '{server_name}'\n"
                "Type: Ollama\n"
                f"URL: {base_url}\n"
                f"Model: {model_text}\n\n"
                f"Use '/server use {server_name}' to activate"
            ),
            server_name=server_name,
            server_type="ollama",
            model=selected,
            url=f"{base_url}/v1",
        )

    async def list_models(self, endpoint_name: Optional[str] = None):
        """Discover models from an endpoint without changing active state."""
        from pico_chat import pico_cfg
        from pico_chat.harness.llm_server import create_server
        from pico_chat.harness.llm_server_config import get_server_config, get_server_config_by_name

        config = get_server_config_by_name(endpoint_name) if endpoint_name else get_server_config()
        if config is None:
            raise ValueError(f"Endpoint '{endpoint_name}' not found")
        return await create_server(config).list_models()

    def select_model(self, model: str) -> None:
        """Persist an active model independently of the endpoint definition."""
        from pico_chat import pico_cfg
        pico_cfg.config.save_active_model(model)

    # --- List / Info ---

    def list_servers(self) -> List[Tuple[str, str, bool]]:
        """Return a list of (name, type, is_active) for all configured servers."""
        from pico_chat import pico_cfg
        active = pico_cfg.config.active_server
        return [
            (name, cfg.get("type", "unknown"), name == active)
            for name, cfg in sorted(pico_cfg.config.servers.items())
        ]

    def get_server_info(self, name: str) -> Optional[ServerInfo]:
        """Get detailed info about a specific server, or None if not found."""
        from pico_chat import pico_cfg
        servers = pico_cfg.config.servers
        if name not in servers:
            return None
        cfg = servers[name]
        return ServerInfo(
            name=name,
            server_type=cfg.get("type", "unknown"),
            is_active=(pico_cfg.config.active_server == name),
            model=cfg.get("model"),
            provider=cfg.get("provider"),
            base_url=cfg.get("base_url"),
            api_key_env=cfg.get("api_key_env"),
            timeout=cfg.get("timeout", 30.0),
            retry_attempts=cfg.get("retry_attempts", 3),
            retry_delay=cfg.get("retry_delay", 2.0),
            max_context=cfg.get("max_context"),
        )

    # --- Use / Switch ---

    def switch_server(self, server_name: str) -> ServerSwitchResult:
        """Switch the active server by name.

        Updates the TOML config file and returns the new LLMServerConfig
        for the caller to pass to the running harness.
        """
        from pico_chat import pico_cfg

        if server_name not in pico_cfg.config.servers:
            return ServerSwitchResult(
                ok=False,
                message=f"Server '{server_name}' not found.\n\nUse '/server list' to see available servers",
            )

        # Update active server in TOML
        self._set_active_server_in_toml(server_name)
        pico_cfg.config.active_server = server_name
        pico_cfg.config.active_model = pico_cfg.config.servers[server_name].get("model")
        pico_cfg.config.save_active_model(pico_cfg.config.active_model)

        new_config = get_server_config_by_name(server_name)
        if new_config is None:
            return ServerSwitchResult(ok=False, message=f"Failed to parse config for '{server_name}'")

        server_dict = pico_cfg.config.servers[server_name]
        server_type = server_dict.get("type", "unknown")
        msg = self._format_switch_message(server_name, server_type, server_dict)

        return ServerSwitchResult(ok=True, message=msg, new_config=new_config)

    # --- Remove ---

    def remove_server(self, server_name: str) -> ServerRemoveResult:
        """Remove a server configuration.

        If the removed server was active, switches to the first remaining
        server (and returns its config for the caller to apply).
        """
        from pico_chat import pico_cfg

        if server_name not in pico_cfg.config.servers:
            return ServerRemoveResult(
                ok=False,
                message=f"Server '{server_name}' not found.\n\nUse '/server list' to see available servers",
            )

        import toml
        config_path = pico_cfg.get_config_path()

        if not config_path.exists():
            return ServerRemoveResult(ok=False, message="Config file not found")

        data = toml.load(config_path)
        if "servers" not in data or server_name not in data["servers"]:
            return ServerRemoveResult(
                ok=False,
                message=f"Server '{server_name}' not found in config file",
            )

        is_active = (pico_cfg.config.active_server == server_name)
        del data["servers"][server_name]

        switched_to = None
        new_config = None

        if is_active:
            remaining = list(data["servers"].keys())
            if remaining:
                new_active = remaining[0]
                if "settings" not in data:
                    data["settings"] = {}
                data["settings"]["active_server"] = new_active
                pico_cfg.config.active_server = new_active
                switched_to = new_active
                new_config = get_server_config_by_name(new_active)
            else:
                if "settings" in data and "active_server" in data["settings"]:
                    del data["settings"]["active_server"]
                pico_cfg.config.active_server = "llamacpp_default"

        with open(config_path, "w") as f:
            toml.dump(data, f)

        del pico_cfg.config.servers[server_name]

        msg = f"Removed server '{server_name}'"
        if switched_to:
            msg += f"\nSwitched to '{switched_to}'"
        elif is_active:
            msg += "\nNo servers configured"

        return ServerRemoveResult(ok=True, message=msg, switched_to=switched_to, new_config=new_config)

    # --- OpenRouter balance ---

    async def get_openrouter_balance(self) -> Tuple[bool, str, Optional[OpenRouterBalance]]:
        """Fetch OpenRouter account balance.

        Returns (ok, message, balance).  balance is None on error.
        """
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return False, (
                "OpenRouter API key not found.\n"
                "Set environment variable: export OPENROUTER_API_KEY=sk-or-..."
            ), None

        import httpx
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/credits",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )

            if response.status_code != 200:
                return False, f"OpenRouter API error: HTTP {response.status_code}", None

            data = response.json().get("data", {})
            total_credits = data.get("total_credits", 0.0)
            total_usage = data.get("total_usage", 0.0)
            remaining = total_credits - total_usage

            return True, "", OpenRouterBalance(
                total_credits=total_credits,
                total_usage=total_usage,
                remaining=remaining,
            )
        except Exception as e:
            return False, f"Failed to fetch balance: {e}", None

    # --- Private helpers ---

    async def _validate_openrouter_model(
        self,
        model_id: str,
        provider: Optional[str] = None,
    ) -> Optional[str]:
        """Validate model ID and provider against OpenRouter catalog.

        Returns an error message string if validation fails, None if OK
        (or if the catalog can't be fetched — we don't block on network errors).
        """
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    timeout=5.0,
                )
                if response.status_code != 200:
                    logger.warning(f"Could not fetch OpenRouter models list: HTTP {response.status_code}")
                    return None

                models = response.json().get("data", [])
                model_info = None
                for model in models:
                    if model.get("id") == model_id:
                        model_info = model
                        break

                if not model_info:
                    return (
                        f"Model '{model_id}' not found in OpenRouter catalog.\n\n"
                        "Browse available models at: https://openrouter.ai/models\n"
                        "Model IDs should be in format: provider/model-name\n"
                        "(e.g., anthropic/claude-3.5-sonnet, openai/gpt-4)"
                    )

                if provider:
                    supported = model_info.get("supported_providers", [])
                    if supported:
                        provider_ids = [p.get("id") if isinstance(p, dict) else p for p in supported]
                        if provider.lower() not in [p.lower() for p in provider_ids if p]:
                            return (
                                f"Provider '{provider}' is not supported for model '{model_id}'.\n\n"
                                f"Supported providers: {', '.join(provider_ids)}\n\n"
                                "Leave provider empty to use OpenRouter's default routing."
                            )
        except Exception as e:
            logger.warning(f"Failed to validate OpenRouter model: {e}")

        return None

    def _set_active_server_in_toml(self, server_name: str):
        """Update the active_server setting in the TOML config file."""
        import toml
        from pico_chat import pico_cfg

        config_path = pico_cfg.get_config_path()
        if config_path.exists():
            data = toml.load(config_path)
        else:
            data = {}

        if "settings" not in data:
            data["settings"] = {}
        data["settings"]["active_server"] = server_name

        with open(config_path, "w") as f:
            toml.dump(data, f)

    @staticmethod
    def _format_switch_message(
        server_name: str,
        server_type: str,
        server_dict: Dict[str, Any],
    ) -> str:
        """Build a one-line switch confirmation message."""
        if server_type == "openrouter":
            model = server_dict.get("model", "unknown")
            provider = server_dict.get("provider")
            if provider:
                return f"Switched to {server_name} (openrouter) - {model} via {provider}"
            return f"Switched to {server_name} (openrouter) - {model}"
        elif server_type == "llamacpp":
            url = server_dict.get("base_url", "unknown")
            return f"Switched to {server_name} (llamacpp) - {url}"
        else:
            return f"Switched to {server_name} ({server_type})"
