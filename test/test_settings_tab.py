"""Tests for the settings tab: panel, pages, screen, and command wiring."""

from __future__ import annotations

import asyncio

import pytest

from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components.settings_panel import SettingsPanel, SettingsPage
from pico_chat.ui.tui.events import KeyEvent, MouseEvent


class _FakeField:
    """Minimal form field for panel tests."""

    focusable = True

    def __init__(self, label):
        self.label = label
        self.parent = None
        self.dirty = False
        self.x = self.y = self.width = self.height = 0
        self.handled_keys = []

    def get_preferred_height(self, width):
        return 1

    def render(self, buffer, x, y, width, height):
        pass

    def handle_input(self, event):
        self.handled_keys.append(event)
        return True

    def handle_input_result(self, event):
        from pico_chat.ui.tui.input_result import InputResult
        if self.handle_input(event):
            return InputResult(handled=True, redraw=False, focus=None)
        return InputResult.from_legacy(False)

    def get_value(self):
        return None

    def set_value(self, value):
        pass

    def activate(self):
        return False

    def set_focused(self, focused):
        pass


def _panel() -> SettingsPanel:
    pages = [
        SettingsPage("permissions", lambda: [_FakeField("perm")],
                     title="Permissions", description="Tool policies."),
        SettingsPage("roles", lambda: [_FakeField("role")]),
    ]
    return SettingsPanel(pages)


def test_panel_requires_pages():
    with pytest.raises(ValueError):
        SettingsPanel([])


def test_panel_switches_page_content():
    panel = _panel()
    assert panel.selected_page.name == "permissions"
    panel._on_page_select("roles")
    assert panel.selected_page.name == "roles"
    # The roles page has no title → falls back to the page name.
    title = panel._content.fields[0].component
    assert title.text == "roles"
    assert panel._content.fields[-1].label == "role"


def test_panel_injects_title_and_description_header():
    panel = _panel()
    from pico_chat.ui.tui.components.text import Label
    header = panel._content.fields[0].component
    assert isinstance(header, Label)
    assert header.text == "Permissions"
    description = panel._content.fields[1].component
    assert isinstance(description, Label)
    assert description.text == "Tool policies."


def test_panel_left_right_keys_switch_pane_when_field_declines():
    """Left/right switch panes only when the focused field declines them."""
    panel = _panel()
    panel._set_pane("content")

    class DeclinesArrows(_FakeField):
        def handle_input(self, event):
            key = event.key if hasattr(event, "key") else event
            if key in ("\x1b[D", "\x1b[C", "h", "l"):
                return False
            return super().handle_input(event)

    # Replace the content's only focusable field so it declines arrows.
    content = panel._content
    declining = DeclinesArrows("decline")
    content.fields[-1] = declining
    declining.parent = content
    content._focus_fields = content._flatten_focus_fields()

    # Left arrow declined by field -> falls back to pane switch to list.
    panel.handle_input(KeyEvent("\x1b[D"))
    assert panel._pane == "list"


def test_panel_left_right_keys_switch_to_content():
    panel = _panel()
    panel._set_pane("list")
    panel.handle_input(KeyEvent("\x1b[C"))
    assert panel._pane == "content"


def test_panel_routes_keys_to_active_pane():
    panel = _panel()
    field = panel._content.fields[-1]
    panel.handle_input("x")
    assert field.handled_keys == ["x"]


def test_panel_mouse_click_in_left_column_selects_list_pane():
    panel = _panel()
    panel.set_layout(0, 0, 60, 20)
    panel.handle_input(MouseEvent(5, 2, 0, True))
    assert panel._pane == "list"


def test_panel_renders_into_buffer():
    panel = _panel()
    panel.set_layout(0, 0, 60, 20)
    panel.layout()
    panel.render(Buffer(60, 20))


def test_settings_screen_renders_tab_bar_and_panel():
    from pico_chat.ui.tui.components.tab_bar import TabBar
    from pico_chat.ui.tui.components.bars import StatusBar
    from pico_chat.ui.tui.focus import FocusScope
    from pico_chat.ui.tui.settings_screen import SettingsScreen

    panel = _panel()
    status_bar = StatusBar()
    screen = SettingsScreen(TabBar(), panel, FocusScope([]), None, status_bar)
    screen.root.set_layout(0, 0, 80, 24)
    screen.root.layout()
    screen.on_enter()
    screen.root.render(Buffer(80, 24))
    assert panel.width == 78  # 80 minus 1-char gutters on each side
    # Status bar pinned to the bottom row.
    assert status_bar.y == 23
    assert status_bar.height == 1
    # Tab bar occupies the top row.
    assert screen.scaffold.top.y == 0
    assert screen.scaffold.top.height >= 1


def test_settings_screen_pane_helpers():
    from pico_chat.ui.tui.components.tab_bar import TabBar
    from pico_chat.ui.tui.focus import FocusScope
    from pico_chat.ui.tui.settings_screen import SettingsScreen

    panel = _panel()
    screen = SettingsScreen(TabBar(), panel, FocusScope([]))
    assert screen.active_pane == "content"
    screen.focus_page_list()
    assert screen.active_pane == "list"
    screen.focus_content()
    assert screen.active_pane == "content"


def test_settings_pages_builders_produce_pages():
    from pico_chat.ui.settings_pages import settings_pages

    pages = settings_pages()
    # Permissions were merged into the single roles page: a role already
    # carries every permission policy.
    assert [page.name for page in pages] == ["roles"]
    assert pages[0].title == "Roles"
    fields = pages[0].build_fields()
    assert fields, "roles page produced no fields"


