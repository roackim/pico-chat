"""Tests for the file-based config commands and the external editor helper."""

import asyncio
from pathlib import Path

import pytest

from pico_chat.ui.external_editor import edit_file, resolve_editor
from pico_chat.ui.commands.core import ConfigCommand, EditCommand, ReloadCommand


class _Panel:
    def __init__(self):
        self.messages = []

    def add_message(self, text, msg_type=None, title=None):
        self.messages.append(text)


class _Terminal:
    def __init__(self):
        self.suspended = 0
        self.resumed = 0

    def suspend(self):
        self.suspended += 1

    def resume(self):
        self.resumed += 1


class _Compositor:
    def __init__(self):
        self.terminal = _Terminal()


class _UI:
    def __init__(self):
        self.chat_history_panel = _Panel()
        self.compositor = _Compositor()
        self.refreshed = 0

    def refresh_status_bar(self):
        self.refreshed += 1


def test_resolve_editor_prefers_visual_then_editor(monkeypatch):
    monkeypatch.setenv("VISUAL", "my-editor --wait")
    monkeypatch.delenv("EDITOR", raising=False)
    assert resolve_editor() == ["my-editor", "--wait"]

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "nano")
    assert resolve_editor() == ["nano"]


def test_edit_file_invokes_editor(monkeypatch, tmp_path):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "my-editor")
    calls = []
    monkeypatch.setattr("subprocess.call", lambda cmd: calls.append(cmd) or 0)

    assert edit_file(tmp_path / "pico.toml") is True
    assert calls == [["my-editor", str(tmp_path / "pico.toml")]]


def test_config_command_opens_editor_and_reloads(monkeypatch, tmp_path):
    import pico_chat.pico_cfg as cfg_mod

    monkeypatch.setattr(cfg_mod, "get_config_path", lambda: tmp_path / "pico.toml")
    monkeypatch.setattr(cfg_mod, "get_state_path", lambda: tmp_path / "state.toml")
    monkeypatch.setenv("EDITOR", "my-editor")
    ui = _UI()

    opened = []

    def _fake_open(_ui, path):
        opened.append(Path(path))
        return True

    monkeypatch.setattr("pico_chat.ui.external_editor.open_editor", _fake_open)

    asyncio.run(ConfigCommand().execute(ui, []))

    assert opened == [tmp_path / "pico.toml"]
    assert (tmp_path / "pico.toml").exists()
    assert any("Config reloaded" in m for m in ui.chat_history_panel.messages)


def test_config_command_without_editor_reports_error(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr("pico_chat.ui.external_editor.shutil.which", lambda _name: None)
    ui = _UI()

    asyncio.run(ConfigCommand().execute(ui, []))

    assert any("No editor" in m for m in ui.chat_history_panel.messages)


def test_edit_command_opens_requested_file(monkeypatch, tmp_path):
    monkeypatch.setenv("EDITOR", "my-editor")
    ui = _UI()
    opened = []
    monkeypatch.setattr(
        "pico_chat.ui.external_editor.open_editor",
        lambda _ui, path: opened.append(Path(path)) or True,
    )

    target = tmp_path / "notes.txt"
    asyncio.run(EditCommand().execute(ui, [str(target)]))

    assert opened == [target]


def test_reload_command_success(monkeypatch, tmp_path):
    import pico_chat.pico_cfg as cfg_mod

    monkeypatch.setattr(cfg_mod, "get_config_path", lambda: tmp_path / "pico.toml")
    monkeypatch.setattr(cfg_mod, "get_state_path", lambda: tmp_path / "state.toml")
    ui = _UI()

    asyncio.run(ReloadCommand().execute(ui, []))

    assert any("Config reloaded" in m for m in ui.chat_history_panel.messages)
    assert ui.refreshed == 1
