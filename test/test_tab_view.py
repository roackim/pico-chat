from pico_chat.ui.tui.actions import Action, Actions
from pico_chat.ui.tui.components.tab_view import TabView
from pico_chat.ui.tui.screen import Screen
from pico_chat.ui.tui.components.text import TextComponent


class LifecycleScreen(Screen):
    def __init__(self):
        super().__init__(TextComponent("screen"))
        self.events = []

    def on_enter(self):
        self.events.append("enter")

    def on_resume(self):
        self.events.append("resume")

    def on_suspend(self):
        self.events.append("suspend")

    def on_leave(self):
        self.events.append("leave")


def test_tab_view_owns_stable_items_and_preserves_views():
    tabs = TabView()
    first = object()
    second = object()

    tabs.add("chat-1", "Chat", first, closeable=False)
    tabs.add("chat-2", "Second", second)

    assert tabs.active_item.id == "chat-1"
    assert tabs.activate_id("chat-2")
    assert tabs.active_view is second
    assert tabs.items[0].view is first


def test_tab_view_dispatches_shared_tab_actions():
    tabs = TabView()
    tabs.add("one", "One", object())
    tabs.add("two", "Two", object())

    assert tabs.dispatch(Action(Actions.NEXT))
    assert tabs.active_item.id == "two"
    assert tabs.dispatch(Action(Actions.PREVIOUS))
    assert tabs.active_item.id == "one"
    assert tabs.dispatch(Action(Actions.ACTIVATE, 1))
    assert tabs.active_item.id == "two"


def test_tab_view_runs_screen_lifecycle_without_recreating_views():
    tabs = TabView()
    first = LifecycleScreen()
    second = LifecycleScreen()
    tabs.add("one", "One", first)
    tabs.add("two", "Two", second)

    tabs.activate(1)
    tabs.activate(0)
    tabs.close(1)

    assert first.events == ["enter", "suspend", "resume"]
    assert second.events == ["enter", "suspend", "leave"]


def test_non_closeable_tab_cannot_be_closed():
    tabs = TabView()
    tabs.add("main", "Main", object(), closeable=False)

    assert not tabs.close(0)
    assert len(tabs.items) == 1