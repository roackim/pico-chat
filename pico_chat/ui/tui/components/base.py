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

    def set_layout(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    @abstractmethod
    def render(self, buffer: Buffer):
        pass

    def handle_input(self, event: Any) -> bool:
        """Return True if event was handled."""
        return False

    def update(self, data: Any):
        """Update component state with new data."""
        pass
