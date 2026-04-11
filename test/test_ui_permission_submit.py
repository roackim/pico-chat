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


class TestCommandMenuNavigation:
    def test_up_arrow_stays_in_command_menu(self):
        ui = chatTUI(_StubAgent())
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

        handled = ui.handle_global_input('\x1b[A')

        assert handled is True
        assert ui._last_focus_id == "input"
        assert ui.chat_history_panel.focused_message_index is None
        assert ui.input_component.command_completion.menu.selected_index != selected_before
