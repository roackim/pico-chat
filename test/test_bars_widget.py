from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components.bars import ActionBar, ActionItem, StatusBar
from pico_chat.ui.tui.terminal import MouseEvent


def row_text(buffer):
    return "".join(cell.char for cell in buffer.cells[0])


def test_status_bar_renders_left_and_right_text_with_padding():
    status = StatusBar("ready", "100%")
    status.set_layout(0, 0, 20, 1)
    buffer = Buffer(20, 1)

    status.render(buffer)

    rendered = row_text(buffer)
    assert rendered.startswith(" ready")
    assert rendered.endswith("100% ")


def test_action_bar_activates_by_key_and_mouse():
    activated = []
    bar = ActionBar([
        ActionItem("q", "quit", lambda: activated.append("quit")),
        ActionItem("s", "save", lambda: activated.append("save")),
    ])
    bar.set_layout(0, 0, 20, 1)
    buffer = Buffer(20, 1)
    bar.render(buffer)

    assert bar.handle_input("s")
    assert bar.handle_input(MouseEvent(3, 0, 0, True))
    assert activated == ["save", "quit"]


def test_action_bar_focus_uses_shared_style_and_disabled_ignores_input():
    activated = []
    bar = ActionBar([ActionItem("x", "close", lambda: activated.append(True))])
    bar.set_layout(0, 0, 12, 1)
    bar.set_focused(True)
    buffer = Buffer(12, 1)
    bar.render(buffer)

    assert all(cell.reverse for cell in buffer.cells[0][1:9])
    bar.enabled = False
    assert bar.handle_input("x") is False
    assert activated == []