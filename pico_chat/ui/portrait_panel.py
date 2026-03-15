"""Portrait panel for the Pico-Chat TUI."""

import asyncio
from typing import Optional

from pico_chat.ui.tui.component import TextComponent, Box
from pico_chat.ui.portraits.portrait import Portrait


class PortraitPanel:
    """Manages the portrait display panel."""

    def __init__(self):
        """Initialize the portrait panel."""
        self.component = TextComponent("", id="portrait", fg=(255, 255, 0))
        self.box = Box(self.component, title="Pico")
        self.compositor: Optional[object] = None
        self._portrait = None

    def set_compositor(self, compositor):
        """Set the compositor for updates."""
        self.compositor = compositor

    def set_portrait(self, portrait_name: str):
        """Set the current portrait."""
        Portrait.set_current_portrait(portrait_name)
        self._portrait = Portrait.get_current_portrait()

    async def update_loop(self):
        """Update portrait animation."""
        if not self._portrait:
            return
            
        while self.compositor and hasattr(self.compositor, 'running') and self.compositor.running:
            image = self._portrait.get_current_frame()
            self.compositor.update_component("portrait", image)
            await asyncio.sleep(1 / self._portrait.fps)

    def get_component(self):
        """Get the box component for layout."""
        return self.box
