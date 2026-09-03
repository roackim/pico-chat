"""Open the settings workspace tab."""
from __future__ import annotations
from typing import List

from .base import ChatUIProtocol, Command


class SettingsCommand(Command):
    def __init__(self):
        super().__init__("settings", "Open the settings tab (permissions, …)")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        # chatTUI exposes the tab toggle; other hosts fall back to a popup.
        toggle = getattr(ui, "toggle_settings_tab", None)
        if callable(toggle):
            toggle()
            return
        ui.show_popup("settings", "Settings are only available in the TUI.")
