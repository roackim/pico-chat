"""Tests for Form fields, FormContainer, and FormPopup."""

import pytest
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components.form import (
    FormField, ToggleField, TextField, TextAreaField,
    CheckboxListField, RadioListField, ProfileListField, ProfileList,
    InlineChoiceField, FormContainer,
)
from pico_chat.ui.tui.input_result import InputResult
from pico_chat.ui.tui.events import MouseEvent
from pico_chat.ui.tui.components.form_popup import FormPopup


# ── ToggleField ────────────────────────────────────────────────

class TestToggleField:
    def test_default_off(self):
        f = ToggleField("Verbose")
        assert f.get_value() is False

    def test_default_on(self):
        f = ToggleField("Verbose", value=True)
        assert f.get_value() is True

    def test_toggle(self):
        f = ToggleField("Verbose")
        f.toggle()
        assert f.get_value() is True
        f.toggle()
        assert f.get_value() is False

    def test_set_value(self):
        f = ToggleField("Verbose")
        f.set_value(True)
        assert f.get_value() is True

    def test_space_toggles(self):
        f = ToggleField("Verbose")
        assert f.handle_input(" ") is True
        assert f.get_value() is True

    def test_enter_toggles(self):
        f = ToggleField("Verbose")
        assert f.handle_input("\r") is True
        assert f.get_value() is True

    def test_unrelated_input_ignored(self):
        f = ToggleField("Verbose")
        assert f.handle_input("x") is False
        assert f.get_value() is False

    def test_render(self):
        f = ToggleField("Verbose", value=True)
        buf = Buffer(40, 1)
        f.render(buf, 0, 0, 40, 1)
        # Unfocused: label on the left and checkbox on the right.
        assert buf.cells[0][0].char == "V"
        assert buf.cells[0][37].char == "["
        assert buf.cells[0][38].char == "x"
        assert buf.cells[0][39].char == "]"

    def test_render_focused(self):
        f = ToggleField("Verbose", value=True)
        f.focused = True
        buf = Buffer(40, 1)
        f.render(buf, 0, 0, 40, 1)
        # Focused: "▸ [x] Verbose"
        assert buf.cells[0][0].char == "▸"

    def test_render_off(self):
        f = ToggleField("Verbose", value=False)
        buf = Buffer(40, 1)
        f.render(buf, 0, 0, 40, 1)
        assert buf.cells[0][37].char == "["
        assert buf.cells[0][38].char == " "

    def test_preferred_height(self):
        f = ToggleField("Verbose")
        assert f.get_preferred_height(40) == 1


# ── TextField ──────────────────────────────────────────────────

class TestTextField:
    def test_default_value(self):
        f = TextField("Name")
        assert f.get_value() == ""

    def test_initial_value(self):
        f = TextField("Name", value="hello")
        assert f.get_value() == "hello"
        assert f.cursor_pos == 5

    def test_type_char(self):
        f = TextField("Name")
        assert f.handle_input("a") is True
        assert f.get_value() == "a"
        assert f.cursor_pos == 1

    def test_backspace(self):
        f = TextField("Name", value="ab")
        f.cursor_pos = 2
        assert f.handle_input("\x7f") is True
        assert f.get_value() == "a"
        assert f.cursor_pos == 1

    def test_backspace_at_start_ignored(self):
        f = TextField("Name", value="ab")
        f.cursor_pos = 0
        assert f.handle_input("\x7f") is False

    def test_delete(self):
        f = TextField("Name", value="ab")
        f.cursor_pos = 0
        assert f.handle_input("\x1b[3~") is True
        assert f.get_value() == "b"

    def test_cursor_left_right(self):
        f = TextField("Name", value="abc")
        f.cursor_pos = 1
        assert f.handle_input("\x1b[D") is True
        assert f.cursor_pos == 0
        assert f.handle_input("\x1b[C") is True
        assert f.cursor_pos == 1

    def test_cursor_home_end(self):
        f = TextField("Name", value="abc")
        f.cursor_pos = 1
        assert f.handle_input("\x1b[H") is True
        assert f.cursor_pos == 0
        assert f.handle_input("\x1b[F") is True
        assert f.cursor_pos == 3

    def test_insert_in_middle(self):
        f = TextField("Name", value="ac")
        f.cursor_pos = 1
        assert f.handle_input("b") is True
        assert f.get_value() == "abc"
        assert f.cursor_pos == 2

    def test_set_value(self):
        f = TextField("Name")
        f.set_value("new value")
        assert f.get_value() == "new value"
        assert f.cursor_pos == 9

    def test_render(self):
        f = TextField("Name", value="test")
        buf = Buffer(30, 1)
        f.render(buf, 0, 0, 30, 1)
        # Unfocused: "Name: test" starts at the content origin.
        assert buf.cells[0][0].char == "N"

    def test_render_focused(self):
        f = TextField("Name", value="test")
        f.focused = True
        buf = Buffer(30, 1)
        f.render(buf, 0, 0, 30, 1)
        # Focused: "▸ Name: test" — focus marker at 0
        assert buf.cells[0][0].char == "▸"

    def test_unrelated_input_ignored(self):
        f = TextField("Name")
        # Arrow keys that aren't handled should return False
        assert f.handle_input("\x1b[A") is False  # Up

    def test_preferred_height(self):
        f = TextField("Name")
        assert f.get_preferred_height(30) == 1


