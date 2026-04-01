from abc import ABC, abstractmethod
from typing import Optional, Any
from pico_chat.ui.tui.buffer import Buffer

class Component(ABC):
    def __init__(self, id: Optional[str] = None):
        self.id = id
        self.x = 0
        self.y = 0
        self.width = 0
        self.height = 0
        self.parent: Optional['Component'] = None
        self._dirty = True
        self._dirty_rect: Optional[tuple[int, int, int, int]] = None

    def set_layout(self, x: int, y: int, width: int, height: int):
        old_layout = (self.x, self.y, self.width, self.height)
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        if old_layout != (x, y, width, height):
            self.mark_changed((x, y, width, height))

    def mark_changed(self, rect: Optional[tuple[int, int, int, int]] = None):
        self._dirty = True
        if rect is None:
            rect = (self.x, self.y, self.width, self.height)
        self._dirty_rect = rect
        if self.parent and hasattr(self.parent, 'mark_changed'):
            self.parent.mark_changed(rect)

    def is_dirty(self) -> bool:
        return self._dirty

    def collect_dirty_rects(self, rects: list[tuple[int, int, int, int]]):
        if self._dirty_rect is not None:
            rects.append(self._dirty_rect)
        if hasattr(self, 'children'):
            for child in self.children:
                if hasattr(child, 'collect_dirty_rects'):
                    child.collect_dirty_rects(rects)

    def clear_dirty(self):
        self._dirty = False
        self._dirty_rect = None
        if hasattr(self, 'children'):
            for child in self.children:
                if hasattr(child, 'clear_dirty'):
                    child.clear_dirty()

    @abstractmethod
    def render(self, buffer: Buffer):
        pass

    def handle_input(self, event: Any) -> bool:
        """Return True if event was handled."""
        return False

    def update(self, data: Any):
        """Update component state with new data."""
        self.mark_changed()
