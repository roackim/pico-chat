"""
LLM Server abstraction layer.

Provides a unified interface for interacting with different LLM servers
(llamacpp, openrouter, openai, etc.) with automatic model and context detection.
"""
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from types import SimpleNamespace
from typing import Optional, AsyncGenerator, Dict, Any

from openai import AsyncOpenAI, InternalServerError, APIError

from pico_chat.harness.llm_server_config import LLMServerConfig, ModelInfo, ServerType


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
        self._model_context_windows: dict[str, int] = {}
        self._selected_model: Optional[str] = config.model

    @property
    def selected_model(self) -> Optional[str]:
        """Return the model selected for this endpoint."""
        return self._selected_model

    def set_model(self, model_name: str) -> None:
        """Select a model without replacing the endpoint connection."""
        model_name = model_name.strip()
        if not model_name:
            raise ValueError("model name cannot be empty")
        self._selected_model = model_name
        self._cached_model_name = model_name
        self._cached_context_window = self._model_context_windows.get(model_name)

    async def list_models(self) -> list[ModelInfo]:
        """List models exposed by this endpoint."""
        models = await asyncio.wait_for(self.client.models.list(), timeout=self.config.timeout)
        result = []
        for model in getattr(models, "data", []) or []:
            result.append(ModelInfo(
                id=model.id,
                context_window=getattr(model, "context_length", None),
                owned_by=getattr(model, "owned_by", None),
            ))
        return result
    
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
        if self._selected_model:
            self._cached_model_name = self._selected_model
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
        model_name = await self.get_model_name()
        if model_name in self._model_context_windows:
            self._cached_context_window = self._model_context_windows[model_name]
            return self._cached_context_window
        
        # Try to query from server
        try:
            self._cached_context_window = await self.query_context_window(model_name)
            self._model_context_windows[model_name] = self._cached_context_window
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
                # Build request parameters
                kwargs = {
                    "model": model_name,
                    "messages": messages,
                    "stream": stream,
                }
                
                if tools:
                    kwargs["tools"] = tools

                # OpenAI-compatible providers commonly emit usage only when
                # explicitly requested on a streaming response. Providers
                # that ignore this option continue to work and are handled by
                # the heuristic fallback in the harness.
                if stream:
                    kwargs["stream_options"] = {"include_usage": True}
                
                # Add provider routing for OpenRouter
                if self.config.type == "openrouter" and self.config.provider:
                    kwargs["extra_body"] = {
                        "provider": {
                            "order": [self.config.provider]
                        }
                    }
                
                # Log request details for debugging (truncate long messages)
                if logger.isEnabledFor(logging.DEBUG):
                    msg_summary = []
                    for msg in messages:
                        role = msg.get("role", "?")
                        content_len = len(str(msg.get("content", "")))
                        tc_count = len(msg.get("tool_calls", []))
                        msg_summary.append(f"{role}:{content_len}chars:{tc_count}tools")
                    logger.debug(f"API request: model={model_name}, messages=[{', '.join(msg_summary)}], tools={'yes' if tools else 'no'}")
                
                response = await self.client.chat.completions.create(**kwargs)
                
                # If streaming, yield chunks
                if stream:
                    chunk_count = 0
                    try:
                        async for chunk in response:
                            chunk_count += 1
                            # Log very first and last few chunks for debugging
                            if chunk_count <= 2 or chunk_count % 50 == 0:
                                logger.debug(f"LLM chunk {chunk_count}: choices={len(chunk.choices)}, finish={chunk.choices[0].finish_reason if chunk.choices else 'N/A'}")
                            yield chunk
                        logger.debug(f"LLM stream complete: {chunk_count} total chunks")
                    except Exception as e:
                        logger.error(f"Error during streaming after {chunk_count} chunks: {type(e).__name__}: {e}")
                        raise
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
        models = await self.list_models()
        if models:
            return models[0].id
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
        models = await self.list_models()
        for model in models:
            if model.id == model_name and model.context_window:
                return model.context_window
        
        raise RuntimeError("Could not determine context window from server")


class OpenRouterServer(LLMServer):
    """Implementation for OpenRouter."""
    
    async def query_model_name(self) -> str:
        """OpenRouter uses configured model name."""
        if self._selected_model:
            return self._selected_model
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
        if self._selected_model:
            return self._selected_model
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


class OllamaServer(LLMServer):
    """Ollama endpoint using its native discovery and OpenAI-compatible chat."""

    def _native_base_url(self) -> str:
        return self.config.base_url.removesuffix("/v1").rstrip("/")

    async def check_connection(self) -> bool:
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._native_base_url()}/api/tags",
                    timeout=self.config.timeout,
                )
                return response.is_success
        except Exception:
            return False

    async def create_completion(
        self,
        messages: list[Dict[str, Any]],
        tools: Optional[list[Dict[str, Any]]] = None,
        stream: bool = True,
    ) -> AsyncGenerator[Any, None]:
        """Use Ollama's native chat API so final usage counters are retained."""
        import httpx

        payload: Dict[str, Any] = {
            "model": await self.get_model_name(),
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._native_base_url()}/api/chat",
                json=payload,
                timeout=None,
            ) as response:
                response.raise_for_status()
                if not stream:
                    data = await response.json()
                    yield self._native_response(data)
                    return

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    yield self._native_response(json.loads(line))

    @staticmethod
    def _native_response(data: Dict[str, Any]) -> Any:
        """Adapt one native Ollama response to the OpenAI chunk shape."""
        message = data.get("message") or {}
        content = message.get("content")
        reasoning = message.get("thinking")
        tool_calls = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            arguments = function.get("arguments", {})
            tool_calls.append(SimpleNamespace(
                index=index,
                id=call.get("id"),
                function=SimpleNamespace(
                    name=function.get("name"),
                    arguments=json.dumps(arguments) if isinstance(arguments, dict) else arguments,
                ),
            ))

        delta = SimpleNamespace(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
        )
        choice = SimpleNamespace(
            delta=delta,
            finish_reason="stop" if data.get("done") else None,
        )
        usage = {
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
        }
        return SimpleNamespace(
            choices=[] if data.get("done") else [choice],
            usage=usage,
        )

    async def list_models(self) -> list[ModelInfo]:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._native_base_url()}/api/tags",
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            data = response.json()

        return [
            ModelInfo(
                id=model.get("name", model.get("model", "")),
                metadata=model,
            )
            for model in data.get("models", [])
            if model.get("name", model.get("model"))
        ]

    async def query_model_name(self) -> str:
        if self._selected_model:
            return self._selected_model
        models = await self.list_models()
        if models:
            return models[0].id
        raise RuntimeError("No Ollama models available on endpoint")

    async def query_context_window(self, model_name: str) -> int:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._native_base_url()}/api/show",
                json={"name": model_name},
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            data = response.json()

        # Ollama versions expose this as model_info metadata or as num_ctx in
        # the parameter string. Keep parsing tolerant across versions.
        for key, value in data.get("model_info", {}).items():
            if key.lower().endswith(("context_length", "context", "n_ctx")) and isinstance(value, int):
                return value
        parameters = data.get("parameters", "")
        for line in str(parameters).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in {"num_ctx", "n_ctx"}:
                return int(parts[1])
        raise RuntimeError(f"Could not determine context window for Ollama model: {model_name}")


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
    elif config.type == "ollama":
        return OllamaServer(config)
    elif config.type == "openrouter":
        return OpenRouterServer(config)
    elif config.type == "openai":
        return OpenAIServer(config)
    else:
        raise ValueError(f"Unknown server type: {config.type}")
