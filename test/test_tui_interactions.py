from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components.form import RadioListField, TextField
from pico_chat.ui.tui.events import KeyEvent, normalize_key
from pico_chat.ui.tui.components.form_popup import FormPopup
from pico_chat.ui.tui.components.tab_bar import TabBar
from pico_chat.ui.tui.components.config_overlay import ConfigOverlay
from pico_chat.ui.tui.terminal import MouseEvent
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.chat_history_panel import ChatHistoryPanel
from pico_chat.ui.app import ConversationState, chatTUI
from conftest import StubAgent


class FakeCompositor:
    def __init__(self, width=80, height=24):
        self.width = width
        self.height = height
        self.overlays = []

    def add_overlay(self, component):
        self.overlays.append(component)

    def remove_overlay(self, component):
        self.overlays.remove(component)

    def request_render(self):
        pass


class FakeMessageComponent:
    parent = None


class FakeMessage:
    def __init__(self):
        self.component = FakeMessageComponent()

    def get_component(self):
        return self.component


def test_chat_history_restores_messages_through_panel_boundary():
    panel = ChatHistoryPanel()
    messages = [FakeMessage(), FakeMessage()]

    panel.restore_messages(messages)

    assert panel.messages == messages
    assert all(message.component.parent is panel for message in messages)


def test_config_overlay_server_shortcuts_use_key_event_metadata():
    overlay = ConfigOverlay()
    overlay.set_servers([{"name": "test", "type": "local", "is_active": True}])
    actions = []
    overlay.on_remove_server = lambda name: actions.append(("remove", name))
    overlay.on_use_server = lambda name: actions.append(("use", name))

    assert overlay.handle_input(KeyEvent("r"))
    assert overlay.handle_input(KeyEvent("u"))


def test_cached_hit_test_rebuilds_after_cache_invalidation():
    """Scrolling invalidates the line-map cache; a subsequent hit test must
    rebuild it rather than crashing on a None cache (regression)."""
    from pico_chat.ui.tui.msg_types import UserMsg

    panel = ChatHistoryPanel()
    panel.set_layout(0, 0, 40, 10)
    panel.add_message("hello", msg_type=UserMsg())
    panel.add_message("world", msg_type=UserMsg())

    # Simulate the scroll handler invalidating only the cache (not the key).
    panel._line_map_cache = None

    # Must not raise TypeError (len() of None).
    result = panel._cached_hit_test(panel.y + 1)
    assert result is not None


def test_app_focus_targets_expose_component_geometry_for_mouse_focus():
    ui = chatTUI(StubAgent())
    ui.chat_history_panel.set_layout(0, 0, 80, 20)
    ui.input_component.set_layout(0, 20, 80, 4)

    handled = ui.handle_global_input(MouseEvent(4, 5, 0, True))

    assert handled is False
    assert ui._last_focus_id == "history"


def test_tab_click_requires_tab_bar_row():
    selected = []
    tab_bar = TabBar()
    tab_bar.add_tab("chat", closeable=False)
    tab_bar.add_tab("second")
    tab_bar.set_callbacks(selected.append, lambda index: None, lambda: None)
    tab_bar.set_layout(0, 3, 40, 1)
    tab_bar.render(Buffer(40, 10))

    assert tab_bar.handle_input(MouseEvent(2, 8, 0, True)) is False
    assert selected == []
    assert tab_bar.handle_input(MouseEvent(2, 3, 0, True)) is True
    assert selected == [0]


def test_tab_close_click_dispatches_tab_index():
    closed = []
    tab_bar = TabBar()
    tab_bar.add_tab("chat", closeable=False)
    tab_bar.add_tab("debug")
    tab_bar.set_callbacks(lambda index: None, closed.append, lambda: None)
    tab_bar.set_layout(0, 0, 40, 1)
    tab_bar.render(Buffer(40, 2))

    assert tab_bar.handle_input(MouseEvent(16, 0, 0, True)) is True
    assert closed == [1]


def test_tab_layout_change_invalidates_cached_click_regions():
    selected = []
    tab_bar = TabBar()
    tab_bar.add_tab("chat", closeable=False)
    tab_bar.set_callbacks(selected.append, lambda index: None, lambda: None)
    tab_bar.set_layout(0, 0, 40, 1)
    tab_bar.render(Buffer(40, 2))
    tab_bar.set_layout(20, 4, 20, 1)

    assert tab_bar.handle_input(MouseEvent(2, 0, 0, True)) is False
    assert selected == []


def test_insert_tab_preserves_existing_tab_order():
    tab_bar = TabBar()
    tab_bar.add_tab("chat", closeable=False)
    tab_bar.add_tab("debug")

    tab_bar.insert_tab(1, "chat 2")

    assert [tab.name for tab in tab_bar.tabs] == ["chat", "chat 2", "debug"]


