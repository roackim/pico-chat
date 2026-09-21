"""LLM endpoints: one type for config and transport.

An :class:`Endpoint` is both the connection description (base_url, api_key,
model, discovery/routing options) and the live client. Server-family
differences are handled by small internal branches — llama.cpp / OpenAI
compatible, Ollama's native chat API, OpenRouter provider routing — instead of
an ABC plus one subclass per family.

The OpenAI-compatible chat transport is implemented directly on httpx (no SDK):
pico fully owns the connection, DNS/IP, timeouts and retries, and exposes
precise timing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, Literal, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx


logger = logging.getLogger(__name__)


ServerType = Literal["llamacpp", "ollama", "openrouter", "openai"]


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------

@dataclass
class ModelInfo:
    """Metadata for one model exposed by an endpoint."""

    id: str
    context_window: int | None = None
    owned_by: str | None = None
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}

    # Convenience accessors for the most useful Ollama metadata fields.
    @property
    def size(self) -> int | None:
        return self.metadata.get("size")

    @property
    def family(self) -> str | None:
        return self.metadata.get("family")

    @property
    def modified_at(self) -> str | None:
        return self.metadata.get("modified_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "context_window": self.context_window,
            "owned_by": self.owned_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelInfo":
        return cls(
            id=data.get("id", ""),
            context_window=data.get("context_window"),
            owned_by=data.get("owned_by"),
            metadata=data.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# HTTP client / proxy handling
# ---------------------------------------------------------------------------

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


def _new_http_client(endpoint: "Endpoint") -> httpx.AsyncClient:
    """Build the single owned httpx client for an endpoint.

    - No SDK magic: we control base_url (already the resolved IPv4 for .local),
      timeout and trust_env.
    - ``trust_env=False`` for local/LAN targets blocks inherited proxy vars.
    - ``limits`` keeps keep-alive connections open across messages in one convo
      (no re-TCP-handshake per message).
    """
    kwargs: Dict[str, Any] = {
        "base_url": endpoint.base_url,
        "timeout": httpx.Timeout(endpoint.timeout, connect=endpoint.timeout),
        "trust_env": not _is_local_target(endpoint.base_url),
        "limits": httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0),
    }
    if endpoint.api_key:
        kwargs["headers"] = {"Authorization": f"Bearer {endpoint.api_key}"}
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
            lines.append("Proxy env: " + ", ".join(f"{k}={v}" for k, v in active.items()))
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


# ---------------------------------------------------------------------------
# .local (mDNS) hostname resolution
# ---------------------------------------------------------------------------

# https://stackoverflow.com/questions/106179/regular-expression-to-match-hostname-or-ip-address
_HOSTNAME_RE = re.compile(
    r"(?=^.{1,253}$)(^((?!-)[a-zA-Z0-9-]{1,63}(?<!-)\.)+[a-zA-Z]{2,63}$)"
)

# hostname -> IP resolution cache for .local hosts. Resolutions persist for the
# process lifetime and are only refreshed when a connection failure invalidates
# them. This avoids a getent subprocess on every connect while keeping stale
# entries self-healing.
_local_cache: dict[str, Optional[str]] = {}

# Hostnames currently being resolved in a background prewarm thread. Used by the
# UI to show an animated "resolving" indicator in the status bar.
_resolving: set[str] = set()


def _getent_host(hostname: str) -> Optional[str]:
    """Resolve a hostname to an IPv4 address.

    Tries ``socket.getaddrinfo`` in-process first (same libc resolver as the
    shell), then ``getent hosts`` as a fallback. Returns the first IPv4 address,
    or None if unresolvable.
    """
    import socket

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for info in infos:
            ip = info[4][0]
            if ip:
                return ip
    except Exception as e:
        logger.warning("socket.getaddrinfo failed for %s: %s", hostname, e)

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

    httpx/OpenAI connect through ``getaddrinfo``, which can return a bare IPv6
    link-local (``fe80::``) address for ``.local`` names. For ``.local`` hosts we
    instead ask ``getent hosts`` (which follows nsswitch and prefers IPv4) and
    swap in the returned address. Cached for the process lifetime; refreshed on
    connection failure. If anything goes wrong, the original URL is returned.
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
    """Drop any cached getent resolution for ``url``'s hostname."""
    try:
        hostname = urlsplit(url).hostname
        if hostname:
            _local_cache.pop(hostname, None)
    except Exception:
        pass


