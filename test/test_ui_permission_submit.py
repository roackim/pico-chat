"""Tests for input submission behavior during tool permission prompts."""

import asyncio
import pytest
import pico_chat.ui.app as app_module
from pico_chat.ui.app import chatTUI
from pico_chat.ui.tui.events import normalize_key
from pico_chat.ui.tui.msg_types import SysMsg
from pico_chat.harness import chunks

from conftest import StubAgent, make_chunk_stream


class TestPermissionPendingSubmit:
    def test_regular_message_blocked_while_permission_pending(self):
        ui = chatTUI(StubAgent())
        ui.pending_permission_prompt = "Allow running command: rm -rf /?"

        ui.on_user_submit("thanks")

        assert ui.message_queue.qsize() == 0
        assert ui.command_queue.qsize() == 0
        assert len(ui.chat_history_panel.messages) == 1

        last_msg = ui.chat_history_panel.messages[-1]
        assert isinstance(last_msg.type, SysMsg)
        assert "Permission required for pending tool call" in last_msg.base_text

    def test_command_allowed_while_permission_pending(self):
        ui = chatTUI(StubAgent())
        ui.pending_permission_prompt = "Allow reading file: secret.txt?"

        ui.on_user_submit("/status")

        assert ui.command_queue.qsize() == 1
        assert ui.command_queue.get_nowait() == "/status"
        assert ui.message_queue.qsize() == 0


class TestCommandMenuNavigation:
    def test_up_arrow_stays_in_command_menu(self):
        ui = chatTUI(StubAgent())
        ui.root = type("_Root", (), {"handle_input": lambda self, event: ui.input_component.handle_input(event)})()
        ui._original_handle_input = ui.root.handle_input

        ui.chat_history_panel.add_message("first")
        ui.chat_history_panel.add_message("second")
        ui.input_component.set_focused(True)
        ui.input_component.buffer.text = "/s"
        ui.input_component.buffer.cursor_pos = len("/s")
        ui.input_component._on_text_changed()
        ui._last_focus_id = "input"

        assert ui.input_component.command_completion is not None
        assert ui.input_component.command_completion.is_active is True

        selected_before = ui.input_component.command_completion.menu.selected_index

        handled = ui.handle_global_input(normalize_key('\x1b[A'))

        assert handled is True
        assert ui._last_focus_id == "input"
        assert ui.chat_history_panel.focused_message_index is None
        assert ui.input_component.command_completion.menu.selected_index != selected_before


class TestCommandWorker:
    def test_command_worker_dispatches_queued_commands(self, monkeypatch):
        ui = chatTUI(StubAgent())
        dispatched = []

        async def fake_handle_command(_ui, command):
            dispatched.append(command)
            ui.shutdown_event.set()

        monkeypatch.setattr(app_module, "handle_command", fake_handle_command)
        ui.on_command_submit("/status")
        asyncio.run(ui.command_worker())

        assert dispatched == ["/status"]


class TestPendingPermissionPromptClearing:
    """Regression tests: pending_permission_prompt must be cleared by incoming chunks,
    not only by explicit allow/deny key presses. Without the fix, auto-denied tool calls
    left pending_permission_prompt set, blocking every subsequent user message."""

    def test_auto_denied_chunk_clears_pending_prompt(self):
        """DENIED chunk (auto-deny path) must clear pending_permission_prompt."""
        ui = chatTUI(StubAgent())
        ui.pending_permission_prompt = "Allow running: sudo rm -rf /?"

        denied_chunk = chunks.ToolStatusChange(
            tool_call_id="call_1",
            tool_name="run",
            tool_args='{"command": "sudo rm -rf /"}',
            status=chunks.ToolStatus.DENIED,
            auto_decision=True,
            denial_reason="Auto-denied by security policy",
        )

        async def _run():
            async for _ in ui._process_generation("hello", ui.chat_history_panel.add_message("hello")):
                pass

        # Patch agent.chat to yield the DENIED chunk then stop
        ui.agent.chat = lambda _: make_chunk_stream(denied_chunk)
        asyncio.run(ui._process_generation("hello", ui.chat_history_panel.add_message("hello")))

        assert ui.pending_permission_prompt is None, (
            "pending_permission_prompt must be cleared after a DENIED chunk arrives"
        )

    def test_auto_approved_chunk_clears_pending_prompt(self):
        """APPROVED chunk must clear pending_permission_prompt (covers auto-approve)."""
        ui = chatTUI(StubAgent())
        ui.pending_permission_prompt = "Allow reading: secrets.txt?"

        approved_chunk = chunks.ToolStatusChange(
            tool_call_id="call_2",
            tool_name="read",
            tool_args='{"path": "secrets.txt"}',
            status=chunks.ToolStatus.APPROVED,
            auto_decision=True,
        )

        ui.agent.chat = lambda _: make_chunk_stream(approved_chunk)
        asyncio.run(ui._process_generation("hello", ui.chat_history_panel.add_message("hello")))

        assert ui.pending_permission_prompt is None, (
            "pending_permission_prompt must be cleared after an APPROVED chunk arrives"
        )

    def test_message_not_blocked_after_auto_denial(self):
        """After auto-denial clears the flag, subsequent messages must not be blocked."""
        ui = chatTUI(StubAgent())
        ui.pending_permission_prompt = "Allow running: sudo rm -rf /?"

        denied_chunk = chunks.ToolStatusChange(
            tool_call_id="call_3",
            tool_name="run",
            tool_args='{"command": "sudo rm -rf /"}',
            status=chunks.ToolStatus.DENIED,
            auto_decision=True,
            denial_reason="Auto-denied by security policy",
        )

        ui.agent.chat = lambda _: make_chunk_stream(denied_chunk)
        asyncio.run(ui._process_generation("hello", ui.chat_history_panel.add_message("hello")))

        # Now submit a follow-up message – it must NOT be blocked
        ui.on_user_submit("what happened?")

        assert ui.message_queue.qsize() == 1, (
            "User message must be queued, not blocked, after pending_permission_prompt was cleared"
        )
