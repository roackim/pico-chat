"""Tests for the R4 config loader: pico.toml intent + state.toml state."""

import toml

from pico_chat.pico_cfg import Config


def _write(path, data):
    path.write_text(toml.dumps(data), encoding="utf-8")
    return path


def test_pico_toml_sections_apply(tmp_path):
    pico = _write(tmp_path / "pico.toml", {
        "ui": {"theme": "pastel", "msg_h_padding": 2, "status_bar_fields": ["role"]},
        "context": {"format": "flat", "max_files": 50},
        "subagents": {"max_depth": 3, "server": "local", "timeout": 30},
        "debug": {"log_enabled": True},
        "servers": {
            "local": {"type": "llamacpp", "base_url": "http://localhost:8080/v1"},
        },
    })
    config = Config(config_path=pico, state_path=tmp_path / "state.toml")

    assert config.load_errors == []
    assert config.ui_theme == "pastel"
    assert config.ui_msg_h_padding == 2
    assert config.ui_status_bar_fields == ["role"]
    assert config.context_format == "flat"
    assert config.context_max_files == 50
    assert config.subagent_max_depth == 3
    assert config.subagent_server == "local"
    assert config.debug_log_enabled is True
    assert config.servers["local"]["base_url"] == "http://localhost:8080/v1"


def test_invalid_values_are_reported_and_do_not_apply(tmp_path):
    pico = _write(tmp_path / "pico.toml", {
        "ui": {"theme": "dark", "msg_h_padding": "wide", "bogus": 1},
        "context": {"format": "spiral"},
        "nonsense": {},
        "servers": {"local": {"type": "wat", "base_url": 5}},
    })
    config = Config(config_path=pico, state_path=tmp_path / "state.toml")

    assert config.ui_theme == "dark"
    assert config.ui_msg_h_padding == 1  # default kept
    assert config.context_format == "tree"  # default kept

    joined = "\n".join(config.load_errors)
    assert "unknown key 'bogus'" in joined
    assert "msg_h_padding must be an integer" in joined
    assert "format must be 'tree' or 'flat'" in joined
    assert "unknown section [nonsense]" in joined
    assert "unknown server type 'wat'" in joined
    assert "base_url must be a string" in joined


def test_malformed_toml_reports_error_and_keeps_defaults(tmp_path):
    pico = tmp_path / "pico.toml"
    pico.write_text("this is = = not toml", encoding="utf-8")

    config = Config(config_path=pico, state_path=tmp_path / "state.toml")

    assert config.load_errors
    assert config.ui_theme == "terminal"


def test_state_toml_loads_selection_and_catalog(tmp_path):
    state = _write(tmp_path / "state.toml", {
        "last_server": "local",
        "active_model": "fallback-model",
        "last_model": {"local": "qwen"},
        "model_catalog": {"local": [{"id": "qwen", "context_window": 32768}]},
    })
    config = Config(config_path=tmp_path / "pico.toml", state_path=state)

    assert config.active_server == "local"
    assert config.active_model == "fallback-model"
    assert config.model_selection == {"local": "qwen"}
    assert config.models_by_server == {"local": [{"id": "qwen", "context_window": 32768}]}
    assert config.get_model_for_server("local") == "qwen"


def test_state_is_written_separately_from_intent(tmp_path):
    pico = _write(tmp_path / "pico.toml", {
        "servers": {"local": {"type": "llamacpp", "base_url": "http://x/v1"}},
    })
    state = tmp_path / "state.toml"
    config = Config(config_path=pico, state_path=state)

    config.save_model_selection("local", "qwen")
    config.save_active_model("qwen")
    config.models_by_server = {"local": [{"id": "qwen"}]}
    config.save_model_catalog()

    intent = toml.load(pico)
    assert "last_model" not in intent.get("servers", {}).get("local", {})
    assert "model_catalog" not in intent

    persisted = toml.load(state)
    assert persisted["last_model"] == {"local": "qwen"}
    assert persisted["active_model"] == "qwen"
    assert persisted["model_catalog"] == {"local": [{"id": "qwen"}]}


def test_save_server_writes_intent_and_preserves_other_sections(tmp_path):
    pico = _write(tmp_path / "pico.toml", {"ui": {"theme": "pastel"}})
    state = tmp_path / "state.toml"
    config = Config(config_path=pico, state_path=state)

    config.save_server("local", {"type": "llamacpp", "base_url": "http://x/v1"})

    intent = toml.load(pico)
    assert intent["ui"]["theme"] == "pastel"
    assert intent["servers"]["local"]["base_url"] == "http://x/v1"
    assert toml.load(state)["last_server"] == "local"


def test_default_pico_template_is_valid_and_error_free(tmp_path):
    from pico_chat.pico_cfg import DEFAULT_PICO_TOML

    pico = tmp_path / "pico.toml"
    pico.write_text(DEFAULT_PICO_TOML, encoding="utf-8")
    config = Config(config_path=pico, state_path=tmp_path / "state.toml")

    assert config.load_errors == []
    assert config.servers == {}
    assert config.ui_theme == "terminal"


def test_default_role_template_is_valid_toml():
    from pico_chat.pico_cfg import DEFAULT_ROLE_TOML

    data = toml.loads(DEFAULT_ROLE_TOML)
    # The example is a single role body, disabled so it is not listed.
    assert data["disabled"] is True
    assert "roles" not in data
    assert data["tools"]["read"]["enabled"] is True


def test_ensure_files_write_templates(tmp_path, monkeypatch):
    import pico_chat.pico_cfg as cfg_mod

    monkeypatch.setattr(cfg_mod, "get_roles_dir", lambda: tmp_path / "roles")
    config = Config(config_path=tmp_path / "pico.toml", state_path=tmp_path / "state.toml")

    pico = config.ensure_config_file()
    config.ensure_config_file()  # idempotent, does not clobber
    roles_dir = cfg_mod.ensure_roles_dir()

    assert pico.exists()
    assert roles_dir == tmp_path / "roles"
    example = roles_dir / cfg_mod.ROLE_EXAMPLE_FILENAME
    assert example.exists()
    assert "[tools.read]" in example.read_text(encoding="utf-8")


def test_reload_picks_up_edits(tmp_path):
    pico = _write(tmp_path / "pico.toml", {"ui": {"theme": "pastel"}})
    config = Config(config_path=pico, state_path=tmp_path / "state.toml")
    assert config.ui_theme == "pastel"

    _write(pico, {"ui": {"theme": "terminal"}})
    assert config.reload() == []
    assert config.ui_theme == "terminal"
