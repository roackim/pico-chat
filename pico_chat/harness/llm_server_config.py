"""
LLM Server configuration system.

Provides configuration for different LLM server types (llamacpp, openrouter, etc.)
with support for model selection, context windows, and server-specific settings.

Server configs are loaded from pico_cfg (which loads from ~/.config/pico-chat/config.toml)
"""
from dataclasses import dataclass
from typing import Literal
import os


ServerType = Literal["llamacpp", "openrouter", "openai"]


@dataclass
class LLMServerConfig:
    """Configuration for an LLM server."""
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


def get_server_config() -> LLMServerConfig:
    """
    Get the active server configuration.
    
    Loads from pico_cfg if available, otherwise returns default llamacpp server.
    Environment variables override config file values for API keys.
    """
    from pico_chat import pico_cfg
    
    server_dict = pico_cfg.config.get_active_server_config()
    
    if server_dict is None:
        # No config found, return default
        return _DEFAULT_SERVER
    
    # Parse server dict into LLMServerConfig
    server_type = server_dict.get("type", "llamacpp")
    
    # Get API key from environment variable if specified
    api_key = server_dict.get("api_key", "")
    api_key_env = server_dict.get("api_key_env")
    if api_key_env:
        api_key = os.getenv(api_key_env, api_key)
    
    return LLMServerConfig(
        name=pico_cfg.config.active_server,
        type=server_type,
        base_url=server_dict.get("base_url", "http://localhost:8080/v1"),
        api_key=api_key,
        model=server_dict.get("model"),
        max_context=server_dict.get("max_context"),
        timeout=server_dict.get("timeout", 30.0),
        retry_attempts=server_dict.get("retry_attempts", 3),
        retry_delay=server_dict.get("retry_delay", 2.0),
        provider=server_dict.get("provider"),
    )


# Global server configuration - call get_server_config() to get current config
server_config: LLMServerConfig = get_server_config()
