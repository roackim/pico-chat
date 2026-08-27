"""
LLM Server abstraction layer.

Provides a unified interface for interacting with different LLM servers
(llamacpp, openrouter, openai, etc.) with automatic model and context detection.

The OpenAI-compatible chat transport is implemented directly on top of httpx
(no openai SDK): we fully own the connection, DNS/IP, timeouts and retries, and
can expose precise timing. Only the three server families pico supports are
covered: llama.cpp / Ollama / OpenRouter (+ generic OpenAI-compatible).
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional, AsyncGenerator, Dict, Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from pico_chat.harness.llm_server_config import LLMServerConfig, ModelInfo, ServerType


logger = logging.getLogger(__name__)

# httpx reads HTTP(S)_PROXY / ALL_PROXY / NO_PROXY by default but, unlike curl,
# does NOT honor NO_PROXY beyond exact matches. WSL setups commonly inherit a
# Windows HTTP_PROXY that routes LAN/localhost traffic through a bogus proxy —
# "curl works, pico doesn't". For local/LAN targets we pin trust_env=False.
ALL_PROXY_KEYS = ("http_proxy", "https_proxy", "all_proxy")


def _is_local_target(url: str) -> bool:
    """True if the URL targets a local/LAN host that should bypass any proxy."""
    hostname = urlsplit(url).hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    if hostname.endswith(".local"):
        return True
    # RFC1918 private ranges + link-local.
    return hostname.startswith(("192.168.", "10.", "172."))


def _new_http_client(config: LLMServerConfig) -> httpx.AsyncClient:
    """Build the single owned httpx client for a server config.

    - No SDK magic: we control base_url (already the resolved IPv4 for .local),
      timeout and trust_env.
    - ``trust_env=False`` for local/LAN targets blocks inherited proxy vars.
    - ``limits`` keeps keep-alive connections open across messages in one convo
      (no re-TCP-handshake per message).
    """
    kwargs: Dict[str, Any] = {
        "base_url": config.base_url,
        "timeout": httpx.Timeout(config.timeout, connect=config.timeout),
        "trust_env": not _is_local_target(config.base_url),
        "limits": httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0),
    }
    if config.api_key:
        kwargs["headers"] = {"Authorization": f"Bearer {config.api_key}"}
    return httpx.AsyncClient(**kwargs)


# --- OpenAI-compatible response adaptation --------------------------------


def _adapt_tool_calls(raw_calls: Any) -> list:
    """Adapt raw tool-call dicts to the ``{index,id,function:{name,arguments}}`` shape."""
    if not raw_calls:
        return []
    adapted = []
    for index, call in enumerate(raw_calls):
        function = call.get("function") or {}
        arguments = function.get("arguments")
        # Some providers send arguments as a JSON object already.
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        adapted.append(SimpleNamespace(
            index=index,
            id=call.get("id"),
            function=SimpleNamespace(
                name=function.get("name"),
                arguments=arguments or "",
            ),
        ))
    return adapted


def _adapt_stream_chunk(data: Dict[str, Any]) -> Any:
    """Adapt one streaming ``chat.completions`` SSE object to SDK chunk shape."""
    choice = None
    raw_choices = data.get("choices") or []
    if raw_choices:
        rc = raw_choices[0]
        delta = rc.get("delta") or {}
        choice = SimpleNamespace(
            index=rc.get("index", 0),
            delta=SimpleNamespace(
                content=delta.get("content"),
                reasoning_content=delta.get("reasoning_content"),
                refusal=delta.get("refusal"),
                tool_calls=_adapt_tool_calls(delta.get("tool_calls")),
            ),
            finish_reason=rc.get("finish_reason"),
        )
    return SimpleNamespace(
        id=data.get("id"),
        choices=[] if choice is None else [choice],
        usage=data.get("usage"),
    )


def _adapt_message(message: Dict[str, Any]) -> SimpleNamespace:
    """Adapt a non-streaming ``choices[0].message`` to SDK message shape."""
    return SimpleNamespace(
        role=message.get("role"),
        content=message.get("content"),
        refusal=message.get("refusal"),
        tool_calls=_adapt_tool_calls(message.get("tool_calls")),
    )


def _adapt_chat_response(data: Dict[str, Any]) -> Any:
    """Adapt a non-streaming ``chat.completions`` response to SDK shape."""
    choices = []
    for rc in data.get("choices") or []:
        choices.append(SimpleNamespace(
            index=rc.get("index", 0),
            message=_adapt_message(rc.get("message") or {}),
            finish_reason=rc.get("finish_reason"),
        ))
    return SimpleNamespace(
        id=data.get("id"),
        choices=choices,
        usage=data.get("usage"),
    )


@dataclass
class ConnectionDiagnosis:
    """Result of a connection attempt, with diagnostics on failure."""
    ok: bool
    url: str
    error: Optional[Exception] = None
    original_url: Optional[str] = None
    hostname: Optional[str] = None

    def message(self) -> str:
        """Human-readable summary for the /server diagnose command."""
        lines = [f"URL     : {self.url}"]
        if self.original_url and self.original_url != self.url:
            lines.append(f"Orig    : {self.original_url}")
        if self.ok:
            lines.append("Status  : ONLINE")
            return "\n".join(lines)

        lines.append("Status  : UNREACHABLE")
        line = f"Error   : {self.error}"
        if self.error is not None:
            line += f" ({type(self.error).__name__})"
        lines.append(line)

        # Proxy hints — the most common silent killer.
        active = {
            k: os.environ.get(k) or os.environ.get(k.upper())
            for k in ALL_PROXY_KEYS
            if os.environ.get(k) or os.environ.get(k.upper())
        }
        no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY")
        if active:
            lines.append("Proxy env: " + ", ".join(f"{k}={v}" for k, v in active.items()) or "none")
            lines.append(
                "Hint     : httpx may route through these proxy vars. If the "
                "server is on your LAN, unset them or ensure it bypasses the proxy."
            )
        if no_proxy:
            lines.append(f"NO_PROXY : {no_proxy}")

        # DNS hint for un-resolvable .local hosts.
        if self.hostname and self.hostname.endswith(".local") and not self.ok:
            lines.append(
                "Hint     : .local hostname resolution happens via `getent`. "
                "Run `getent hosts " + self.hostname + "` to verify it resolves to an IP."
            )

        return "\n".join(lines)

# https://stackoverflow.com/questions/106179/regular-expression-to-match-hostname-or-ip-address
_HOSTNAME_RE = re.compile(
    r"(?=^.{1,253}$)(^((?!-)[a-zA-Z0-9-]{1,63}(?<!-)\.)+[a-zA-Z]{2,63}$)"
)

# hostname -> IP resolution cache for .local hosts. Resolutions persist for the
# process lifetime and are only refreshed when a connection failure invalidates
# them (see invalidate_local_hostname / diagnose_connection). This avoids a
# getent subprocess on every connect while keeping stale entries self-healing.
_local_cache: dict[str, Optional[str]] = {}


def _getent_host(hostname: str) -> Optional[str]:
    """Resolve a hostname to an IPv4 address.

    Tries, in order:
    1. ``socket.getaddrinfo`` in-process — uses the same libc resolver as the
       shell (nsswitch + mDNS), no subprocess, no timeout hang. This is the
       reliable path; a ``getent`` subprocess can hang on mDNS when the process
       environment differs from the shell (e.g. under ``pixi run`` / WSL).
    2. ``getent hosts`` as a fallback.

    Returns the first IPv4 address, or None if unresolvable.
    """
    import socket

    # In-process resolution first — matches what the shell's `getent` does.
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for info in infos:
            ip = info[4][0]
            if ip:
                return ip
    except Exception as e:
        logger.warning("socket.getaddrinfo failed for %s: %s", hostname, e)

    # Fallback: getent subprocess (generous timeout — only reached if the
    # in-process resolver above failed, so it's a rare safety net).
    try:
        result = subprocess.run(
            ["getent", "hosts", hostname],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        line = result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else ""
        return line.split()[0] if line else None
    except Exception as e:
        logger.warning("getent failed for %s: %s", hostname, e)
        return None


def _cached_ip_for(hostname: str) -> Optional[str]:
    """Return the cached IP for hostname, or None if not yet resolved."""
    return _local_cache.get(hostname)


def _resolve_once(hostname: str) -> Optional[str]:
    """Resolve hostname via getent (uncached) and cache the result."""
    ip = _getent_host(hostname)
    if ip:
        _local_cache[hostname] = ip
        logger.info("Resolved %s via getent → %s", hostname, ip)
    else:
        _local_cache.pop(hostname, None)
        logger.warning("getent could not resolve %s", hostname)
    return ip


def _resolve_local_hostname(url: str) -> str:
    """Resolve a ``.local`` (mDNS/Bonjour) hostname to a routable address.

    httpx/OpenAI connect through ``getaddrinfo``, which can return a bare
    IPv6 link-local (``fe80::``) address for ``.local`` names. Connecting to
    ``fe80::`` without an interface scope fails ("no route"/"network
    unreachable") even though the name lookup succeeds — so pico fails to
    reach servers that plain tools (ping/curl) can reach.

    For ``.local`` hosts we instead ask ``getent hosts`` (which follows
    nsswitch and prefers IPv4 / ``/etc/hosts``) and swap in the returned
    address. The result is cached for the process lifetime and only refreshed
    when a connection failure invalidates the entry. If anything goes wrong,
    the original URL is returned unchanged.
    """
    try:
        hostname = urlsplit(url).hostname
        if not hostname or not _HOSTNAME_RE.match(hostname) or not hostname.endswith(".local"):
            return url

        ip = _cached_ip_for(hostname) or _resolve_once(hostname)
        if not ip:
            return url

        parts = urlsplit(url)
        # Preserve scheme, path, query, fragment — only swap the host.
        netloc = f"{ip}:{parts.port}" if parts.port else ip
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception as e:
        logger.warning("Failed to resolve %s host via getent: %s — using original URL", url, e)
        return url


def invalidate_local_hostname(url: str) -> None:
    """Drop any cached getent resolution for ``url``'s hostname.

    Called after a connect failure so the next attempt re-runs ``getent``
    once instead of reusing a stale address.
    """
    try:
        hostname = urlsplit(url).hostname
        if hostname:
            _local_cache.pop(hostname, None)
    except Exception:
        pass


class LLMServer(ABC):
    """Abstract base class for LLM server implementations."""

    def __init__(self, config: LLMServerConfig):
        """Initialize the server with configuration."""
        self.config = config
        self._original_base_url = config.base_url
        # If this is a .local host, we rewrite base_url to a routable IP;
        # keep the original hostname so a stale cache can be invalidated and
        # re-resolved on connection failure.
        self._hostname = urlsplit(config.base_url).hostname
        if self._hostname and self._hostname.endswith(".local"):
            self.config.base_url = _resolve_local_hostname(config.base_url)
        self.client = _new_http_client(self.config)
        logger.info(
            "LLM client initialized: original=%s resolved=%s trust_env=%s",
            self._original_base_url,
            self.config.base_url,
            not _is_local_target(self.config.base_url),
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
        response = await asyncio.wait_for(
            self.client.get("/models"), timeout=self.config.timeout
        )
        response.raise_for_status()
        data = response.json()
        result = []
        for model in data.get("data", []) or []:
            result.append(ModelInfo(
                id=model.get("id"),
                context_window=model.get("context_length"),
                owned_by=model.get("owned_by"),
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

        The result is cached on first success OR first fallback so a failing /
        slow remote query is not re-run on every message in a conversation.

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

        # Fallback to config — and cache it so we don't re-query every message.
        if self.config.max_context:
            self._cached_context_window = self.config.max_context
        else:
            self._cached_context_window = 32768
        self._model_context_windows[model_name] = self._cached_context_window
        logger.warning(f"Context window unknown, using default: {self._cached_context_window}")
        return self._cached_context_window
    
    async def check_connection(self) -> bool:
        """
        Check if the server is reachable.

        For ``.local`` hosts, a failed connect invalidates the cached
        ``getent`` resolution and re-resolves + retries exactly once (the
        address may have changed or gone stale). Non-``.local`` hosts are
        simply tried once.
        
        Returns:
            True if server is online, False otherwise
        """
        return (await self.diagnose_connection()).ok

    async def diagnose_connection(self) -> "ConnectionDiagnosis":
        """
        Attempt a connection and return detailed diagnostics on failure.

        Unlike ``check_connection``, this surfaces the *reason* a connect
        failed (DNS, proxy, timeout, connection refused, etc.) plus the
        resolved URL and any proxy env vars that would have applied.

        Returns:
            ConnectionDiagnosis with ok/message details
        """
        error = None
        try:
            await asyncio.wait_for(self.client.get("/models"), timeout=self.config.timeout)
            return ConnectionDiagnosis(ok=True, url=self.config.base_url, error=None)
        except Exception as e:
            error = e

        # .local host: drop stale cache and re-resolve once.
        if self._hostname and self._hostname.endswith(".local"):
            invalidate_local_hostname(self._original_base_url)
            new_url = _resolve_local_hostname(self._original_base_url)
            if new_url != self._original_base_url:
                self.config.base_url = new_url
                self.client = _new_http_client(self.config)
                try:
                    await asyncio.wait_for(self.client.get("/models"), timeout=self.config.timeout)
                    return ConnectionDiagnosis(ok=True, url=self.config.base_url, error=None)
                except Exception as e2:
                    error = e2

        return ConnectionDiagnosis(
            ok=False,
            url=self.config.base_url,
            error=error,
            original_url=self._original_base_url,
            hostname=self._hostname,
        )

    async def create_completion(
        self,
        messages: list[Dict[str, Any]],
        tools: Optional[list[Dict[str, Any]]] = None,
        stream: bool = True,
    ) -> AsyncGenerator[Any, None]:
        """
        Create a chat completion, streaming via SSE when ``stream`` is true.

        Implemented directly on httpx (no openai SDK): we own the connection
        and expose precise timing. Chunks are adapted to the same shape the
        SDK produced (``choices[0].delta`` / ``.finish_reason`` / ``.usage``,
        and ``choices[0].message`` for non-streaming) so downstream callers
        (harness, UI) are unaffected.

        Args:
            messages: List of message dictionaries
            tools: Optional list of tool schemas
            stream: Whether to stream the response

        Yields:
            Completion chunks if streaming, otherwise yields final response
        """
        _t0 = time.perf_counter()
        model_name = await self.get_model_name()
        logger.info(
            "[llm] model_name resolved in %.0fms (cached=%s)",
            (time.perf_counter() - _t0) * 1000,
            bool(self._cached_model_name),
        )

        max_retries = self.config.retry_attempts
        retry_delay = self.config.retry_delay

        for attempt in range(max_retries):
            payload: Dict[str, Any] = {
                "model": model_name,
                "messages": messages,
                "stream": stream,
            }
            if tools:
                payload["tools"] = tools
            if stream:
                payload["stream_options"] = {"include_usage": True}
            # OpenRouter provider routing.
            if self.config.type == "openrouter" and self.config.provider:
                payload["provider"] = {"order": [self.config.provider]}

            if logger.isEnabledFor(logging.DEBUG):
                msg_summary = []
                for msg in messages:
                    role = msg.get("role", "?")
                    content_len = len(str(msg.get("content", "")))
                    tc_count = len(msg.get("tool_calls", []))
                    msg_summary.append(f"{role}:{content_len}chars:{tc_count}tools")
                logger.debug(f"API request: model={model_name}, messages=[{', '.join(msg_summary)}], tools={'yes' if tools else 'no'}")

            _t_req = time.perf_counter()

            try:
                if stream:
                    async with self.client.stream("POST", "/chat/completions", json=payload) as response:
                        if response.status_code == 503:
                            error_body = await response.aread()
                            error_message = error_body.decode(errors="replace")
                            if attempt < max_retries - 1:
                                logger.warning(
                                    "Model loading (503), retrying in %.1fs (attempt %d/%d)",
                                    retry_delay, attempt + 1, max_retries,
                                )
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 1.5
                                continue
                            raise httpx.HTTPStatusError(
                                f"Model loading timeout after {max_retries} attempts",
                                request=response.request, response=response,
                            )
                        response.raise_for_status()
                        headers_at = time.perf_counter()
                        logger.info(
                            "[llm] POST /chat/completions headers received in %.0fms",
                            (headers_at - _t_req) * 1000,
                        )
                        chunk_count = 0
                        first_chunk_at = None
                        async for chunk in self._iter_sse_chunks(response):
                            if first_chunk_at is None:
                                first_chunk_at = time.perf_counter()
                                logger.info(
                                    "[llm] first token after %.0fms (headers->first)",
                                    (first_chunk_at - headers_at) * 1000,
                                )
                            chunk_count += 1
                            if chunk_count <= 2 or chunk_count % 50 == 0:
                                logger.debug(f"LLM chunk {chunk_count}: choices={len(chunk.choices)}")
                            yield chunk
                        logger.debug(f"LLM stream complete: {chunk_count} total chunks")
                    return
                else:
                    response = await asyncio.wait_for(
                        self.client.post("/chat/completions", json=payload),
                        timeout=self.config.timeout,
                    )
                    if response.status_code == 503:
                        if attempt < max_retries - 1:
                            logger.warning("Model loading (503), retrying in %.1fs", retry_delay)
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 1.5
                            continue
                        response.raise_for_status()
                    response.raise_for_status()
                    data = response.json()
                    yield _adapt_chat_response(data)
                    return
            except (httpx.HTTPStatusError, httpx.RequestError, asyncio.TimeoutError, httpx.TimeoutException) as e:
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code != 503:
                    raise
                if attempt < max_retries - 1:
                    logger.warning(
                        "Request failed (%s) retrying in %.1fs (attempt %d/%d)",
                        type(e).__name__, retry_delay, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.5
                    continue
                raise

    async def _iter_sse_chunks(self, response: httpx.Response):
        """Parse SSE ``data:`` lines from a streaming response into chunks."""
        async for line in response.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                logger.debug("Skipping non-JSON SSE line: %r", data[:80])
                continue
            yield _adapt_stream_chunk(obj)


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
