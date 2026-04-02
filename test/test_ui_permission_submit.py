"""Tests for input submission behavior during tool permission prompts."""

from pico_chat.ui.app import chatTUI
from pico_chat.ui.tui.msg_types import SysMsg


class _StubAgent:
    def list_files_and_folders(self):
        return []


class TestPermissionPendingSubmit:
    def test_regular_message_blocked_while_permission_pending(self):
        ui = chatTUI(_StubAgent())
        ui.pending_permission_prompt = "Allow running command: rm -rf /?"

        ui.on_user_submit("thanks")

        assert ui.message_queue.qsize() == 0
        assert ui.command_queue.qsize() == 0
        assert len(ui.chat_history_panel.messages) == 1

        last_msg = ui.chat_history_panel.messages[-1]
        assert isinstance(last_msg.type, SysMsg)
        assert "Permission required for pending tool call" in last_msg.base_text

    def test_command_allowed_while_permission_pending(self):
        ui = chatTUI(_StubAgent())
        ui.pending_permission_prompt = "Allow reading file: secret.txt?"

        ui.on_user_submit("/status")

        assert ui.command_queue.qsize() == 1
        assert ui.command_queue.get_nowait() == "/status"
        assert ui.message_queue.qsize() == 0
