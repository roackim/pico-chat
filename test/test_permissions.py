"""Tests for the tool approval gate and the harness permission flow.

The engine is gone: a role maps each tool to ``no`` / ``ask`` / ``yes`` and the
gate turns that into ``deny`` / ``ask`` / ``allow``.  These tests cover the
gate, the prompt text, and the ask/deny/allow paths through the harness.
"""
import json

import pytest

from pico_chat.harness import events as harness_events
from pico_chat.harness.harness import Harness
from pico_chat.harness.llm_status import AgentState
from pico_chat.harness.permissions import PermissionGate
from pico_chat.harness.roles import Role

from conftest import NoopDebugStream, StubReadTool, run_harness_tool_call


def test_run_permission_prompt_preserves_full_command():
    command = "printf " + "x" * 120

    prompt = PermissionGate.build_prompt("run", {"command": command})

    assert command in prompt


def test_gate_denies_disabled_and_unknown_tools():
    gate = PermissionGate(role=Role(name="r", tools={"read": "yes"}))

    assert gate.check("read", {}) == "allow"
    assert gate.check("write", {}) == "deny"
    assert gate.check("run", {"command": "ls"}) == "deny"


def test_gate_returns_ask_for_ask_tools():
    gate = PermissionGate(role=Role(name="r", tools={
        "subagent": "ask", "wait_for_subagents": "ask"}))

    assert gate.check("subagent", {}) == "ask"
    assert gate.check("wait_for_subagents", {}) == "ask"


def test_true_role_change_history_replaces_consecutive_notices():
    harness = Harness.__new__(Harness)
    harness.history = []

    harness._record_role_change("agent", "chat")
    harness._record_role_change("chat", "agent")

    assert len(harness.history) == 1
    assert harness.history[0]["content"] == "[Role changed from chat to agent]"


def test_role_change_history_preserves_notice_after_other_messages():
    harness = Harness.__new__(Harness)
    harness.history = []

    harness._record_role_change("agent", "chat")
    harness._add_message_to_history("user", "hello")
    harness._record_role_change("chat", "agent")

    assert len(harness.history) == 3
    assert harness.history[-1]["content"] == "[Role changed from chat to agent]"


def _build_harness_stub(tmp_path, read_tool, role):
    harness = Harness.__new__(Harness)
    harness.debug_stream = NoopDebugStream()
    harness.state = AgentState.IDLE
    harness.history = []
    harness.workspace = str(tmp_path)
    harness.tools_map = {"read": read_tool}
    harness._permission_gate = PermissionGate(role=role)
    return harness


def _read_call(call_id="call_1"):
    return {
        "id": call_id,
        "function": {
            "name": "read",
            "arguments": json.dumps({"path": "test.txt"}),
        },
    }


class TestHarnessReadPermissionFlow:
    """The ask/allow/deny paths through ``_execute_tool_calls``."""

    def test_auto_deny_enforced_before_execution(self, tmp_path):
        role = Role(name="r", tools={"read": "no"})
        read_tool = StubReadTool("content")
        harness = _build_harness_stub(tmp_path, read_tool, role)

        events, messages = run_harness_tool_call(harness, _read_call())

        assert isinstance(events[0], harness_events.PermissionRequest)
        assert isinstance(events[1], harness_events.ToolResult)
        assert events[0].auto is True
        assert events[1].outcome == "denied"
        assert events[1].output == "Auto-denied by security policy"
        assert read_tool.called is False
        denial_content = messages[-1]["content"]
        assert "[TOOL DENIED]" in denial_content

    def test_user_deny_enforced_for_ask(self, tmp_path):
        role = Role(name="r", tools={"read": "ask"})
        read_tool = StubReadTool("content")
        harness = _build_harness_stub(tmp_path, read_tool, role)
        harness.set_user_response("no")

        events, messages = run_harness_tool_call(harness, _read_call("call_2"))

        assert events[0].auto is False
        assert events[1].outcome == "denied"
        assert events[1].output == "User denied"
        assert read_tool.called is False

    def test_allow_executes_tool(self, tmp_path):
        role = Role(name="r", tools={"read": "yes"})
        read_tool = StubReadTool("stubbed content")
        harness = _build_harness_stub(tmp_path, read_tool, role)

        events, messages = run_harness_tool_call(harness, _read_call("call_3"))

        assert events[0].auto is True
        assert isinstance(events[-1], harness_events.ToolResult)
        assert events[-1].outcome == "completed"
        assert read_tool.called is True
        assert events[-1].output == "stubbed content"
        assert messages[-1]["content"] == "stubbed content"


class TestFileToolLayer:
    """The tool layer no longer enforces permissions; the gate does."""

    def test_read_supports_line_ranges_and_line_numbers(self, tmp_path):
        (tmp_path / "test.txt").write_text("one\ntwo\nthree\nfour\n")
        from pico_chat.harness.tools import MinimalToolset

        tools = MinimalToolset(tmp_path)

        assert tools.read("test.txt", offset=1, limit=2) == "two\nthree\n"
        assert tools.read("test.txt", offset=1, limit=2, include_line_numbers=True) == (
            "     2\ttwo\n     3\tthree\n"
        )

    def test_read_rejects_invalid_offset(self, tmp_path):
        from pico_chat.harness.tools import MinimalToolset, ToolError

        (tmp_path / "test.txt").write_text("content")
        tools = MinimalToolset(tmp_path)

        with pytest.raises(ToolError, match="Invalid offset"):
            tools.read("test.txt", offset=-1)

    def test_read_marks_character_truncation(self, tmp_path):
        from pico_chat.harness.tools import MinimalToolset

        (tmp_path / "test.txt").write_text("abcdefgh")
        tools = MinimalToolset(tmp_path)

        result = tools.read("test.txt", max_chars=3)
        assert result.startswith("abc\n[truncated:")

    def test_write_and_run_work_without_a_profile(self, tmp_path):
        from pico_chat.harness.tools import MinimalToolset

        tools = MinimalToolset(tmp_path)

        assert "[OK]" in tools.write("output.txt", "data")
        assert (tmp_path / "output.txt").read_text() == "data"
        assert "hello" in tools.run("echo hello")
