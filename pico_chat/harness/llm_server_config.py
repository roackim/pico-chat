"""
LLM Server configuration system.

Provides configuration for different LLM server types (llamacpp, openrouter, etc.)
with support for model selection, context windows, and server-specific settings.

Server configs are loaded from pico_cfg (which loads from ~/.config/pico-chat/config.toml)
"""
from dataclasses import dataclass, field
from typing import Any, Literal
import os


ServerType = Literal["llamacpp", "ollama", "openrouter", "openai"]


@dataclass(frozen=True)
class ModelInfo:
    """Metadata for one model exposed by an endpoint."""

    id: str
    context_window: int | None = None
    owned_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Convenience accessors for the most useful Ollama metadata fields.
    @property
    def size(self) -> int | None:
        """Model size in bytes (Ollama ``size`` field), if known."""
        return self.metadata.get("size")

    @property
    def family(self) -> str | None:
        """Model family (Ollama ``family`` field), if known."""
        return self.metadata.get("family")

    @property
    def modified_at(self) -> str | None:
        """Last-modified timestamp (Ollama ``modified_at``), if known."""
        return self.metadata.get("modified_at")

    def to_dict(self) -> dict[str, Any]:
        """Serializable form for the discovery catalog."""
        return {
            "id": self.id,
            "context_window": self.context_window,
            "owned_by": self.owned_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelInfo":
        """Rebuild a ModelInfo from :meth:`to_dict` output."""
        return cls(
            id=data.get("id", ""),
            context_window=data.get("context_window"),
            owned_by=data.get("owned_by"),
            metadata=data.get("metadata") or {},
        )


@dataclass(frozen=True)
class ModelRef:
    """A model addressable by ``(server, model)`` pair.

    This is the unit of selection: picking a model implicitly selects the
    server that serves it.
    """

    server: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.server}::{self.model}"

    def __str__(self) -> str:
        return f"{self.model} [{self.server}]"


@dataclass(frozen=True)
class LLMTarget:
    """The selected model at an endpoint."""

    endpoint: str
    model: str


@dataclass
class LLMServerConfig:
    """Connection configuration for an LLM endpoint.

    ``model`` is a legacy/default selection. Runtime model selection is
    owned by the server instance so one endpoint can serve many models.
    """
    name: str
    type: ServerType
    base_url: str
    api_key: str
    model: str | None  # None means query from server (or select interactively for OpenRouter)
    max_context: int | None  # None means query from server/model
    
    # Server-specific settings
    timeout: float = 30.0  # Timeout for server queries in seconds
    retry_attempts: int = 3  # Retry attempts for transient errors
    retry_delay: float = 2.0  # Initial retry delay in seconds
    provider: str | None = None  # OpenRouter: routing preference (e.g., "Anthropic", "DeepInfra")
    # OpenRouter: the set of explicitly-enabled model ids. All others are
    # hidden from /model (disabled by default). Falls back to ``model``.
    enabled_models: list[str] = field(default_factory=list)
    # OpenRouter: per-model provider routing. Maps a model id to a
    # ``{mode, providers}`` dict where mode is "whitelist" (only these
    # providers) or "blacklist" (all except these). A model with no entry
    # uses OpenRouter's default routing.
    model_providers: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def target(self) -> LLMTarget | None:
        """Return the selected endpoint/model pair when a model is known."""
        return LLMTarget(self.name, self.model) if self.model else None


# Default fallback server (used if no config file exists)
_DEFAULT_SERVER = LLMServerConfig(
    name="llamacpp_default",
    type="llamacpp",
    base_url="http://localhost:8080/v1",
    api_key="EMPTY",
    model=None,
    max_context=None,
    timeout=2.0,
    retry_attempts=5,
    retry_delay=2.0,
)


def _parse_server_dict(name: str, server_dict: dict) -> LLMServerConfig:
    """Parse a server config dict into an LLMServerConfig."""
    server_type = server_dict.get("type", "llamacpp")
    api_key = server_dict.get("api_key", "")
    api_key_env = server_dict.get("api_key_env")
    if api_key_env:
        api_key = os.getenv(api_key_env, api_key)
    return LLMServerConfig(
        name=name,
        type=server_type,
        base_url=server_dict.get("base_url", "http://localhost:8080/v1"),
        api_key=api_key,
        model=server_dict.get("model"),
        max_context=server_dict.get("max_context"),
        timeout=server_dict.get("timeout", 30.0),
        retry_attempts=server_dict.get("retry_attempts", 3),
        retry_delay=server_dict.get("retry_delay", 2.0),
        provider=server_dict.get("provider"),
        enabled_models=server_dict.get("enabled_models", []),
        model_providers=server_dict.get("model_providers", {}),
    )


def get_server_config() -> LLMServerConfig:
    """
    Get the active server configuration.
    
    Loads from pico_cfg if available, otherwise returns default llamacpp server.
    Environment variables override config file values for API keys.
    """
    from pico_chat import pico_cfg

    server_dict = pico_cfg.config.get_active_server_config()
    if server_dict is None:
        return _DEFAULT_SERVER
    config = _parse_server_dict(pico_cfg.config.active_server, server_dict)
    # Prefer the per-server model selection, then the legacy active_model,
    # then the per-server ``model`` default.
    selected = pico_cfg.config.get_model_for_server(pico_cfg.config.active_server)
    if selected is None and pico_cfg.config.active_model is not None:
        selected = pico_cfg.config.active_model
    if selected is not None:
        config.model = selected
    return config


def get_server_config_by_name(name: str) -> LLMServerConfig | None:
    """
    Get a server configuration by name.

    Applies the per-server model selection so the returned config describes
    the endpoint *and the model that was last selected on it*. Returns None if
    the named server is not found in config.
    """
    from pico_chat import pico_cfg

    server_dict = pico_cfg.config.servers.get(name)
    if server_dict is None:
        return None
    config = _parse_server_dict(name, server_dict)
    selected = pico_cfg.config.get_model_for_server(name)
    if selected is not None:
        config.model = selected
    return config


# Global server configuration - call get_server_config() to get current config
server_config: LLMServerConfig = get_server_config()
