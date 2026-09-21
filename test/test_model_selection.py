"""Regression tests for model/endpoint selection and reconciliation.

These cover the failure modes where pico could display one model but send
another: per-server selection not applied on switch and single-model endpoints
(llama.cpp) that ignore the requested model.
"""

import asyncio
from types import SimpleNamespace

import pytest
import toml


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    import pico_chat.pico_cfg as cfg_mod

    monkeypatch.setattr(cfg_mod, "get_config_path", lambda: tmp_path / "pico.toml")
    monkeypatch.setattr(cfg_mod, "get_state_path", lambda: tmp_path / "state.toml")
    monkeypatch.setattr(cfg_mod.config, "servers", {}, raising=False)
    monkeypatch.setattr(cfg_mod.config, "model_selection", {}, raising=False)
    monkeypatch.setattr(cfg_mod.config, "models_by_server", {}, raising=False)
    monkeypatch.setattr(cfg_mod.config, "active_server", "a", raising=False)
    monkeypatch.setattr(cfg_mod.config, "active_model", None, raising=False)
    return cfg_mod


def test_get_endpoint_applies_per_server_selection(cfg):
    cfg.config.servers["srv"] = {
        "type": "ollama",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "legacy-default",
    }
    cfg.config.model_selection["srv"] = "selected-model"

    from pico_chat.harness.endpoint import get_endpoint

    assert get_endpoint("srv").model == "selected-model"


def test_get_endpoint_falls_back_to_legacy_model(cfg):
    cfg.config.servers["srv"] = {
        "type": "ollama",
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "model": "legacy-default",
    }

    from pico_chat.harness.endpoint import get_endpoint

    assert get_endpoint("srv").model == "legacy-default"


def test_remove_server_drops_config_and_catalog(cfg, tmp_path):
    config_path = tmp_path / "pico.toml"
    config_path.write_text(toml.dumps({
        "servers": {
            "a": {"type": "ollama", "base_url": "http://a/v1", "model": "ma"},
            "b": {"type": "ollama", "base_url": "http://b/v1", "model": "mb"},
        },
    }))
    cfg.config.servers = {
        "a": {"type": "ollama", "base_url": "http://a/v1", "model": "ma"},
        "b": {"type": "ollama", "base_url": "http://b/v1", "model": "mb"},
    }
    cfg.config.models_by_server = {"a": [{"id": "ma"}], "b": [{"id": "mb"}]}
    cfg.config.active_server = "a"

    assert cfg.config.remove_server("b") is True

    assert "b" not in cfg.config.servers
    assert "b" not in cfg.config.models_by_server
    assert "b" not in toml.load(config_path)["servers"]


def test_llamacpp_reconciles_requested_selection_with_served_model(cfg, monkeypatch):
    from pico_chat.harness.endpoint import Endpoint

    endpoint = Endpoint(
        name="local", type="llamacpp", base_url="http://localhost:8080/v1",
        api_key="EMPTY", model="served-model",
    )

    async def _fake_diagnose():
        return SimpleNamespace(ok=True)

    async def _fake_query_model_name():
        return "served-model"

    monkeypatch.setattr(endpoint, "diagnose_connection", _fake_diagnose)
    monkeypatch.setattr(endpoint, "query_model_name", _fake_query_model_name)

    endpoint.set_model("requested-but-ignored")
    asyncio.run(endpoint.prewarm_model_name())

    assert endpoint.selected_model == "served-model"
    assert endpoint._cached_model_name == "served-model"