# ── TextAreaField ──────────────────────────────────────────────

class TestTextAreaField:
    def test_default_value(self):
        f = TextAreaField("Description")
        assert f.get_value() == ""

    def test_enter_inserts_newline(self):
        f = TextAreaField("Description", value="line1")
        f.cursor_row = 0
        f.cursor_col = 5
        assert f.handle_input("\r") is True
        assert f.get_value() == "line1\n"

    def test_backspace_joins_lines(self):
        f = TextAreaField("Description", value="line1\nline2")
        f.cursor_row = 1
        f.cursor_col = 0
        assert f.handle_input("\x7f") is True
        assert f.get_value() == "line1line2"

    def test_cursor_up_down(self):
        f = TextAreaField("Description", value="aaa\nbbb")
        f.cursor_row = 0
        f.cursor_col = 1
        assert f.handle_input("\x1b[B") is True  # Down
        assert f.cursor_row == 1
        assert f.handle_input("\x1b[A") is True  # Up
        assert f.cursor_row == 0

    def test_type_char(self):
        f = TextAreaField("Description")
        assert f.handle_input("x") is True
        assert f.get_value() == "x"

    def test_preferred_height(self):
        f = TextAreaField("Description", value="a\nb\nc", min_lines=2)
        # 3 lines of content + 1 label = 4, but min_lines=2 so max(2, 4) = 4
        assert f.get_preferred_height(40) == 4

    def test_preferred_height_respects_min(self):
        f = TextAreaField("Description", value="short", min_lines=5)
        assert f.get_preferred_height(40) == 5


# ── CheckboxListField ──────────────────────────────────────────

class TestCheckboxListField:
    def test_default_none_selected(self):
        f = CheckboxListField("Colors", options=["red", "green", "blue"])
        assert f.get_value() == []

    def test_toggle_on(self):
        f = CheckboxListField("Colors", options=["red", "green", "blue"])
        f._cursor = 1
        f.handle_input(" ")
        assert 1 in f.get_value()

    def test_toggle_off(self):
        f = CheckboxListField("Colors", options=["red", "green", "blue"], value=[1])
        f._cursor = 1
        f.handle_input(" ")
        assert f.get_value() == []

    def test_multiple_selections(self):
        f = CheckboxListField("Colors", options=["red", "green", "blue"])
        f._cursor = 0
        f.handle_input(" ")
        f._cursor = 2
        f.handle_input(" ")
        assert f.get_value() == [0, 2]

    def test_cursor_navigation(self):
        f = CheckboxListField("Colors", options=["red", "green", "blue"])
        assert f._cursor == 0
        f.handle_input("\x1b[B")  # Down
        assert f._cursor == 1
        f.handle_input("\x1b[A")  # Up
        assert f._cursor == 0

    def test_cursor_clamped(self):
        f = CheckboxListField("Colors", options=["red"])
        f.handle_input("\x1b[B")  # Down past end
        assert f._cursor == 0  # clamped
        f.handle_input("\x1b[A")  # Up past start
        assert f._cursor == 0

    def test_preferred_height(self):
        f = CheckboxListField("Colors", options=["red", "green", "blue"])
        assert f.get_preferred_height(40) == 4  # 1 label + 3 options

    def test_set_value(self):
        f = CheckboxListField("Colors", options=["red", "green", "blue"])
        f.set_value([0, 2])
        assert f.get_value() == [0, 2]


