import asyncio
import json

from pico_chat.harness.roles import Role
from pico_chat.ui.commands.builtins import ConversationExportCommand, ConversationImportCommand


class FakeAgent:
    def __init__(self):
        self.role = Role("default")
        self.history = [{"role": "user", "content": "hello"}]

    def set_role(self, role):
        self.role = role


class FakeRuntime:
    def __init__(self):
        self.agent = FakeAgent()
        self.current_generation_task = None

    @property
    def is_generating(self):
        return False

    def ensure_agent(self):
        return self.agent

    def switch_role(self, role):
        self.agent.set_role(role)
        return role


class FakePanel:
    def __init__(self):
        self.messages = []

    def add_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    def clear(self):
        self.messages.clear()


class FakeUI:
    def __init__(self):
        self.runtime = FakeRuntime()
        self.chat_history_panel = FakePanel()

    @property
    def agent(self):
        return self.runtime.agent

    def _active_runtime(self):
        return self.runtime


def test_conversation_export_includes_active_role(tmp_path):
    ui = FakeUI()
    filename = tmp_path / "conversation.json"

    asyncio.run(ConversationExportCommand().execute(ui, [str(filename)]))

    exported = json.loads(filename.read_text())
    assert exported["role"] == "default"
    assert exported["history"] == ui.agent.history


def test_conversation_import_restores_role_before_history_replay(tmp_path, monkeypatch):
    ui = FakeUI()
    filename = tmp_path / "conversation.json"
    history = [{"role": "user", "content": "imported"}]
    filename.write_text(json.dumps({"role": "reviewer", "history": history}))
    monkeypatch.setattr(
        "pico_chat.harness.roles.load_role",
        lambda name: Role(name),
    )

    command = ConversationImportCommand()
    command._rebuild_ui_from_history = lambda ui, history: setattr(
        ui, "replayed_role", ui.agent.role.name
    )
    asyncio.run(command.execute(ui, [str(filename)]))

    assert ui.agent.role.name == "reviewer"
    assert ui.agent.history == history
    assert ui.replayed_role == "reviewer"


def test_conversation_import_accepts_legacy_history_array(tmp_path):
    ui = FakeUI()
    filename = tmp_path / "legacy.json"
    history = [{"role": "user", "content": "legacy"}]
    filename.write_text(json.dumps(history))

    command = ConversationImportCommand()
    command._rebuild_ui_from_history = lambda ui, history: None
    asyncio.run(command.execute(ui, [str(filename)]))

    assert ui.agent.history == history
    assert ui.agent.role.name == "default"


def test_conversation_import_rejects_malformed_envelope(tmp_path):
    ui = FakeUI()
    filename = tmp_path / "malformed.json"
    filename.write_text(json.dumps({"role": "reviewer", "history": [{"content": "missing role"}]}))

    command = ConversationImportCommand()
    asyncio.run(command.execute(ui, [str(filename)]))

    assert "missing 'role'" in ui.chat_history_panel.messages[-1][0][0]


def test_conversation_import_rejects_non_string_role(tmp_path):
    ui = FakeUI()
    filename = tmp_path / "bad-role.json"
    filename.write_text(json.dumps({"role": 42, "history": []}))

    asyncio.run(ConversationImportCommand().execute(ui, [str(filename)]))

    assert "role must be a string" in ui.chat_history_panel.messages[-1][0][0]


def test_conversation_import_rejects_invalid_json(tmp_path):
    ui = FakeUI()
    filename = tmp_path / "invalid.json"
    filename.write_text("not json")

    asyncio.run(ConversationImportCommand().execute(ui, [str(filename)]))

    assert "Invalid JSON file" in ui.chat_history_panel.messages[-1][0][0]
