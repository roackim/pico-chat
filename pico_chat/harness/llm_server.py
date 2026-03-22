"""
LLM Server abstraction layer.

Provides a unified interface for interacting with different LLM servers
(llamacpp, openrouter, openai, etc.) with automatic model and context detection.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, AsyncGenerator, Dict, Any

from openai import AsyncOpenAI, InternalServerError, APIError

from pico_chat.harness.llm_server_config import LLMServerConfig, ServerType


logger = logging.getLogger(__name__)


class LLMServer(ABC):
    """Abstract base class for LLM server implementations."""
    
    def __init__(self, config: LLMServerConfig):
        """Initialize the server with configuration."""
        self.config = config
        self.client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )
        
        # Cached server information
        self._cached_model_name: Optional[str] = None
        self._cached_context_window: Optional[int] = None
    
    @abstractmethod
    async def query_model_name(self) -> str:
        """Query the server for the active model name."""
        pass
    
    @abstractmethod
    async def query_context_window(self, model_name: str) -> int:
        """Query the server for the model's context window size."""
        pass
    
    async def get_model_name(self) -> str:
        """
        Get the model name (cached or queried).
        
        Returns:
            Model name string
        """
        if self._cached_model_name:
            return self._cached_model_name
        
        # Try to query from server
        try:
            self._cached_model_name = await self.query_model_name()
            logger.info(f"Queried model name: {self._cached_model_name}")
            return self._cached_model_name
        except Exception as e:
            logger.warning(f"Failed to query model name: {e}")
        
        # Fallback to config
        if self.config.model:
            self._cached_model_name = self.config.model
            logger.info(f"Using model from config: {self._cached_model_name}")
            return self._cached_model_name
        
        # Last resort
        self._cached_model_name = "unknown"
        logger.warning("Model name unknown, using 'unknown'")
        return self._cached_model_name
    
    async def get_context_window(self) -> int:
        """
        Get the context window size (cached or queried).
        
        Returns:
            Context window size in tokens
        """
        if self._cached_context_window:
            return self._cached_context_window
        
        # Try to query from server
        try:
            model_name = await self.get_model_name()
            self._cached_context_window = await self.query_context_window(model_name)
            logger.info(f"Queried context window: {self._cached_context_window}")
            return self._cached_context_window
        except Exception as e:
            logger.warning(f"Failed to query context window: {e}")
        
        # Fallback to config
        if self.config.max_context:
            self._cached_context_window = self.config.max_context
            logger.info(f"Using context window from config: {self._cached_context_window}")
            return self._cached_context_window
        
        # Default fallback
        self._cached_context_window = 32768
        logger.warning(f"Context window unknown, using default: {self._cached_context_window}")
        return self._cached_context_window
    
    async def check_connection(self) -> bool:
        """
        Check if the server is reachable.
        
        Returns:
            True if server is online, False otherwise
        """
        try:
            await asyncio.wait_for(self.client.models.list(), timeout=self.config.timeout)
            return True
        except Exception:
            return False
    
    async def create_completion(
        self,
        messages: list[Dict[str, Any]],
        tools: Optional[list[Dict[str, Any]]] = None,
        stream: bool = True,
    ) -> AsyncGenerator[Any, None]:
        """
        Create a chat completion with automatic retry for transient errors.
        
        Args:
            messages: List of message dictionaries
            tools: Optional list of tool schemas
            stream: Whether to stream the response
            
        Yields:
            Completion chunks if streaming, otherwise yields final response
        """
        model_name = await self.get_model_name()
        
        # Retry logic for transient errors (e.g., 503 "Loading model")
        max_retries = self.config.retry_attempts
        retry_delay = self.config.retry_delay
        
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    tools=tools,
                    stream=stream
                )
                
                # If streaming, yield chunks
                if stream:
                    async for chunk in response:
                        yield chunk
                else:
                    yield response
                
                return  # Success, exit
                
            except InternalServerError as e:
                # Check if it's a "Loading model" error (503)
                error_message = str(e)
                if e.status_code == 503 and ("Loading model" in error_message or "unavailable" in error_message.lower()):
                    if attempt < max_retries - 1:
                        logger.warning(f"Model loading (503), retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 1.5  # Exponential backoff
                        continue
                    else:
                        logger.error(f"Model loading timeout after {max_retries} attempts")
                        raise
                else:
                    # Other 5xx errors - re-raise immediately
                    raise
                    
            except APIError:
                # Other API errors - re-raise immediately
                raise


class LlamaCppServer(LLMServer):
    """Implementation for llama.cpp server."""
    
    async def query_model_name(self) -> str:
        """Query model name from llama.cpp server."""
        models = await asyncio.wait_for(
            self.client.models.list(),
            timeout=self.config.timeout
        )
        if models and models.data:
            return models.data[0].id
        raise RuntimeError("No models available on server")
    
    async def query_context_window(self, model_name: str) -> int:
        """
        Query context window from llama.cpp server.
        
        llama.cpp provides this via /props endpoint or in model metadata.
        For now, we'll try to get it from the models endpoint.
        """
        try:
            # Try to get from /props endpoint (llama.cpp specific)
            import httpx
            async with httpx.AsyncClient() as client:
                url = self.config.base_url.replace("/v1", "/props")
                response = await client.get(url, timeout=self.config.timeout)
                if response.status_code == 200:
                    data = response.json()
                    # llama.cpp returns context length in different fields
                    ctx = data.get("default_generation_settings", {}).get("n_ctx")
                    if ctx:
                        return ctx
        except Exception as e:
            logger.debug(f"Failed to query /props endpoint: {e}")
        
        # Fallback: models endpoint might have it
        models = await asyncio.wait_for(
            self.client.models.list(),
            timeout=self.config.timeout
        )
        if models and models.data:
            model = models.data[0]
            # Check if context_length is available in model metadata
            ctx = getattr(model, 'context_length', None)
            if ctx:
                return ctx
        
        raise RuntimeError("Could not determine context window from server")


class OpenRouterServer(LLMServer):
    """Implementation for OpenRouter."""
    
    async def query_model_name(self) -> str:
        """OpenRouter uses configured model name."""
        if self.config.model:
            return self.config.model
        raise RuntimeError("OpenRouter requires model to be configured")
    
    async def query_context_window(self, model_name: str) -> int:
        """
        Query context window from OpenRouter API.
        
        OpenRouter provides model info via their models endpoint.
        """
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    timeout=self.config.timeout
                )
                if response.status_code == 200:
                    data = response.json()
                    for model in data.get("data", []):
                        if model.get("id") == model_name:
                            ctx = model.get("context_length")
                            if ctx:
                                return ctx
        except Exception as e:
            logger.debug(f"Failed to query OpenRouter models: {e}")
        
        raise RuntimeError("Could not determine context window from OpenRouter")


class OpenAIServer(LLMServer):
    """Implementation for OpenAI API."""
    
    async def query_model_name(self) -> str:
        """OpenAI uses configured model name."""
        if self.config.model:
            return self.config.model
        raise RuntimeError("OpenAI requires model to be configured")
    
    async def query_context_window(self, model_name: str) -> int:
        """
        Query context window for OpenAI models.
        
        Uses known context windows for OpenAI models.
        """
        # Known OpenAI model context windows
        context_windows = {
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
            "o1": 200000,
            "o1-mini": 128000,
        }
        
        # Check if model name matches known models
        for known_model, ctx in context_windows.items():
            if known_model in model_name:
                return ctx
        
        raise RuntimeError(f"Unknown context window for model: {model_name}")


def create_server(config: LLMServerConfig) -> LLMServer:
    """
    Factory function to create the appropriate server implementation.
    
    Args:
        config: Server configuration
        
    Returns:
        LLMServer instance
    """
    if config.type == "llamacpp":
        return LlamaCppServer(config)
    elif config.type == "openrouter":
        return OpenRouterServer(config)
    elif config.type == "openai":
        return OpenAIServer(config)
    else:
        raise ValueError(f"Unknown server type: {config.type}")