# ── RadioListField ─────────────────────────────────────────────

class TestRadioListField:
    def test_default_none(self):
        f = RadioListField("Priority", options=["low", "medium", "high"])
        assert f.get_value() is None

    def test_select(self):
        f = RadioListField("Priority", options=["low", "medium", "high"])
        f._cursor = 2
        f.handle_input(" ")
        assert f.get_value() == 2

    def test_single_select(self):
        f = RadioListField("Priority", options=["low", "medium", "high"])
        f._cursor = 0
        f.handle_input(" ")
        f._cursor = 2
        f.handle_input(" ")
        assert f.get_value() == 2
        assert 0 not in [f.get_value()]

    def test_cursor_navigation(self):
        f = RadioListField("Priority", options=["low", "medium", "high"])
        f.handle_input("\x1b[B")  # Down
        assert f._cursor == 1
        f.handle_input("\x1b[B")  # Down
        assert f._cursor == 2
        f.handle_input("\x1b[A")  # Up
        assert f._cursor == 1

    def test_preferred_height(self):
        f = RadioListField("Priority", options=["low", "medium", "high"])
        assert f.get_preferred_height(40) == 4

    def test_set_value(self):
        f = RadioListField("Priority", options=["low", "medium", "high"])
        f.set_value(1)
        assert f.get_value() == 1
        assert f._cursor == 1


# ── FormContainer ──────────────────────────────────────────────

