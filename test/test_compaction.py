import asyncio

from pico_chat.harness.harness import Harness, COMPACTION_MARKER_PREFIX
from pico_chat.harness.llm_status import AgentState


class _NoopDebugStream:
    def log(self, *args, **kwargs):
        pass


class _FakeServer:
    def __init__(self):
        self.last_messages = None

    async def get_model_name(self):
        return "test-model"

    async def get_context_window(self):
        return 32768

    async def create_completion(self, messages, tools=None, stream=True):
        self.last_messages = messages

        class _Msg:
            content = "Decisions: keep latest thread.\nOpen Tasks: continue implementation."

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        yield _Resp()


def _build_harness_stub():
    harness = Harness.__new__(Harness)
    harness.debug_stream = _NoopDebugStream()
    harness.state = AgentState.IDLE
    harness.history = []
    harness.memory = {}
    harness.memory_snapshots = {}
    harness.workspace = "."
    harness.project_context = "Project Root: .\nFiles:"
    harness.server = _FakeServer()
    return harness


def test_effective_history_starts_from_last_compaction_marker():
    harness = _build_harness_stub()
    harness.history = [
        {"id": "u1", "role": "user", "content": "first"},
        {"id": "a1", "role": "assistant", "content": "first answer"},
        {"id": "c1", "role": "assistant", "content": f"{COMPACTION_MARKER_PREFIX}\nsummary"},
        {"id": "u2", "role": "user", "content": "second"},
    ]

    effective = harness._get_effective_history()

    assert [m["id"] for m in effective] == ["c1", "u2"]


def test_compact_history_inserts_new_marker_and_becomes_effective_start():
    harness = _build_harness_stub()
    harness.history = [
        {"id": "u1", "role": "user", "content": "first"},
        {"id": "a1", "role": "assistant", "content": "first answer"},
    ]

    result = asyncio.run(harness.compact_history())

    assert result["ok"] is True
    assert result["compacted_messages"] == 2
    assert harness.history[-1]["role"] == "assistant"
    assert harness.history[-1]["content"].startswith(COMPACTION_MARKER_PREFIX)

    effective = harness._get_effective_history()
    assert len(effective) == 1
    assert effective[0]["id"] == result["message_id"]


def test_deleting_compaction_marker_restores_full_history_behavior():
    harness = _build_harness_stub()
    harness.history = [
        {"id": "u1", "role": "user", "content": "first"},
        {"id": "c1", "role": "assistant", "content": f"{COMPACTION_MARKER_PREFIX}\nsummary"},
        {"id": "u2", "role": "user", "content": "second"},
    ]

    # Simulate user deleting the compaction message from history.
    harness.history = [msg for msg in harness.history if msg["id"] != "c1"]

    effective = harness._get_effective_history()

    assert [m["id"] for m in effective] == ["u1", "u2"]


def test_compact_history_summary_call_has_single_system_message_first():
    harness = _build_harness_stub()
    harness.history = [
        {"id": "u1", "role": "user", "content": "first"},
        {"id": "a1", "role": "assistant", "content": "first answer"},
    ]

    asyncio.run(harness.compact_history())

    roles = [m["role"] for m in harness.server.last_messages]
    assert roles[0] == "system"
    assert roles.count("system") == 1
