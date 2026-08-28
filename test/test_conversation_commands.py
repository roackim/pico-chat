import asyncio
import json
from types import SimpleNamespace

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
        msg = SimpleNamespace(
            text=args[0] if args else "",
            harness_message_ids=kwargs.get("harness_message_ids"),
            type=kwargs.get("msg_type"),
            tool_name=None, tool_args=None, tool_output=None,
            tool_status=None, show_output=True,
            rebuild_tool_display=lambda: None, finalize=lambda: None,
        )
        self.messages.append(msg)
        return msg

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


def test_conversation_import_defaults_role_when_missing(tmp_path, monkeypatch):
    ui = FakeUI()
    filename = tmp_path / "missing-role.json"
    history = [{"role": "user", "content": "imported"}]
    filename.write_text(json.dumps({"role": "ghost-role", "history": history}))

    def fake_load(name):
        if name == "ghost-role":
            raise KeyError(f"Role not found: {name}")
        return Role(name)

    monkeypatch.setattr("pico_chat.harness.roles.load_role", fake_load)

    command = ConversationImportCommand()
    command._rebuild_ui_from_history = lambda ui, history: None
    asyncio.run(command.execute(ui, [str(filename)]))

    # Defaulted to 'default' and warned in the chat.
    assert ui.agent.role.name == "default"
    assert ui.agent.history == history
    all_text = "\n".join(m.text for m in ui.chat_history_panel.messages)
    assert "ghost-role" in all_text
    assert "default" in all_text


def test_conversation_import_handles_tool_call_only_assistant(tmp_path):
    """Assistant messages with tool_calls and no content must not crash."""
    ui = FakeUI()
    filename = tmp_path / "toolcall.json"
    history = [
        {"role": "user", "content": "list files"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "function": {"name": "read", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ]
    filename.write_text(json.dumps({"role": "default", "history": history}))

    command = ConversationImportCommand()
    asyncio.run(command.execute(ui, [str(filename)]))

    assert ui.agent.history == history
    assert "Import failed" not in "\n".join(m.text for m in ui.chat_history_panel.messages)


def test_conversation_import_rejects_malformed_envelope(tmp_path):
    ui = FakeUI()
    filename = tmp_path / "malformed.json"
    filename.write_text(json.dumps({"role": "reviewer", "history": [{"content": "missing role"}]}))

    command = ConversationImportCommand()
    asyncio.run(command.execute(ui, [str(filename)]))

    assert "missing 'role'" in ui.chat_history_panel.messages[-1].text


def test_conversation_import_rejects_non_string_role(tmp_path):
    ui = FakeUI()
    filename = tmp_path / "bad-role.json"
    filename.write_text(json.dumps({"role": 42, "history": []}))

    asyncio.run(ConversationImportCommand().execute(ui, [str(filename)]))

    assert "role must be a string" in ui.chat_history_panel.messages[-1].text


def test_conversation_import_rejects_invalid_json(tmp_path):
    ui = FakeUI()
    filename = tmp_path / "invalid.json"
    filename.write_text("not json")

    asyncio.run(ConversationImportCommand().execute(ui, [str(filename)]))

    assert "Invalid JSON file" in ui.chat_history_panel.messages[-1].text
