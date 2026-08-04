from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from pico_chat.ui.tui.actions import Action, ActionMap, Actions
from pico_chat.ui.tui.components.tab_bar import TabBar
from pico_chat.ui.tui.screen import Screen


@dataclass
class TabItem:
    """Stable identity and presentation metadata for one tab view."""

    id: str
    title: str
    view: Any
    closeable: bool = True


class TabView:
    """Own tab views and selection state without owning their domain models."""

    def __init__(self, *, tab_bar: Optional[TabBar] = None,
                 on_change: Optional[Callable[[TabItem], None]] = None,
                 on_close: Optional[Callable[[int, TabItem], None]] = None,
                 can_close: Optional[Callable[[int, TabItem], bool]] = None):
        self.tab_bar = tab_bar or TabBar()
        self.items: List[TabItem] = []
        self._entered_ids: set[str] = set()
        self.active_index: Optional[int] = None
        self.on_change = on_change
        self.on_close = on_close
        self.can_close = can_close
        self.action_map = ActionMap()
        self.action_map.bind(Actions.ACTIVATE, self._activate_action)
        self.action_map.bind(Actions.CLOSE, self._close_action)
        self.action_map.bind(Actions.NEXT, self._next_action)
        self.action_map.bind(Actions.PREVIOUS, self._previous_action)
        self.tab_bar.set_callbacks(self.activate, self.close, self._new_tab)
        self._on_new: Optional[Callable[[], None]] = None

    @property
    def active_item(self) -> Optional[TabItem]:
        if self.active_index is None:
            return None
        return self.items[self.active_index]

    @property
    def active_view(self) -> Any:
        item = self.active_item
        return item.view if item else None

    def set_on_new(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_new = callback

    def add(self, tab_id: str, title: str, view: Any, *, closeable: bool = True) -> TabItem:
        if any(item.id == tab_id for item in self.items):
            raise ValueError(f"Duplicate tab id: {tab_id}")
        item = TabItem(tab_id, title, view, closeable)
        self.items.append(item)
        self.tab_bar.add_tab(title, closeable=closeable)
        if self.active_index is None:
            self.active_index = 0
            self.tab_bar.set_active(0)
            self._activate_view(item)
            self._notify_change(item)
        return item

    def activate(self, index: int) -> bool:
        if not 0 <= index < len(self.items) or index == self.active_index:
            return False
        old = self.active_item
        if old is not None:
            self._suspend_view(old)
        self.active_index = index
        self.tab_bar.set_active(index)
        item = self.items[index]
        self._activate_view(item)
        self._notify_change(item)
        return True

    def activate_id(self, tab_id: str) -> bool:
        for index, item in enumerate(self.items):
            if item.id == tab_id:
                return self.activate(index)
        return False

    def close(self, index: int) -> bool:
        if not 0 <= index < len(self.items):
            return False
        item = self.items[index]
        if not item.closeable:
            return False
        if self.can_close is not None and not self.can_close(index, item):
            return False
        was_active = index == self.active_index
        self._leave_view(item)
        self._entered_ids.discard(item.id)
        self.items.pop(index)
        self.tab_bar.remove_tab(index)
        if self.on_close:
            self.on_close(index, item)
        if not self.items:
            self.active_index = None
        elif was_active:
            self.active_index = min(index, len(self.items) - 1)
            self.tab_bar.set_active(self.active_index)
            self._resume_view(self.items[self.active_index])
            self._notify_change(self.items[self.active_index])
        elif self.active_index is not None and index < self.active_index:
            self.active_index -= 1
        return True

    def dispatch(self, action: Action) -> bool:
        return self.action_map.dispatch(action)

    def _activate_action(self, action: Action) -> bool:
        return self.activate(int(action.payload)) if action.payload is not None else False

    def _close_action(self, action: Action) -> bool:
        return self.close(int(action.payload)) if action.payload is not None else False

    def _next_action(self, action: Action) -> bool:
        if not self.items or self.active_index is None:
            return False
        return self.activate((self.active_index + 1) % len(self.items))

    def _previous_action(self, action: Action) -> bool:
        if not self.items or self.active_index is None:
            return False
        return self.activate((self.active_index - 1) % len(self.items))

    def _new_tab(self) -> None:
        if self._on_new:
            self._on_new()

    def _notify_change(self, item: TabItem) -> None:
        if self.on_change:
            self.on_change(item)

    def _activate_view(self, item: TabItem) -> None:
        if isinstance(item.view, Screen):
            if item.id in self._entered_ids:
                item.view.on_resume()
            else:
                item.view.on_enter()
                self._entered_ids.add(item.id)

    @staticmethod
    def _resume_view(item: TabItem) -> None:
        if isinstance(item.view, Screen):
            item.view.on_resume()

    @staticmethod
    def _suspend_view(item: TabItem) -> None:
        if isinstance(item.view, Screen):
            item.view.on_suspend()

    @staticmethod
    def _leave_view(item: TabItem) -> None:
        if isinstance(item.view, Screen):
            item.view.on_leave()
