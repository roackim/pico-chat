"""Input panel for the Open-Clank TUI."""

import asyncio
from typing import Optional, Callable

from pico_chat.ui.tui.component import InputComponent, Box


class InputPanel:
    """Manages the user input panel."""

    def __init__(self, user_color: tuple[int, int, int]):
        """Initialize the input panel.
        
        Args:
            user_color: RGB color tuple for user text
        """
        self.component = InputComponent("> ", id="entry", fg=user_color)
        self.box = Box(self.component, title="Input")
        self.on_submit_callback: Optional[Callable[[str], None]] = None

    def set_on_submit(self, callback: Callable[[str], None]):
        """Set the callback for when user submits input.
        
        Args:
            callback: Function to call with the submitted text
        """
        self.on_submit_callback = callback
        self.component.on_submit = callback

    def get_component(self):
        """Get the box component for layout."""
        return self.box
