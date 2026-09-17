"""Regression tests for model/server selection and staleness.

These cover the failure modes where pico could display one model but send
another: per-server selection not applied on switch, stale discovery catalogs
resolving a model to the wrong server, and single-model endpoints (llama.cpp)
that ignore the requested model.
"""

import asyncio
from types import SimpleNamespace

import pytest
import toml

from pico_chat.harness.server_service import ServerService


@pytest.fixture
def cfg(monkeypatch):
    import pico_chat.pico_cfg as cfg_mod

    monkeypatch.setattr(cfg_mod.config, "servers", {}, raising=False)
    monkeypatch.setattr(cfg_mod.config, "model_selection", {}, raising=False)
    monkeypatch.setattr(cfg_mod.config, "models_by_server", {}, raising=False)
    monkeypatch.setattr(cfg_mod.config, "active_server", "a", raising=False)
    monkeypatch.setattr(cfg_mod.config, "active_model", None, raising=False)
    return cfg_mod


def test_get_server_config_by_name_applies_per_server_selection(cfg):
    cfg.config.servers["srv"] = {
        "type": "ollama",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "legacy-default",
    }
    cfg.config.model_selection["srv"] = "selected-model"

    from pico_chat.harness.llm_server_config import get_server_config_by_name

    assert get_server_config_by_name("srv").model == "selected-model"


def test_get_server_config_by_name_falls_back_to_legacy_model(cfg):
    cfg.config.servers["srv"] = {
        "type": "ollama",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "legacy-default",
    }

    from pico_chat.harness.llm_server_config import get_server_config_by_name

    assert get_server_config_by_name("srv").model == "legacy-default"


def test_resolve_and_all_models_ignore_unconfigured_servers(cfg):
    cfg.config.servers = {
        "known": {"type": "ollama", "base_url": "http://x/v1", "model": "m1"},
    }
    cfg.config.models_by_server = {
        "known": [{"id": "m1"}],
        "removed": [{"id": "gone-model"}],
    }

    service = ServerService()

    assert service.resolve_model_servers("m1") == ["known"]
    assert service.resolve_model_servers("gone-model") == []
    assert [m.id for m in service.all_models()] == ["m1"]


def test_remove_server_drops_catalog_entry(cfg, tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml.dumps({
        "servers": {
            "a": {"type": "ollama", "base_url": "http://a/v1", "model": "ma"},
            "b": {"type": "ollama", "base_url": "http://b/v1", "model": "mb"},
        },
        "settings": {"active_server": "a"},
    }))
    monkeypatch.setattr(cfg, "get_config_path", lambda: config_path)
    cfg.config.servers = {
        "a": {"type": "ollama", "base_url": "http://a/v1", "model": "ma"},
        "b": {"type": "ollama", "base_url": "http://b/v1", "model": "mb"},
    }
    cfg.config.models_by_server = {"a": [{"id": "ma"}], "b": [{"id": "mb"}]}

    result = ServerService().remove_server("b")

    assert result.ok
    assert "b" not in cfg.config.models_by_server
    assert "b" not in cfg.config.servers


def test_llamacpp_reconciles_requested_selection_with_served_model(cfg, monkeypatch):
    from pico_chat.harness.llm_server import LlamaCppServer
    from pico_chat.harness.llm_server_config import LLMServerConfig

    config = LLMServerConfig(
        name="local", type="llamacpp", base_url="http://localhost:8080/v1",
        api_key="EMPTY", model="served-model", max_context=None,
    )
    server = LlamaCppServer(config)

    async def _fake_diagnose():
        return SimpleNamespace(ok=True)

    async def _fake_query_model_name():
        return "served-model"

    monkeypatch.setattr(server, "diagnose_connection", _fake_diagnose)
    monkeypatch.setattr(server, "query_model_name", _fake_query_model_name)

    server.set_model("requested-but-ignored")
    asyncio.run(server.prewarm_model_name())

    assert server.selected_model == "served-model"
    assert server._cached_model_name == "served-model"


def test_openrouter_save_persists_enabled_models(cfg, monkeypatch):
    cfg.config.servers = {
        "or": {
            "type": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "k",
            "model": "openai/gpt-4o",
        },
    }
    cfg.config.models_by_server = {"or": [{"id": "old-model"}]}
    saved = {}

    def fake_save_server(name, server_config, set_active=True):
        saved[name] = dict(server_config)
        cfg.config.servers[name] = dict(server_config)

    monkeypatch.setattr(cfg.config, "save_server", fake_save_server, raising=False)
    monkeypatch.setattr(cfg.config, "save_model_catalog", lambda: None, raising=False)

    from pico_chat.ui.openrouter_settings import build_openrouter_fields

    fields, save = build_openrouter_fields()
    enabled = next(
        f for f in fields
        if getattr(f, "label", "") == "Enabled models (comma-separated)"
    )
    enabled.set_value("openai/gpt-4o, anthropic/claude-3.5-sonnet")
    save()

    assert saved["or"]["enabled_models"] == [
        "openai/gpt-4o", "anthropic/claude-3.5-sonnet"
    ]
    # The stale catalog must be invalidated so /model re-discovers.
    assert "or" not in cfg.config.models_by_server
