"""
LLM Server configuration system.

Provides configuration for different LLM server types (llamacpp, openrouter, etc.)
with support for model selection, context windows, and server-specific settings.
"""
from dataclasses import dataclass
from typing import Literal


ServerType = Literal["llamacpp", "openrouter", "openai"]


@dataclass
class LLMServerConfig:
    """Configuration for an LLM server."""
    name: str
    type: ServerType
    base_url: str
    api_key: str
    model: str | None  # None means query from server
    max_context: int | None  # None means query from server/model
    
    # Server-specific settings
    timeout: float = 2.0  # Timeout for server queries in seconds
    retry_attempts: int = 5  # Retry attempts for transient errors
    retry_delay: float = 2.0  # Initial retry delay in seconds


# --- Predefined Server Configurations ---

# llamacpp_local = LLMServerConfig(
#     name="llamacpp_local",
#     type="llamacpp",
#     base_url="http://localhost:8080/v1",
#     api_key="EMPTY",
#     model=None,  # Will be queried from server
#     max_context=None,  # Will be queried from server
#     timeout=2.0,
#     retry_attempts=5,
#     retry_delay=2.0,
# )

llamacpp = LLMServerConfig(
    name="llamacpp",
    type="llamacpp",
    base_url="http://clank:3344/v1",
    # base_url="http://gpu4.hygeos.com:8080/v1",
    api_key="EMPTY",
    model=None,         # Will be queried from server
    max_context=None,   # Will be queried from server
    timeout=2.0,
    retry_attempts=5,
    retry_delay=2.0,
)

# openrouter_default = LLMServerConfig(
#     name="openrouter",
#     type="openrouter",
#     base_url="https://openrouter.ai/api/v1",
#     api_key="",  # User must provide API key
#     model="anthropic/claude-3.5-sonnet",
#     max_context=200000,
#     timeout=5.0,
#     retry_attempts=3,
#     retry_delay=1.0,
# )

# openai_default = LLMServerConfig(
#     name="openai",
#     type="openai",
#     base_url="https://api.openai.com/v1",
#     api_key="",  # User must provide API key
#     model="gpt-4o",
#     max_context=128000,
#     timeout=5.0,
#     retry_attempts=3,
#     retry_delay=1.0,
# )

# Global server configuration (can be changed at runtime)
server_config: LLMServerConfig = llamacpp