def prewarm_local_resolution(url: str) -> None:
    """Kick off ``.local`` resolution for ``url`` in a background thread.

    ``socket.getaddrinfo`` (used for mDNS) can block for a moment. Running it
    off the event loop and populating the cache means the resolved IP is cached
    by the time the user sends a message. Non-``.local`` hosts are no-ops.
    """
    hostname = urlsplit(url).hostname
    if not hostname or not hostname.endswith(".local"):
        return
    if _cached_ip_for(hostname):
        return
    if hostname in _resolving:
        return

    import threading

    _resolving.add(hostname)

    def _resolve():
        try:
            _resolve_once(hostname)
        except Exception as e:
            logger.warning("prewarm resolution failed for %s: %s", hostname, e)
        finally:
            _resolving.discard(hostname)

    threading.Thread(target=_resolve, daemon=True).start()


def _resolve_local_hostname_async(url: str) -> str:
    """Resolve a ``.local`` hostname without blocking the event loop.

    Returns the resolved URL if the address is already cached, otherwise kicks
    off a background resolution and returns the original URL unchanged. Never
    performs blocking I/O on the calling thread.
    """
    hostname = urlsplit(url).hostname
    if not hostname or not hostname.endswith(".local"):
        return url
    ip = _cached_ip_for(hostname)
    if ip:
        parts = urlsplit(url)
        netloc = f"{ip}:{parts.port}" if parts.port else ip
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    prewarm_local_resolution(url)
    return url


async def _resolve_local_hostname_await(url: str) -> str:
    """Resolve a ``.local`` hostname to a routable URL, off the event loop."""
    hostname = urlsplit(url).hostname
    if not hostname or not hostname.endswith(".local"):
        return url
    ip = _cached_ip_for(hostname)
    if not ip:
        ip = await asyncio.to_thread(_resolve_once, hostname)
    if not ip:
        return url
    parts = urlsplit(url)
    netloc = f"{ip}:{parts.port}" if parts.port else ip
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def is_local_resolution_pending(url: str) -> bool:
    """True if ``.local`` resolution for ``url`` is currently in progress."""
    hostname = urlsplit(url).hostname
    if not hostname or not hostname.endswith(".local"):
        return False
    return hostname in _resolving


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