def test_tab_bar_highlights_only_active_tab():
    tab_bar = TabBar()
    tab_bar.add_tab("chat", closeable=False)
    tab_bar.add_tab("debug")
    tab_bar.set_active(1)
    tab_bar.set_layout(0, 0, 40, 1)

    buffer = Buffer(40, 2)
    tab_bar.render(buffer)

    assert buffer.cells[0][1].reverse is True
    assert buffer.cells[0][9].reverse is True
    assert buffer.cells[0][1].fg is theme.MUTED
    assert buffer.cells[0][9].fg is theme.DEFAULT


def test_debug_tab_index_tracks_conversation_close():
    ui = chatTUI(StubAgent())
    ui._tabs = [
        ConversationState("chat"),
        ConversationState("chat 2"),
        ConversationState("debug", kind="debug"),
    ]
    for index, tab in enumerate(ui._tabs):
        ui.tab_view.add(f"test-{index}", tab.name, tab, closeable=True)
    ui.tab_view.on_close = ui._on_tab_view_close
    ui.tab_view.can_close = ui._can_close_tab
    ui._active_tab_index = 0

    ui._close_tab(0)

    assert ui._debug_tab_index() == 1
    assert ui.tab_bar.tabs[1].name == "debug"


def _configure_conversation_tabs(ui, names):
    ui._tabs = [ConversationState(name) for name in names]
    for index, tab in enumerate(ui._tabs):
        ui.tab_view.add(f"test-{index}", tab.name, tab, closeable=True)
    ui.tab_view.on_change = ui._on_tab_view_change
    ui.tab_view.on_close = ui._on_tab_view_close
    ui.tab_view.can_close = ui._can_close_tab


def test_workspace_starts_without_tabs():
    ui = chatTUI(StubAgent())

    assert ui._tabs == []
    assert ui.tab_view.items == []


def test_closing_last_conversation_leaves_empty_workspace():
    ui = chatTUI(StubAgent())
    ui._new_tab("chat")
    ui.tab_view.on_change = ui._on_tab_view_change
    ui.tab_view.on_close = ui._on_tab_view_close
    ui.tab_view.can_close = ui._can_close_tab

    ui._close_tab(0)

    assert ui._tabs == []
    assert ui.tab_view.items == []
    assert ui.tab_view.active_index is None


def test_empty_workspace_creates_conversation_on_first_ordinary_input():
    ui = chatTUI(StubAgent())

    ui.on_user_submit("hello")

    assert [tab.kind for tab in ui._tabs] == ["chat"]
    assert ui._active_tab_index == 0


def test_message_in_other_tab_is_not_marked_queued_by_active_generation():
    class ActiveTask:
        def done(self):
            return False

    ui = chatTUI(StubAgent())
    ui._new_tab("one")
    first_tab = ui._tabs[0]
    ui._new_tab("two")

    ui._active_generation_tab = first_tab
    ui.current_generation_task = ActiveTask()
    ui.on_user_submit("first message in second tab")

    message = ui.chat_history_panel.messages[-1]
    assert message.is_queued is False
    assert message.title == "user"


def test_conversation_tabs_own_runtime_resources():
    ui = chatTUI(StubAgent())
    ui._new_tab("one")
    first = ui._tabs[0]
    ui._new_tab("two")
    second = ui._tabs[1]

    assert first.agent is not second.agent
    assert first.chat_history_panel is not second.chat_history_panel
    assert first.message_queue is not second.message_queue


def test_conversation_tabs_show_independent_history_panels():
    ui = chatTUI(StubAgent())
    ui._new_tab("one")
    first = ui._tabs[0]
    first.chat_history_panel.add_message("message from one")

    ui._new_tab("two")
    second = ui._tabs[1]
    second.chat_history_panel.add_message("message from two")

    ui._on_tab_select(0)
    assert ui.chat_history_panel is first.chat_history_panel
    assert [message.base_text for message in ui.chat_history_panel.messages] == ["message from one"]

    ui._on_tab_select(1)
    assert ui.chat_history_panel is second.chat_history_panel
    assert [message.base_text for message in ui.chat_history_panel.messages] == ["message from two"]


def test_submitting_messages_uses_only_the_selected_conversation_runtime():
    ui = chatTUI(StubAgent())
    ui._new_tab("one")
    first = ui._tabs[0]

    ui.on_user_submit("message from one")
    first.ensure_agent().history.append("history from one")
    first.pending_permission_prompt = "permission in one"

    ui._new_tab("two")
    second = ui._tabs[1]
    ui.on_user_submit("message from two")
    second.ensure_agent().history.append("history from two")

    assert [message.base_text for message in first.messages] == ["message from one"]
    assert [message.base_text for message in second.messages] == ["message from two"]
    assert first.message_queue.qsize() == 1
    assert second.message_queue.qsize() == 1
    assert first.harness_history == ["history from one"]
    assert second.harness_history == ["history from two"]

    ui._on_tab_select(0)
    assert ui.pending_permission_prompt == "permission in one"
    assert [message.base_text for message in ui.chat_history_panel.messages] == ["message from one"]

    ui._on_tab_select(1)
    assert ui.pending_permission_prompt is None
    assert [message.base_text for message in ui.chat_history_panel.messages] == ["message from two"]


