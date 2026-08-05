from pico_chat.ui.chat_message import Message
from pico_chat.ui.tui.msg_types import ToolCallMsg


def test_focusing_compact_single_line_message_invalidates_height_cache():
    message = Message("tool", msg_type=ToolCallMsg(), max_width=40)
    component = message.get_component()

    assert component.get_preferred_height(40) == 1

    message.set_focused(True)

    assert message.layout_revision == 1
    assert component.get_preferred_height(40) == 3