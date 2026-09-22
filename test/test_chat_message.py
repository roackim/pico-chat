from pico_chat.ui.chat_message import Message
from pico_chat.ui.tui.msg_types import ToolCallMsg


def test_focusing_compact_single_line_message_invalidates_height_cache():
    message = Message("tool", msg_type=ToolCallMsg(), max_width=40)
    component = message.get_component()

    # In thread mode there are no borders. Unfocused, a single-line message is
    # one row tall.
    assert component.get_preferred_height(40) == 1

    message.set_focused(True)

    assert message.layout_revision == 1
    # Actions are no longer rendered inline (the app shows them in the mode
    # line), so focusing does not change the message height.
    assert component.get_preferred_height(40) == 1


def test_thread_mode_uses_role_gutter():
    from pico_chat.ui.tui.msg_types import UserMsg, PicoMsg

    user = Message("hi", msg_type=UserMsg(), max_width=40)
    pico = Message("hello", msg_type=PicoMsg(), max_width=40)

    assert user.box.thread_mode is True
    assert user.box.gutter == "▌"
    assert pico.box.gutter == "▌"


def test_user_message_content_is_normal_but_gutter_is_user_colored():
    """User message text is normal color; the prefix bar keeps the USER color."""
    from pico_chat.ui.tui.msg_types import UserMsg
    from pico_chat.ui.tui.colors import theme

    msg = Message("hello", msg_type=UserMsg(), max_width=40)
    assert msg.component.fg == theme.DEFAULT  # normal text color
    assert msg.box.gutter_color == theme.USER


def test_pico_message_gutter_is_gray():
    from pico_chat.ui.tui.msg_types import PicoMsg
    from pico_chat.ui.tui.colors import theme

    msg = Message("hello", msg_type=PicoMsg(), max_width=40)
    assert msg.box.gutter_color == theme.MUTED


def test_append_strips_leading_whitespace_on_first_chunk():
    """Streamed assistant content often opens with a space; drop it once."""
    from pico_chat.ui.tui.msg_types import PicoMsg

    msg = Message("", msg_type=PicoMsg(), max_width=40, render_markdown=True)
    msg.append(" Hello.")
    assert msg.base_text == "Hello."

    msg.append(" More text.")
    assert msg.base_text == "Hello. More text."


def test_thinking_message_is_collapsible():
    from pico_chat.ui.tui.msg_types import ThinkingMsg

    msg = Message("deep reasoning", msg_type=ThinkingMsg(), max_width=40)

    assert msg.collapsible is True
    assert msg.collapsed is False

    msg.set_collapsed(True)
    assert msg.collapsed is True
    # Collapsed messages render a single row.
    assert msg.get_component().get_preferred_height(40) == 1


def test_thinking_spinner_animates_while_streaming():
    from pico_chat.ui.tui.buffer import Buffer
    from pico_chat.ui.tui.msg_types import ThinkingMsg

    msg = Message("deep reasoning", msg_type=ThinkingMsg(), max_width=40)
    msg.set_collapsed(True)
    box = msg.get_component()
    box.set_layout(0, 0, 40, 1)

    def row():
        buf = Buffer(40, 1)
        box.render(buf)
        return "".join(c.char for c in buf.cells[0])

    first = row()
    assert "⠋" in first  # spinner frame 0

    msg.advance_spinner()
    second = row()
    assert "⠙" in second  # spinner frame 1
    assert second != first

    # Once finalized, the spinner is replaced by a done marker + "thoughts".
    msg.finalize()
    finalized = row()
    assert "⠋" not in finalized
    assert "⠙" not in finalized
    assert "✓" in finalized
    assert "thoughts" in finalized


def test_thinking_done_glyph_and_label():
    from pico_chat.ui.tui.msg_types import ThinkingMsg

    msg = Message("deep reasoning", msg_type=ThinkingMsg(), max_width=40)
    msg.finalize()
    glyph, color = msg.done_glyph()
    assert glyph == "✓"
    assert msg.done_label("thinking") == "thoughts"


def _render_rows(msg, width, height):
    from pico_chat.ui.tui.buffer import Buffer

    box = msg.get_component()
    box.set_layout(0, 0, width, height)
    buf = Buffer(width, height)
    box.render(buf)
    return ["".join(c.char for c in row) for row in buf.cells]


def test_thread_render_smoke_text_message():
    """Thread-mode render draws the gutter and the content (regression guard)."""
    from pico_chat.ui.tui.msg_types import PicoMsg

    msg = Message("hello world", msg_type=PicoMsg(), max_width=20)
    msg.finalize()
    rows = _render_rows(msg, 20, 4)

    joined = "\n".join(rows)
    assert "hello world" in joined
    assert "▌" in joined


def test_thread_render_smoke_markdown_message():
    from pico_chat.ui.tui.msg_types import UserMsg

    msg = Message("a **bold** line", msg_type=UserMsg(), max_width=24,
                  render_markdown=True)
    msg.finalize()
    rows = _render_rows(msg, 24, 4)

    joined = "\n".join(rows)
    assert "bold" in joined
    assert "▌" in joined