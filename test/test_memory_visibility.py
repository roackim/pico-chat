import asyncio

from pico_chat.harness.harness import Harness
from pico_chat.harness.llm_status import AgentState
from pico_chat.ui.commands import StatusCommand


class _NoopDebugStream:
    def log(self, *args, **kwargs):
        pass


class _FakeServer:
    def __init__(self):
        self._cached_context_window = 32768

    async def get_model_name(self):
        return "test-model"

    async def get_context_window(self):
        return 32768


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


def test_get_current_context_includes_explicit_empty_memory_block():
    harness = _build_harness_stub()

    context = asyncio.run(harness.get_current_context())

    assert context[0]["role"] == "system"
    assert "MEMORY:[]" in context[0]["content"]


def test_status_format_displays_memory_empty():
    status = {
        "online": True,
        "server_name": "llamacpp",
        "server_type": "llamacpp",
        "base_url": "http://localhost:8080/v1",
        "model": "test-model",
        "context_window": "32k",
        "context_used": 1200,
        "context_max": 32768,
        "context_percentage": 3.7,
        "memory_items": 0,
        "memory_tokens": 0,
    }

    rendered = StatusCommand.format_status(status)
    assert "Memory           : " in rendered
    assert "empty" in rendered