class TestFormContainer:
    def test_empty_container(self):
        c = FormContainer([])
        assert c.get_preferred_height(40) == 0

    def test_focus_next_wraps(self):
        f1 = TextField("A")
        f2 = TextField("B")
        c = FormContainer([f1, f2])
        assert f1.focused is True
        c.focus_next()
        assert f1.focused is False
        assert f2.focused is True
        c.focus_next()
        assert f1.focused is True

    def test_focus_prev_wraps(self):
        f1 = TextField("A")
        f2 = TextField("B")
        c = FormContainer([f1, f2])
        c.focus_prev()
        assert f2.focused is True

    def test_tab_navigates(self):
        f1 = TextField("A")
        f2 = TextField("B")
        c = FormContainer([f1, f2])
        c.set_layout(0, 0, 40, 20)
        assert f1.focused is True
        c.handle_input("\t")
        assert f2.focused is True

    def test_shift_tab_navigates(self):
        f1 = TextField("A")
        f2 = TextField("B")
        c = FormContainer([f1, f2])
        c.set_layout(0, 0, 40, 20)
        c.handle_input("\t")  # move to f2
        assert f2.focused is True
        c.handle_input("\x1b[Z")  # Shift+Tab back to f1
        assert f1.focused is True

    def test_input_routes_to_focused_field(self):
        f1 = TextField("A")
        f2 = TextField("B")
        c = FormContainer([f1, f2])
        c.set_layout(0, 0, 40, 20)
        c.handle_input("x")
        assert f1.get_value() == "x"
        assert f2.get_value() == ""

    def test_field_focus_intent_moves_to_sibling(self):
        class EdgeField(FormField):
            def get_value(self): return None
            def set_value(self, value): pass
            def render(self, buffer, x, y, width, height): pass
            def handle_input(self, event): return False
            def handle_input_result(self, event):
                return InputResult(handled=True, focus="next")

        first = EdgeField("First")
        second = TextField("Second")
        container = FormContainer([first, second])
        assert container.handle_input("x") is True
        assert second.focused is True

    def test_profile_list_bubbles_down_at_create_action(self):
        profiles = ProfileListField("Profiles", options=["default", "+ create new"], value=0)
        following = TextField("Following")
        container = FormContainer([profiles, following])
        profiles._cursor = 1
        assert container.handle_input("\x1b[B") is True
        assert following.focused is True

    def test_composable_profile_list_selects_with_space(self):
        selected = []
        profiles = ProfileList(
            "Profiles", options=["default", "+ create new"],
            on_select=selected.append,
        )
        profiles._cursor = 0
        assert profiles.handle_input(" ") is True
        assert selected == ["default"]

    def test_composable_profile_list_moves_past_create_action(self):
        profiles = ProfileList("Profiles", options=["default", "second"])
        following = TextField("Following")
        container = FormContainer([profiles, following])
        profiles._cursor = 2
        assert container.handle_input("\x1b[B") is True
        assert following.focused is True

    def test_composable_profile_list_wraps_at_vertical_edges(self):
        profiles = ProfileList("Profiles", options=["default", "second"])
        following = TextField("Following")
        container = FormContainer([profiles, following])

        profiles._cursor = 0
        assert container.handle_input("\x1b[A") is True
        assert following.focused is True

        assert container.handle_input("\x1b[B") is True
        assert profiles.focused is True

    def test_composable_profile_list_rename_uses_block_cursor(self):
        profiles = ProfileList("Profiles", options=["default"])
        profiles.focused = True
        profiles._rename_profile("default")
        profiles.x, profiles.y = 0, 0
        profiles.width = 60
        profiles.height = profiles.get_preferred_height(60)
        buffer = Buffer(60, profiles.height)

        profiles.render(buffer, profiles.x, profiles.y, profiles.width, profiles.height)

        cursor_x = len("(x) ") + len("default") + 2
        assert buffer.cells[1][cursor_x].reverse is True

    def test_composable_profile_list_renames_inline(self):
        renamed = []
        profiles = ProfileList(
            "Profiles", options=["default"],
            on_rename=lambda old, new: renamed.append((old, new)) or True,
        )
        profiles._action_cursor = 1
        profiles.handle_input("\r")
        profiles.handle_input("x")
        profiles.handle_input("\r")
        assert renamed == [("default", "defaultx")]

    def test_inline_choice_mouse_selects_clicked_option(self):
        field = InlineChoiceField("Policy", options=["allow", "ask", "deny"], value=0)
        field.x, field.y, field.width, field.height = 0, 0, 60, 1
        # The second option starts after the fixed-width first option.
        assert field.handle_input(MouseEvent(23, 0, 0, True)) is True
        assert field.get_value() == "ask"

    def test_preferred_height_with_spacing(self):
        f1 = ToggleField("A")
        f2 = ToggleField("B")
        c = FormContainer([f1, f2])
        h = c.get_preferred_height(40)
        # 1 (field1) + 1 (spacing) + 1 (field2) = 3
        assert h == 3

    def test_render(self):
        f1 = ToggleField("A", value=True)
        f2 = ToggleField("B", value=False)
        c = FormContainer([f1, f2])
        c.set_layout(0, 0, 40, 10)
        buf = Buffer(40, 10)
        c.render(buf)
        # First field has focus; the checkbox is aligned on the right.
        assert buf.cells[0][0].char == "▸"
        assert buf.cells[0][2].char == "A"
        assert buf.cells[0][37].char == "["

    def test_scroll_offset_on_overflow(self):
        fields = [TextField(f"Field{i}") for i in range(20)]
        c = FormContainer(fields)
        c.set_layout(0, 0, 40, 5)  # Only 5 rows visible
        # Focus last field
        for _ in range(19):
            c.focus_next()
        assert c._scroll_offset > 0


# ── FormPopup ──────────────────────────────────────────────────