def test_new_tab_after_debug_panel_mounts_into_current_chat_workspace():
    ui = chatTUI(StubAgent())
    ui._new_tab("one")
    ui.on_user_submit("message from one")

    # Build the same initial workspace that run() installs.
    ui._install_chat_screen()
    ui._chat_workspace = ui.root.children[1]
    ui.toggle_debug_console()
    ui._new_tab("two")

    visible_history = ui.root.children[1].children[0]
    assert visible_history is ui._tabs[2].chat_history_panel
    assert visible_history is not ui._tabs[0].chat_history_panel


def test_multiple_messages_are_consistently_queued_during_generation():
    class ActiveTask:
        def done(self):
            return False

    ui = chatTUI(StubAgent())
    ui._new_tab("chat")
    runtime = ui._tabs[0]
    ui._active_generation_tab = runtime
    runtime.current_generation_task = ActiveTask()

    ui.on_user_submit("second")
    ui.on_user_submit("third")
    ui.on_user_submit("fourth")

    queued = runtime.chat_history_panel.messages
    assert [message.is_queued for message in queued] == [True, True, True]
    assert runtime.message_queue.qsize() == 3


def test_closing_active_first_tab_selects_next_tab_consistently():
    ui = chatTUI(StubAgent())
    _configure_conversation_tabs(ui, ["one", "two", "three"])
    ui._active_tab_index = 0

    ui._close_tab(0)

    assert [tab.name for tab in ui._tabs] == ["two", "three"]
    assert [item.title for item in ui.tab_view.items] == ["two", "three"]
    assert [tab.name for tab in ui.tab_bar.tabs] == ["two", "three"]
    assert ui._active_tab_index == 0
    assert ui.tab_view.active_index == 0
    assert ui.tab_bar.active_index == 0


def test_closing_inactive_first_tab_preserves_active_third_tab():
    ui = chatTUI(StubAgent())
    _configure_conversation_tabs(ui, ["one", "two", "three"])
    ui._active_tab_index = 2
    ui.tab_view.activate(2)

    ui._close_tab(0)

    assert [tab.name for tab in ui._tabs] == ["two", "three"]
    assert [item.title for item in ui.tab_view.items] == ["two", "three"]
    assert [tab.name for tab in ui.tab_bar.tabs] == ["two", "three"]
    assert ui._active_tab_index == 1
    assert ui.tab_view.active_index == 1
    assert ui.tab_bar.active_index == 1


def test_returning_from_debug_updates_active_header_tab():
    ui = chatTUI(StubAgent())
    ui._tabs = [ConversationState("chat"), ConversationState("debug", kind="debug")]
    for index, tab in enumerate(ui._tabs):
        ui.tab_view.add(f"test-{index}", tab.name, tab, closeable=index != 0)
    ui._active_tab_index = 0
    ui.tab_view.activate(1)
    ui.show_debug = True

    ui._on_tab_select(0)

    assert ui.show_debug is False
    assert ui.tab_bar.active_index == 0


def test_radio_option_click_selects_clicked_option():
    compositor = FakeCompositor()
    selected = []
    field = RadioListField("Type", options=["local", "remote"])
    popup = FormPopup(compositor=compositor)
    popup.show("Test", [field], lambda values: selected.append(values))
    popup._form_container.set_layout(popup.x + 1, popup.y + 1, popup.width - 2, popup.height - 2)
    popup._form_container._compute_layout()
    popup.render(Buffer(80, 24))

    field_y = popup._box.y + 1 + popup._box.padding_y + popup._form_container._field_offsets[0]
    click = MouseEvent(popup.x + 3, field_y + 2, 0, True)
    assert popup.handle_input(click) is True
    assert field.get_value() == 1


def test_form_tab_and_shift_tab_move_focus_both_directions():
    popup = FormPopup(compositor=FakeCompositor())
    popup.show("Test", [TextField("Name"), RadioListField("Type", options=["local", "remote"])], lambda values: None)

    assert popup._form_container.get_focused_field().label == "Name"
    assert popup.handle_input(normalize_key("\t")) is True
    assert popup._form_container.get_focused_field().label == "Type"
    assert popup.handle_input(normalize_key("\x1b[Z")) is True
    assert popup._form_container.get_focused_field().label == "Name"