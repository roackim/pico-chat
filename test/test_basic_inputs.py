from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components.input import BoxInput, LineInput
from pico_chat.ui.tui.events import KeyEvent, PasteEvent, TickEvent, normalize_key
from pico_chat.ui.tui.components.input.input_handlers import InputContext, KeyboardHandler
from pico_chat.ui.tui.components.input.text_buffer import TextBuffer
from pico_chat.ui.tui.components.input.coordinate_mapper import CoordinateMapper
from pico_chat.ui.tui.components.input.scroll_manager import ScrollManager


def test_line_input_edits_and_renders_cursor():
    field = LineInput("ab")
    field.set_layout(1, 1, 8, 1)
    field.set_focused(True)
    field.handle_input(normalize_key("\x1b[D"))
    field.handle_input(normalize_key("X"))

    assert field.get_value() == "aXb"
    assert field.cursor_pos == 2
    buffer = Buffer(12, 3)
    field.render(buffer)
    assert buffer.cells[1][3].char == "b"
    assert buffer.cells[1][3].reverse


def test_box_input_handles_multiline_cursor_and_rendering():
    field = BoxInput("one")
    field.set_layout(1, 1, 10, 3)
    field.set_focused(True)
    field.handle_input(normalize_key("\r"))
    field.handle_input(normalize_key("t"))

    assert field.get_value() == "\ntone"
    buffer = Buffer(14, 6)
    field.render(buffer)
    assert buffer.cells[2][1].char == "t"


def test_box_input_wraps_long_lines_and_renders_cursor():
    field = BoxInput("hello world")
    field.set_layout(1, 1, 6, 2)
    field.set_focused(True)
    field.cursor_row = 0
    field.cursor_col = len(field.value)

    buffer = Buffer(8, 4)
    field.render(buffer)

    assert "".join(cell.char for cell in buffer.cells[1][1:7]) == "hello "
    assert "".join(cell.char for cell in buffer.cells[2][1:7]) == "world "
    assert buffer.cells[2][6].reverse


def test_box_input_supports_home_end_and_delete():
    field = BoxInput("abc\ndef")
    field.cursor_row = 0
    field.cursor_col = 1

    assert field.handle_input(normalize_key("\x1b[F"))
    assert field.cursor_col == 3
    assert field.handle_input(normalize_key("\x1b[3~"))
    assert field.get_value() == "abcdef"
    assert field.handle_input(normalize_key("\x1b[H"))
    assert field.handle_input(normalize_key("\x1b[3~"))
    assert field.get_value() == "bcdef"


def test_box_input_clears_cells_after_multiline_content_shrinks():
    field = BoxInput("long line\nold second line")
    field.set_layout(0, 0, 20, 2)
    buffer = Buffer(20, 2)
    field.render(buffer)

    field.set_value("new\n")
    field.render(buffer)

    assert "".join(cell.char for cell in buffer.cells[0]) == "new" + " " * 17
    assert "".join(cell.char for cell in buffer.cells[1]) == " " * 20


def test_line_input_supports_word_editing_and_paste():
    field = LineInput("hello brave world")
    field.cursor_pos = len(field.value)

    assert field.handle_input(KeyEvent("\x17"))
    assert field.get_value() == "hello brave "
    assert field.handle_input(PasteEvent("new\r\ntext"))
    assert field.get_value() == "hello brave new\ntext"
    assert field.cursor_pos == len(field.value)


def test_box_input_supports_word_editing_and_multiline_paste():
    field = BoxInput("hello world")
    field.cursor_col = len(field.value)

    assert field.handle_input(KeyEvent("\x17"))
    assert field.get_value() == "hello "
    assert field.handle_input(PasteEvent("new\r\ntext"))
    assert field.get_value() == "hello new\ntext"
    assert (field.cursor_row, field.cursor_col) == (1, 4)


def test_basic_inputs_use_typed_key_metadata():
    line = LineInput("ab")
    line.handle_input(KeyEvent("\x1b[D", text=None))
    line.handle_input(KeyEvent("ignored", text="X"))

    box = BoxInput("ab")
    box.handle_input(KeyEvent("ignored", text="X"))

    assert line.get_value() == "aXb"
    assert box.get_value() == "Xab"


def test_input_tick_invalidates_cursor_blink():
    field = LineInput("x")
    field.set_layout(0, 0, 4, 1)
    field.set_focused(True)
    field.clear_dirty()
    field._blink._last_input = 0
    field._blink._last_blink = 0

    assert field.handle_input(TickEvent(0))
    assert field.is_dirty()


def test_keyboard_handler_uses_typed_printable_text_metadata():
    buffer = TextBuffer()
    context = InputContext(
        buffer,
        CoordinateMapper("> ", 20),
        ScrollManager(buffer, CoordinateMapper("> ", 20), lambda: 3),
    )

    assert KeyboardHandler().handle(KeyEvent("ignored", text="X"), context)
    assert buffer.text == "X"