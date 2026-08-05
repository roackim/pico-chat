from pico_chat.ui.tui.actions import Action, Actions
from pico_chat.ui.tui.components.form import TextAreaField, TextField, ToggleField
from pico_chat.ui.tui.components.form_popup import FormPopup
from pico_chat.ui.tui.navigation import ModalHost
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.events import KeyEvent, MouseEvent, TickEvent
from pico_chat.ui.tui.focus import FocusScope


def test_form_popup_emits_cancel_and_preserves_callback():
    actions = []
    callbacks = []
    popup = FormPopup()
    popup.show("Form", [TextField("Name")], lambda values: callbacks.append(values),
               lambda: callbacks.append("cancel"), actions.append)

    assert popup.handle_input("\x1b")
    assert actions == [Action(Actions.CANCEL)]
    assert callbacks == ["cancel"]


def test_form_popup_enter_activates_toggle_without_submitting():
    actions = []
    callbacks = []
    popup = FormPopup()
    popup.show("Form", [ToggleField("Enabled", value=True)], callbacks.append,
               on_action=actions.append)

    assert popup.handle_input("\r")
    assert actions == []
    assert callbacks == []


def test_invalid_form_does_not_emit_submit():
    actions = []
    callbacks = []
    popup = FormPopup()
    popup.show("Form", [TextField("Name", required=True)], callbacks.append,
               on_action=actions.append)

    assert not popup._try_submit()
    assert actions == []
    assert callbacks == []


def test_text_field_enter_does_not_advance_or_submit():
    actions = []
    callbacks = []
    popup = FormPopup()
    popup.show("Form", [TextField("Name"), ToggleField("Enabled")], callbacks.append,
               on_action=actions.append)

    assert popup.handle_input("\r") is True
    assert actions == []
    assert callbacks == []


def test_typed_tab_moves_focus_to_next_field():
    first = TextField("First")
    second = TextField("Second")
    popup = FormPopup()
    popup.show("Form", [first, second], lambda values: None)

    assert popup.handle_input(KeyEvent("\t"))
    assert second.focused


def test_tab_marks_form_dirty_for_focus_repaint():
    first = TextField("First")
    second = TextField("Second")
    popup = FormPopup()
    popup.show("Form", [first, second], lambda values: None)
    popup._form_container.clear_dirty()

    assert popup.handle_input(KeyEvent("\t"))
    assert second.focused
    assert popup._form_container.is_dirty()


def test_textarea_enter_inserts_newline_without_submitting():
    submitted = []
    field = TextAreaField("Notes")
    popup = FormPopup()
    popup.show("Form", [field], submitted.append)

    assert popup.handle_input(KeyEvent("\r"))
    assert field.get_value() == "\n"
    assert submitted == []


def test_alt_enter_is_consumed_by_form_popup():
    submitted = []
    field = TextField("Name")
    popup = FormPopup()
    popup.show("Form", [field], submitted.append)

    assert popup.handle_input(KeyEvent("\x1b\r"))
    assert popup.is_visible
    assert submitted == []


def test_alt_enter_protocol_variants_are_consumed_by_form_popup():
    for sequence in ("\x1b\n", "\x1b[13;3u", "\x1b[27;3;13~"):
        submitted = []
        popup = FormPopup()
        popup.show("Form", [TextField("Name")], submitted.append)

        assert popup.handle_input(KeyEvent(sequence))
        assert popup.is_visible
        assert submitted == []


def test_form_popup_forwards_ticks_to_focused_input():
    field = TextField("Name")
    popup = FormPopup()
    popup.show("Form", [field], lambda values: None)
    field._editor._blink._last_input = 0
    field._editor._blink._last_blink = 0
    popup._form_container.clear_dirty()

    assert popup.handle_input(TickEvent(0))
    assert popup._form_container.is_dirty()


class FakeCompositor:
    width = 80
    height = 24

    def add_overlay(self, component):
        pass

    def remove_overlay(self, component):
        pass

    def request_render(self):
        pass


class FocusCompositor(FakeCompositor):
    def __init__(self, focus_scope):
        self.event_router = type("Router", (), {"focus_scope": focus_scope})()


def test_form_popup_suspends_and_restores_background_focus():
    background = TextField("Background")
    scope = FocusScope([background])
    scope.enter()
    popup = FormPopup(FocusCompositor(scope))

    popup.show("Form", [TextField("Name")], lambda values: None)
    assert scope.focused is None
    assert not background.focused

    popup.hide()
    assert scope.focused is background
    assert background.focused


def test_form_action_bar_mouse_and_keyboard_emit_same_cancel_action():
    mouse_actions = []
    keyboard_actions = []
    mouse_popup = FormPopup(FakeCompositor())
    mouse_popup.show("Form", [TextField("Name")], lambda values: None,
                     on_action=mouse_actions.append)
    mouse_popup.render(Buffer(80, 24))
    cancel_region = next(region for region in mouse_popup._box._action_hit_regions
                         if region[2].key == "Esc")
    start, _, _ = cancel_region
    assert mouse_popup.handle_input(MouseEvent(
        mouse_popup.x + start, mouse_popup.y + mouse_popup.height - 1,
        0, True,
    ))

    keyboard_popup = FormPopup()
    keyboard_popup.show("Form", [TextField("Name")], lambda values: None,
                        on_action=keyboard_actions.append)
    assert keyboard_popup.handle_input("\x1b")
    assert mouse_actions == keyboard_actions == [Action(Actions.CANCEL)]


def test_form_popup_can_be_owned_by_modal_host():
    compositor = FakeCompositor()
    host = ModalHost(compositor)
    popup = FormPopup(modal_host=host)

    popup.show("Form", [TextField("Name")], lambda values: None)
    assert host.current is popup
    assert host._current_screen is popup._modal_screen

    popup.hide()
    assert host.current is None
    assert host._current_screen is None