class TestFormPopup:
    def test_initial_state(self):
        fp = FormPopup()
        assert fp.is_visible is False

    def test_submit_calls_callback(self):
        fp = FormPopup()
        results = []
        fields = [TextField("Name", value="test")]
        fp.show("Test", fields, lambda v: results.append(v))
        assert fp.is_visible is True
        fp._try_submit()
        assert len(results) == 1
        assert results[0]["Name"] == "test"
        assert fp.is_visible is False

    def test_cancel_calls_callback(self):
        fp = FormPopup()
        cancelled = []
        fields = [TextField("Name")]
        fp.show("Test", fields, lambda v: None, on_cancel=lambda: cancelled.append(True))
        fp._do_cancel()
        assert len(cancelled) == 1
        assert fp.is_visible is False

    def test_required_field_blocks_submit(self):
        fp = FormPopup()
        results = []
        fields = [TextField("Name", required=True, value="")]
        fp.show("Test", fields, lambda v: results.append(v))
        fp._try_submit()
        assert len(results) == 0  # blocked
        assert fp._error_msg is not None

    def test_required_field_passes(self):
        fp = FormPopup()
        results = []
        fields = [TextField("Name", required=True, value="ok")]
        fp.show("Test", fields, lambda v: results.append(v))
        fp._try_submit()
        assert len(results) == 1

    def test_escape_key_cancels(self):
        fp = FormPopup()
        cancelled = []
        fields = [TextField("Name")]
        fp.show("Test", fields, lambda v: None, on_cancel=lambda: cancelled.append(True))
        fp.handle_input("\x1b")
        assert len(cancelled) == 1
        assert fp.is_visible is False

    def test_input_routes_to_fields(self):
        fp = FormPopup()
        fields = [TextField("Name")]
        fp.show("Test", fields, lambda v: None)
        fp.handle_input("a")
        assert fields[0].get_value() == "a"
        assert fp.dirty

    def test_reset_restores_model_values(self):
        fp = FormPopup()
        field = TextField("Name", value="before")
        fp.show("Test", [field], lambda v: None)
        fp.handle_input("x")
        assert field.get_value() == "beforex"
        assert fp.dirty

        fp.reset()
        assert field.get_value() == "before"
        assert not fp.dirty

    def test_cancel_resets_model_values_before_dismissal(self):
        fp = FormPopup()
        field = TextField("Name", value="before")
        fp.show("Test", [field], lambda v: None)
        fp.handle_input("x")
        fp._do_cancel()
        assert field.get_value() == "before"

    def test_tab_navigates_fields(self):
        fp = FormPopup()
        f1 = TextField("A")
        f2 = TextField("B")
        fp.show("Test", [f1, f2], lambda v: None)
        assert f1.focused is True
        fp.handle_input("\t")
        assert f2.focused is True

    def test_values_collected(self):
        fp = FormPopup()
        f1 = TextField("Name", value="server1")
        f2 = RadioListField("Type", options=["a", "b"], value=1)
        f3 = ToggleField("Debug", value=True)
        fp.show("Test", [f1, f2, f3], lambda v: None)
        values = {f.label: f.get_value() for f in [f1, f2, f3]}
        assert values["Name"] == "server1"
        assert values["Type"] == 1
        assert values["Debug"] is True

    def test_hide_clears_state(self):
        fp = FormPopup()
        fp.show("Test", [TextField("X")], lambda v: None)
        fp.hide()
        assert fp.is_visible is False
        assert fp._form_container is None

    def test_enter_on_textfield_does_not_advance(self):
        fp = FormPopup()
        f1 = TextField("A")
        f2 = TextField("B")
        fp.show("Test", [f1, f2], lambda v: None)
        assert f1.focused is True
        assert fp.handle_input("\r") is True
        assert f1.focused is True
        assert f2.focused is False

    def test_enter_on_toggle_acts_like_space_without_submitting(self):
        fp = FormPopup()
        results = []
        f1 = ToggleField("A")
        fp.show("Test", [f1], lambda v: results.append(v))
        fp.handle_input("\r")
        assert f1.get_value() is True
        assert results == []

    def test_validate_action_submits(self):
        fp = FormPopup()
        results = []
        fp.show("Test", [TextField("Name", value="ok")], results.append)
        assert any(action.key == "Enter" and action.label == "validate"
               for action in fp._box.actions)
        assert fp._try_submit()
        assert results == [{"Name": "ok"}]

    def test_down_focuses_validate_and_enter_submits(self):
        fp = FormPopup()
        results = []
        fp.show("Test", [ToggleField("Enabled")], results.append)

        assert fp.handle_input("\x1b[B") is True
        assert fp._action_focus_index == 0
        assert fp._box.focused_action_key == "Enter"
        assert fp.handle_input("\r") is True
        assert results == [{"Enabled": False}]

    def test_up_from_action_returns_to_last_field(self):
        fp = FormPopup()
        field = ToggleField("Enabled")
        fp.show("Test", [field], lambda values: None)

        fp.handle_input("\x1b[B")
        fp.handle_input("\x1b[A")

        assert fp._action_focus_index is None
        assert field.focused is True

    def test_clicking_field_leaves_action_focus(self):
        fp = FormPopup()
        field = TextField("Name")
        fp.show("Test", [field], lambda values: None)
        fp.handle_input("\x1b[B")
        fp.render(Buffer(80, 24))
        fp._form_container._compute_layout()

        fp.handle_input(MouseEvent(fp._box.x + 3, fp._box.y + 1, 0, True))

        assert fp._action_focus_index is None
