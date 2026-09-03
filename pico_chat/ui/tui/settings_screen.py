"""Settings screen: a tabbed workspace whose body is a master-detail panel."""

from __future__ import annotations

from typing import Any, Optional

from pico_chat.ui.tui.components.bars import StatusBar
from pico_chat.ui.tui.components.settings_panel import SettingsPanel
from pico_chat.ui.tui.components.tab_bar import TabBar
from pico_chat.ui.tui.focus import FocusScope
from pico_chat.ui.tui.screen import Screen
from pico_chat.ui.tui.scaffold import AppScaffold


class SettingsScreen(Screen):
    """Own the settings workspace layout while the app owns its state.

    Built on the shared ``AppScaffold``: tab bar on top, the master-detail
    settings panel as the guttered body, status bar pinned to the bottom.
    """

    def __init__(self, tab_bar: TabBar, panel: SettingsPanel,
                 focus_scope: FocusScope, model: Any = None,
                 status_bar: Optional[StatusBar] = None):
        self.tab_bar = tab_bar
        self.panel = panel
        self.status_bar = status_bar or StatusBar()
        self.status_bar.parent = self
        # Gutter keeps the panel content off the screen edges; the panel draws
        # its own divider between the page list and the content pane.
        self.scaffold = AppScaffold(panel, top=tab_bar, bottom=self.status_bar,
                                    gutter=(0, 1, 0, 1))
        super().__init__(self.scaffold, focus_scope=focus_scope, model=model)

    def on_enter(self) -> None:
        self.panel.mark_changed()

    # ── pane navigation helpers ─────────────────────────────────

    @property
    def active_pane(self) -> str:
        return self.panel._pane

    def focus_page_list(self) -> None:
        """Move pane focus to the left column."""
        self.panel._set_pane("list")

    def focus_content(self) -> None:
        """Move pane focus to the right (fields) pane."""
        self.panel._set_pane("content")
