"""Tests for the .local (mDNS) hostname resolver and its connect-retry path."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pico_chat.harness.llm_server import (
    LlamaCppServer,
    _local_cache,
    _resolve_local_hostname,
    invalidate_local_hostname,
)
from pico_chat.harness.llm_server_config import LLMServerConfig


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure a clean resolver cache around every test."""
    _local_cache.clear()
    yield
    _local_cache.clear()


def make_server(base_url: str):
    config = LLMServerConfig(
        name="test",
        type="llamacpp",
        base_url=base_url,
        api_key="EMPTY",
        model=None,
        max_context=None,
        timeout=1.0,
        retry_attempts=1,
        retry_delay=0.0,
    )
    # LlamaCppServer doesn't override check_connection, so it exercises the
    # base class retry/invalidate logic.
    return LlamaCppServer(config)


# --- Resolver behavior ---


def test_non_local_url_untouched():
    with patch("pico_chat.harness.llm_server._getent_host") as getent:
        url = "http://openrouter.ai/api/v1"
        assert _resolve_local_hostname(url) == url
        getent.assert_not_called()


def test_local_host_rewritten_with_ip():
    with patch("pico_chat.harness.llm_server._getent_host", return_value="192.168.1.50"):
        assert _resolve_local_hostname("http://llm-mini-server.local:8080") == "http://192.168.1.50:8080"
        assert _resolve_local_hostname("http://llm-mini-server.local:8080/v1") == "http://192.168.1.50:8080/v1"


def test_resolution_is_cached():
    with patch("pico_chat.harness.llm_server._getent_host") as getent:
        getent.return_value = "192.168.1.50"
        assert _resolve_local_hostname("http://srv.local/path") == "http://192.168.1.50/path"
        assert _resolve_local_hostname("http://srv.local/path") == "http://192.168.1.50/path"
        # getent should only be called once thanks to the cache.
        assert getent.call_count == 1


def test_cache_persists_across_calls():
    # Resolution survives repeated lookups without re-running getent.
    with patch("pico_chat.harness.llm_server._getent_host") as getent:
        getent.return_value = "192.168.1.50"
        for _ in range(5):
            assert _resolve_local_hostname("http://srv.local/x") == "http://192.168.1.50/x"
        assert getent.call_count == 1


def test_getent_failure_returns_original():
    with patch("pico_chat.harness.llm_server._getent_host", return_value=None):
        url = "http://srv.local:8080"
        assert _resolve_local_hostname(url) == url


def test_invalidate_drops_cache():
    with patch("pico_chat.harness.llm_server._getent_host") as getent:
        getent.return_value = "192.168.1.50"
        assert _resolve_local_hostname("http://srv.local") == "http://192.168.1.50"
        invalidate_local_hostname("http://srv.local")
        assert "srv.local" not in _local_cache
        # Re-resolving should call getent again.
        _resolve_local_hostname("http://srv.local")
        assert getent.call_count == 2


# --- Connect-time invalidate + retry ---


def test_connect_failure_retries_with_fresh_resolution():
    # Model a stale resolution: first GET /models raises, fresh one succeeds.
    stale = MagicMock()
    stale.get = AsyncMock(side_effect=ConnectionError("stale address"))
    fresh = MagicMock()
    fresh.get = AsyncMock(return_value=MagicMock())

    with patch("pico_chat.harness.llm_server._new_http_client", side_effect=[stale, fresh]), patch(
        "pico_chat.harness.llm_server._getent_host",
        side_effect=["192.168.1.50", "192.168.1.99"],  # fresh IP on re-resolve
    ):
        server = make_server("http://srv.local:8080")
        ok = _run(server.check_connection())

    assert ok is True
    # The server config was re-pointed at the freshly resolved address.
    assert server.config.base_url == "http://192.168.1.99:8080"
    stale.get.assert_called_once()
    fresh.get.assert_called_once()


def test_connect_failure_non_local_does_not_retry():
    down = MagicMock()
    down.get = AsyncMock(side_effect=ConnectionError("down"))

    with patch("pico_chat.harness.llm_server._new_http_client", return_value=down), patch(
        "pico_chat.harness.llm_server._getent_host"
    ) as getent:
        server = make_server("http://localhost:8080")
        ok = _run(server.check_connection())

    assert ok is False
    # Non-.local host: no getent fallback, and we only built the client once.
    getent.assert_not_called()
    down.get.assert_called_once()


# --- Context-window fallback caching ---


def test_context_window_fallback_is_cached():
    """A failing context-window query must not re-run on every message."""
    server = make_server("http://localhost:8080")
    server._cached_model_name = "m"

    # query_context_window always fails (e.g. /props not available).
    async def always_fail():
        raise RuntimeError("no n_ctx")

    with patch.object(
        server, "query_context_window", side_effect=AsyncMock(side_effect=RuntimeError("no n_ctx"))
    ):
        first = _run(server.get_context_window())
    assert first == 32768  # default fallback

    # Second call, with the query eagerly re-queried, must NOT call again.
    with patch.object(
        server, "query_context_window", side_effect=RuntimeError("no n_ctx")
    ) as qmock:
        second = _run(server.get_context_window())

    assert second == 32768
    # Because the fallback is cached, the network query is never re-attempted.
    qmock.assert_not_called()


def _run(coro):
    import asyncio

    return asyncio.run(coro)