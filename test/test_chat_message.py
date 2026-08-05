import json

from pico_chat.ui.chat_message import Message
from pico_chat.ui.tui.msg_types import AskPermissionMsg, ToolCallMsg


def test_focusing_compact_single_line_message_invalidates_height_cache():
    message = Message("tool", msg_type=ToolCallMsg(), max_width=40)
    component = message.get_component()

    assert component.get_preferred_height(40) == 1

    message.set_focused(True)

    assert message.layout_revision == 1
    assert component.get_preferred_height(40) == 3


def test_permission_message_stays_boxed_when_unfocused():
    message = Message("permission", msg_type=AskPermissionMsg(), max_width=40)

    assert message.box.compact_when_unfocused is False
    assert message.box.get_preferred_height(40) > 1


def test_permission_message_shows_full_command():
    command = "printf " + "x" * 120
    message = Message("", msg_type=AskPermissionMsg(), max_width=40)
    message.tool_name = "run"
    message.tool_args = json.dumps({"command": command})
    message.rebuild_tool_display()

    assert command in message.base_text