class Endpoint:
    """A single LLM endpoint: connection config plus live transport.

    Differences between server families live in the few methods that branch on
    :attr:`type`; there is no subclass hierarchy.
    """

    def __init__(
        self,
        name: str,
        type: ServerType = "llamacpp",
        base_url: str = "http://localhost:8080/v1",
        api_key: str = "",
        model: Optional[str] = None,
        max_context: Optional[int] = None,
        timeout: float = 30.0,
        retry_attempts: int = 3,
        retry_delay: float = 2.0,
        provider: Optional[str] = None,
        enabled_models: Optional[list[str]] = None,
        model_providers: Optional[dict[str, dict[str, Any]]] = None,
    ):
        self.name = name
        self.type: ServerType = type
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_context = max_context
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.provider = provider
        self.enabled_models = list(enabled_models or [])
        self.model_providers = dict(model_providers or {})

        # .local hosts are rewritten to a routable IP. Resolution can block for
        # seconds on an offline mDNS host, so it is kicked off in the background
        # and we fall back to the original URL until the address is ready.
        self._original_base_url = base_url
        self._hostname = urlsplit(base_url).hostname
        if self._hostname and self._hostname.endswith(".local"):
            self.base_url = _resolve_local_hostname_async(base_url)
        self.client = _new_http_client(self)

        # Runtime caches.
        self._cached_model_name: Optional[str] = None
        self._cached_context_window: Optional[int] = None
        self._model_context_windows: dict[str, int] = {}
        self._selected_model: Optional[str] = model
        self._model_name_pending: bool = False
        self._connection_state: str = "unknown"  # unknown|checking|ok|error

    # -- construction --------------------------------------------------------

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "Endpoint":
        """Build an endpoint from a ``servers.toml`` ``[servers.<name>]`` table."""
        api_key = data.get("api_key", "")
        api_key_env = data.get("api_key_env")
        if api_key_env:
            api_key = os.getenv(api_key_env, api_key)
        return cls(
            name=name,
            type=data.get("type", "llamacpp"),
            base_url=data.get("base_url", "http://localhost:8080/v1"),
            api_key=api_key,
            model=data.get("model"),
            max_context=data.get("max_context"),
            timeout=data.get("timeout", 30.0),
            retry_attempts=data.get("retry_attempts", 3),
            retry_delay=data.get("retry_delay", 2.0),
            provider=data.get("provider"),
            enabled_models=data.get("enabled_models"),
            model_providers=data.get("model_providers"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializable form for ``servers.toml`` (secrets stripped)."""
        data: dict[str, Any] = {
            "type": self.type,
            "base_url": self._original_base_url,
        }
        if self.api_key:
            data["api_key"] = self.api_key
        if self.model:
            data["model"] = self.model
        if self.max_context is not None:
            data["max_context"] = self.max_context
        data["timeout"] = self.timeout
        data["retry_attempts"] = self.retry_attempts
        data["retry_delay"] = self.retry_delay
        if self.provider:
            data["provider"] = self.provider
        if self.enabled_models:
            data["enabled_models"] = list(self.enabled_models)
        if self.model_providers:
            data["model_providers"] = {
                model: dict(spec) for model, spec in self.model_providers.items()
            }
        return data

    @property
    def supports_model_selection(self) -> bool:
        """Whether the endpoint honors a per-request ``model`` selection.

        llama.cpp loads exactly one model and ignores the request's ``model``.
        """
        return self.type != "llamacpp"

    # -- model selection -----------------------------------------------------

    @property
    def selected_model(self) -> Optional[str]:
        return self._selected_model

    def set_model(self, model_name: str) -> None:
        """Select a model without replacing the endpoint connection."""
        model_name = model_name.strip()
        if not model_name:
            raise ValueError("model name cannot be empty")
        self._selected_model = model_name
        self._cached_model_name = model_name
        self._cached_context_window = self._model_context_windows.get(model_name)
        if not self.supports_model_selection:
            self._cached_model_name = None
            self._cached_context_window = None
            self._connection_state = "unknown"
            logger.warning(
                "Endpoint '%s' serves a single model; the requested model '%s' "
                "will be resolved to the served model.",
                self.name, model_name,
            )

    async def prewarm_model_name(self) -> None:
        """Probe the connection and cache model name/context in the background."""
        if self._cached_model_name and self._connection_state == "ok":
            return
        self._model_name_pending = True
        self._connection_state = "checking"
        try:
            if self._hostname and self._hostname.endswith(".local"):
                new_url = _resolve_local_hostname_async(self._original_base_url)
                if new_url != self._original_base_url and new_url != self.base_url:
                    self.base_url = new_url
                    self.client = _new_http_client(self)
            diagnosis = await self.diagnose_connection()
            if not diagnosis.ok:
                self._connection_state = "error"
                return
            if not self.supports_model_selection:
                try:
                    actual = await self.query_model_name()
                    if actual and actual != self._selected_model:
                        logger.warning(
                            "Endpoint '%s' serves '%s' (requested '%s'); using "
                            "the served model.", self.name, actual, self._selected_model,
                        )
                    if actual:
                        self._selected_model = actual
                        self._cached_model_name = actual
                except Exception as e:
                    logger.warning("Could not resolve served model: %s", e)
            if not self._cached_model_name:
                try:
                    await self.get_model_name()
                    self._connection_state = "ok"
                except Exception as e:
                    logger.warning("prewarm model name failed: %s", e)
                    self._connection_state = "error"
            else:
                self._connection_state = "ok"
            try:
                await self.get_context_window()
            except Exception as e:
                logger.warning("prewarm context window failed: %s", e)
        finally:
            self._model_name_pending = False

    # -- model / context discovery ------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        """List models exposed by this endpoint."""
        if self.type == "ollama":
            return await self._list_ollama_models()
        response = await asyncio.wait_for(
            self.client.get("/models"), timeout=self.timeout
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

    async def discover_models(self) -> list[ModelInfo]:
        """Discover the models surfaced by this endpoint.

        OpenRouter exposes thousands of models, so only explicitly-enabled ids
        are surfaced. Ollama models are enriched with their context window.
        """
        if self.type == "openrouter":
            return await self._discover_openrouter_models()
        if self.type == "ollama":
            return await self._discover_ollama_models()
        return await self.list_models()

    async def query_model_name(self) -> str:
        if self.type in ("openrouter", "openai"):
            if self._selected_model:
                return self._selected_model
            raise RuntimeError(f"{self.type} requires a model to be configured")
        if self.type == "ollama" and self._selected_model:
            return self._selected_model
        models = await self.list_models()
        if models:
            return models[0].id
        raise RuntimeError(f"No models available on endpoint '{self.name}'")

    async def query_context_window(self, model_name: str) -> int:
        if self.type == "ollama":
            return await self._ollama_context_window(model_name)
        if self.type == "openrouter":
            return await self._openrouter_context_window(model_name)
        if self.type == "openai":
            return self._openai_context_window(model_name)
        return await self._llamacpp_context_window(model_name)

    async def get_model_name(self) -> str:
        """Get the model name (cached or queried)."""
        if self._cached_model_name:
            return self._cached_model_name
        try:
            self._cached_model_name = await self.query_model_name()
            logger.info("Queried model name: %s", self._cached_model_name)
            return self._cached_model_name
        except Exception as e:
            logger.warning("Failed to query model name: %s", e)
        if self._selected_model:
            self._cached_model_name = self._selected_model
            logger.info("Using model from config: %s", self._cached_model_name)
            return self._cached_model_name
        self._cached_model_name = "unknown"
        logger.warning("Model name unknown, using 'unknown'")
        return self._cached_model_name

    async def get_context_window(self) -> int:
        """Get the context window size (cached or queried).

        The result is cached on first success OR first fallback so a failing or
        slow remote query is not re-run on every message in a conversation.
        """
        model_name = await self.get_model_name()
        if model_name in self._model_context_windows:
            self._cached_context_window = self._model_context_windows[model_name]
            return self._cached_context_window
        try:
            self._cached_context_window = await self.query_context_window(model_name)
            self._model_context_windows[model_name] = self._cached_context_window
            logger.info("Queried context window: %s", self._cached_context_window)
            return self._cached_context_window
        except Exception as e:
            logger.warning("Failed to query context window: %s", e)
        if self.max_context:
            self._cached_context_window = self.max_context
        else:
            self._cached_context_window = 32768
        self._model_context_windows[model_name] = self._cached_context_window
        logger.warning("Context window unknown, using default: %s", self._cached_context_window)
        return self._cached_context_window

    # -- connection ----------------------------------------------------------

    async def check_connection(self) -> bool:
        """Check if the endpoint is reachable."""
        if self.type == "ollama":
            return await self._check_ollama_connection()
        return (await self.diagnose_connection()).ok

    async def diagnose_connection(self) -> "ConnectionDiagnosis":
        """Attempt a connection and return detailed diagnostics on failure."""
        error = None
        self._connection_state = "checking"
        try:
            await asyncio.wait_for(self.client.get("/models"), timeout=self.timeout)
            self._connection_state = "ok"
            return ConnectionDiagnosis(ok=True, url=self.base_url, error=None)
        except Exception as e:
            error = e

        if self._hostname and self._hostname.endswith(".local"):
            invalidate_local_hostname(self._original_base_url)
            new_url = await _resolve_local_hostname_await(self._original_base_url)
            if new_url != self._original_base_url:
                self.base_url = new_url
                self.client = _new_http_client(self)
                try:
                    await asyncio.wait_for(self.client.get("/models"), timeout=self.timeout)
                    self._connection_state = "ok"
                    return ConnectionDiagnosis(ok=True, url=self.base_url, error=None)
                except Exception as e2:
                    error = e2

        self._connection_state = "error"
        return ConnectionDiagnosis(
            ok=False,
            url=self.base_url,
            error=error,
            original_url=self._original_base_url,
            hostname=self._hostname,
        )

    # -- chat completion -----------------------------------------------------

    async def create_completion(
        self,
        messages: list[Dict[str, Any]],
        tools: Optional[list[Dict[str, Any]]] = None,
        stream: bool = True,
    ) -> AsyncGenerator[Any, None]:
        """Create a chat completion, streaming via SSE when ``stream`` is true.

        Ollama uses its native chat API so final usage counters are retained;
        every other family uses the OpenAI-compatible transport. Chunks are
        adapted to the SDK shape (``choices[0].delta`` / ``finish_reason`` /
        ``usage``, and ``choices[0].message`` for non-streaming).
        """
        if self.type == "ollama":
            async for chunk in self._create_ollama_completion(messages, tools, stream):
                yield chunk
            return
        async for chunk in self._create_openai_completion(messages, tools, stream):
            yield chunk

    async def _create_openai_completion(
        self,
        messages: list[Dict[str, Any]],
        tools: Optional[list[Dict[str, Any]]],
        stream: bool,
    ) -> AsyncGenerator[Any, None]:
        _t0 = time.perf_counter()
        model_name = await self.get_model_name()
        logger.info(
            "[llm] model_name resolved in %.0fms (cached=%s)",
            (time.perf_counter() - _t0) * 1000,
            bool(self._cached_model_name),
        )

        max_retries = self.retry_attempts
        retry_delay = self.retry_delay

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
            if self.type == "openrouter":
                provider_spec = self._provider_spec(model_name)
                if provider_spec:
                    payload["provider"] = provider_spec

            if logger.isEnabledFor(logging.DEBUG):
                msg_summary = []
                for msg in messages:
                    role = msg.get("role", "?")
                    content_len = len(str(msg.get("content", "")))
                    tc_count = len(msg.get("tool_calls", []))
                    msg_summary.append(f"{role}:{content_len}chars:{tc_count}tools")
                logger.debug(
                    "API request: model=%s, messages=[%s], tools=%s",
                    model_name, ", ".join(msg_summary), "yes" if tools else "no",
                )

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
                                f"Model loading timeout after {max_retries} attempts: {error_message}",
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
                                logger.debug("LLM chunk %d: choices=%d", chunk_count, len(chunk.choices))
                            yield chunk
                        logger.debug("LLM stream complete: %d total chunks", chunk_count)
                    return
                else:
                    response = await asyncio.wait_for(
                        self.client.post("/chat/completions", json=payload),
                        timeout=self.timeout,
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

    # -- Ollama native -------------------------------------------------------

    def _native_base_url(self) -> str:
        return self.base_url.removesuffix("/v1").rstrip("/")

    async def _check_ollama_connection(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._native_base_url()}/api/tags",
                    timeout=self.timeout,
                )
                return response.is_success
        except Exception:
            return False

    async def _create_ollama_completion(
        self,
        messages: list[Dict[str, Any]],
        tools: Optional[list[Dict[str, Any]]],
        stream: bool,
    ) -> AsyncGenerator[Any, None]:
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

    async def _list_ollama_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._native_base_url()}/api/tags",
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        return [
            ModelInfo(
                id=model.get("name", model.get("model", "")),
                context_window=model.get("context_length"),
                metadata=model,
            )
            for model in data.get("models", [])
            if model.get("name", model.get("model"))
        ]

    async def _discover_ollama_models(self) -> list[ModelInfo]:
        """Discover Ollama models, enriching each with its context window."""
        models = await self._list_ollama_models()
        enriched = []
        for model in models:
            try:
                ctx = await self._ollama_context_window(model.id)
                enriched.append(ModelInfo(
                    id=model.id,
                    context_window=ctx,
                    owned_by=model.owned_by,
                    metadata=model.metadata,
                ))
            except Exception as e:
                logger.debug("Could not enrich context for %s: %s", model.id, e)
                enriched.append(model)
        return enriched

    async def _ollama_context_window(self, model_name: str) -> int:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._native_base_url()}/api/show",
                json={"name": model_name},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        for key, value in data.get("model_info", {}).items():
            if key.lower().endswith(("context_length", "context", "n_ctx")) and isinstance(value, int):
                return value
        parameters = data.get("parameters", "")
        for line in str(parameters).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in {"num_ctx", "n_ctx"}:
                return int(parts[1])
        raise RuntimeError(f"Could not determine context window for Ollama model: {model_name}")

    # -- OpenRouter ----------------------------------------------------------

    def _enabled_ids(self) -> list[str]:
        """Return the explicitly-enabled model ids.

        All OpenRouter models are disabled unless explicitly enabled. The
        allowlist is ``enabled_models``, falling back to the single ``model``.
        """
        if self.enabled_models:
            return list(self.enabled_models)
        if self.model:
            return [self.model]
        return []

    def _provider_spec(self, model_name: str) -> Optional[dict]:
        """Build the OpenRouter ``provider`` payload for a model.

        Per-model routing (``model_providers``) takes precedence over the legacy
        single ``provider``. Returns ``None`` for OpenRouter's default routing.
        """
        entry = self.model_providers.get(model_name)
        if entry:
            mode = entry.get("mode")
            providers = entry.get("providers") or []
            if mode == "whitelist" and providers:
                return {"order": list(providers)}
            if mode == "blacklist" and providers:
                return {"exclude": list(providers)}
        if self.provider:
            return {"order": [self.provider]}
        return None

    async def _discover_openrouter_models(self) -> list[ModelInfo]:
        """Return only the enabled models for this OpenRouter endpoint."""
        enabled = self._enabled_ids()
        if not enabled:
            return []
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/models",
                timeout=self.timeout,
            )
            if response.status_code != 200:
                return [ModelInfo(id=e) for e in enabled]
        catalog = response.json().get("data", [])
        by_id = {m.get("id"): m for m in catalog}

        def _match(eid: str) -> dict:
            if eid in by_id:
                return by_id[eid]
            # Accept a bare id (no provider namespace) by suffix match, so
            # ``deepseek-v4-flash`` resolves ``deepseek/deepseek-v4-flash``.
            # Prefer non-alias entries (ids not prefixed with ``~``).
            suffix = "/" + eid
            fallback = None
            for cid, info in by_id.items():
                if cid.endswith(suffix):
                    if not cid.startswith("~"):
                        return info
                    fallback = fallback or info
            return fallback or {}

        result = []
        for eid in enabled:
            info = _match(eid)
            result.append(ModelInfo(
                id=info.get("id") or eid,
                context_window=info.get("context_length"),
                owned_by=info.get("owned_by"),
                metadata=info,
            ))
        return result

    async def _openrouter_context_window(self, model_name: str) -> int:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/models",
                timeout=self.timeout,
            )
            if response.status_code == 200:
                catalog = response.json().get("data", [])
                suffix = "/" + model_name
                fallback = None
                for model in catalog:
                    mid = model.get("id", "")
                    if mid != model_name and not mid.endswith(suffix):
                        continue
                    ctx = model.get("context_length")
                    if not ctx:
                        continue
                    if mid == model_name or not mid.startswith("~"):
                        return ctx
                    fallback = fallback or ctx
                if fallback:
                    return fallback
        raise RuntimeError("Could not determine context window from OpenRouter")

    # -- OpenAI / llama.cpp --------------------------------------------------

    @staticmethod
    def _openai_context_window(model_name: str) -> int:
        context_windows = {
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
            "o1": 200000,
            "o1-mini": 128000,
        }
        for known_model, ctx in context_windows.items():
            if known_model in model_name:
                return ctx
        raise RuntimeError(f"Unknown context window for model: {model_name}")

    async def _llamacpp_context_window(self, model_name: str) -> int:
        """Query context window from a llama.cpp server via /props."""
        try:
            async with httpx.AsyncClient() as client:
                url = self.base_url.replace("/v1", "/props")
                response = await client.get(url, timeout=self.timeout)
                if response.status_code == 200:
                    ctx = response.json().get("default_generation_settings", {}).get("n_ctx")
                    if ctx:
                        return ctx
        except Exception as e:
            logger.debug("Failed to query /props endpoint: %s", e)

        models = await self.list_models()
        for model in models:
            if model.id == model_name and model.context_window:
                return model.context_window
        raise RuntimeError("Could not determine context window from server")


def default_endpoint() -> Endpoint:
    """Fallback endpoint used when no server is configured."""
    return Endpoint(
        name="llamacpp_default",
        type="llamacpp",
        base_url="http://localhost:8080/v1",
        api_key="EMPTY",
        timeout=2.0,
        retry_attempts=5,
        retry_delay=2.0,
    )


def get_active_endpoint() -> Endpoint:
    """Build the endpoint currently selected in ``pico_cfg``.

    Falls back to the local llama.cpp default when nothing is configured.
    """
    from pico_chat import pico_cfg

    name = pico_cfg.config.active_server
    data = pico_cfg.config.get_active_server_config()
    if data is None:
        return default_endpoint()
    endpoint = Endpoint.from_dict(name, data)
    selected = pico_cfg.config.get_model_for_server(name)
    if selected is None and pico_cfg.config.active_model is not None:
        selected = pico_cfg.config.active_model
    if selected is not None:
        endpoint.model = selected
        endpoint._selected_model = selected
    return endpoint


def get_endpoint(name: str) -> Optional[Endpoint]:
    """Build a configured endpoint by name, applying its model selection."""
    from pico_chat import pico_cfg

    data = pico_cfg.config.servers.get(name)
    if data is None:
        return None
    endpoint = Endpoint.from_dict(name, data)
    selected = pico_cfg.config.get_model_for_server(name)
    if selected is not None:
        endpoint.model = selected
        endpoint._selected_model = selected
    return endpoint


__all__ = [
    "Endpoint",
    "ModelInfo",
    "ServerType",
    "ConnectionDiagnosis",
    "default_endpoint",
    "get_active_endpoint",
    "get_endpoint",
    "_is_local_target",
    "_new_http_client",
    "_local_cache",
    "_resolve_local_hostname",
    "invalidate_local_hostname",
    "prewarm_local_resolution",
    "is_local_resolution_pending",
]