def test_settings_command_registered():
    from pico_chat.ui.commands.builtins import COMMANDS
    from pico_chat.ui.commands.settings import SettingsCommand

    assert isinstance(COMMANDS["settings"], SettingsCommand)


def test_settings_command_toggles_tab():
    from pico_chat.ui.commands.settings import SettingsCommand

    calls = []

    class FakeUI:
        def toggle_settings_tab(self):
            calls.append(True)

        def show_popup(self, *a, **kw):
            raise AssertionError("should not fall back to popup")

    asyncio.run(SettingsCommand().execute(FakeUI(), []))
    assert calls == [True]


def test_panel_left_right_keys_switch_pane_when_field_declines():
    """Left/right switch panes only when the focused field declines them."""
    panel = _panel()
    panel._set_pane("content")

    class DeclinesArrows(_FakeField):
        def handle_input(self, event):
            key = event.key if hasattr(event, "key") else event
            if key in ("\x1b[D", "\x1b[C", "h", "l"):
                return False
            return super().handle_input(event)

    # Replace the content's only focusable field so it declines arrows.
    from pico_chat.ui.tui.components.form import FormContainer
    content = panel._content
    declining = DeclinesArrows("decline")
    content.fields[-1] = declining
    declining.parent = content
    content._focus_fields = content._flatten_focus_fields()

    # Right arrow declined by field -> falls back to pane switch.
    panel.handle_input(KeyEvent("\x1b[C"))
    assert panel._pane == "content" and content.handle_input(KeyEvent("\x1b[C")) is False
    # Left arrow -> switch back to list.
    panel.handle_input(KeyEvent("\x1b[D"))
    assert panel._pane == "list"


def test_profile_list_actions_reachable_by_keyboard():
    """Left/right arrows reach ProfileList action buttons instead of switching
    the pane, and Enter activates the selected action."""
    from pico_chat.ui.tui.components.form import ProfileList

    duplicates, removes = [], []

    def on_dup(name):
        duplicates.append(name)

    def on_rm(name):
        removes.append(name)

    plist = ProfileList(
        "Available roles", options=["default", "babysit"], value=0,
        on_rename=lambda o, n: True, on_duplicate=on_dup, on_remove=on_rm,
        on_create=lambda: None,
    )
    panel = SettingsPanel([SettingsPage("roles", lambda: [plist])])
    panel.set_layout(0, 0, 100, 30)
    panel.layout()
    panel._set_pane("content")

    # Cursor starts on the name button (index 0): right arrow moves to rename.
    panel.handle_input(KeyEvent("\x1b[C"))
    assert plist._action_cursor == 1
    assert panel._pane == "content"  # must NOT switch to the list pane

    # Move across to remove (index 3) via l keys and activate it.
    panel.handle_input(KeyEvent("l"))
    panel.handle_input(KeyEvent("l"))
    assert plist._action_cursor == 3
    panel.handle_input(KeyEvent("\r"))
    assert removes == ["default"]

    # Move back to duplicate with h and activate it.
    panel.handle_input(KeyEvent("h"))
    assert plist._action_cursor == 2
    panel.handle_input(KeyEvent("\r"))
    assert duplicates == ["default"]


def test_panel_content_indent_wraps_content_in_padding():
    from pico_chat.ui.tui.container import Padding

    panel = SettingsPanel(_panel().pages, content_indent=2)
    panel.set_layout(0, 0, 100, 30)
    panel.layout()
    third = panel._split.children[2]
    assert isinstance(third, Padding)
    assert third.padding == (0, 0, 0, 2)
    # The wrapped FormContainer is offset by the left indent.
    assert third.child.x == third.x + 2


def test_panel_no_indent_by_default():
    panel = _panel()
    panel.set_layout(0, 0, 100, 30)
    panel.layout()
    # Without content_indent the content is the FormContainer directly.
    assert panel._split.children[2] is panel._content


def test_panel_tab_cycles_between_panes():
    panel = _panel()
    panel._set_pane("content")
    panel.handle_input(KeyEvent("\t"))
    assert panel._pane == "list"
    panel.handle_input(KeyEvent("\x1b[Z"))
    assert panel._pane == "content"


def test_panel_list_pane_keyboard_focusable():
    panel = _panel()
    panel._set_pane("list")
    assert panel._list.focused is True
    # Up/down navigate the list; with 2 pages we can move.
    panel.handle_input(KeyEvent("\x1b[B"))
    assert panel._list.model.selected_index == 1
    panel.handle_input(KeyEvent("\x1b[A"))
    assert panel._list.model.selected_index == 0


def test_role_prompt_enter_submits_alt_enter_newline():
    from pico_chat.ui.role_editor_form import RoleEditorForm
    from pico_chat.ui.role_editor_model import RoleEditorModel

    saved = []
    editor = RoleEditorModel("default")
    form = RoleEditorForm(editor)
    prompt = form.field("role_prompt")
    prompt._editor.on_submit = lambda v: saved.append(v)

    prompt._editor.set_value("hello")
    prompt._editor.handle_input(KeyEvent("\r"))
    assert saved == ["hello"]

    prompt._editor.set_value("hello")
    prompt._editor.handle_input(KeyEvent("\x1b\r"))
    assert "\n" in prompt._editor.get_value()
