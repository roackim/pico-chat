"""Master-detail settings panel.

Left column lists setting *pages*; the right pane shows the selected page:
a title, an optional description, and the page's fields (scrollable).  All
geometry is delegated to a ``Vsplit`` (list | divider | content); the panel
only owns selection state and pane focus routing.  Within the content pane,
the embedded ``FormContainer`` handles field-to-field navigation exactly like
a form popup does.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, List, Optional

from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.components.form import ComponentField, FormContainer
from pico_chat.ui.tui.components.layout import EmptyLine, SeparatorLine, VerticalDivider
from pico_chat.ui.tui.components.list_view import ListView
from pico_chat.ui.tui.components.text import Label
from pico_chat.ui.tui.container import Fill, Fixed, Padding, Vsplit
from pico_chat.ui.tui.events import MouseEvent


@dataclass
class SettingsPage:
    """A named group of settings shown in the right-hand pane.

    ``build_fields`` is called each time the page is selected so the fields
    always reflect current model state.
    """

    name: str
    build_fields: Callable[[], List[Any]]
    title: Optional[str] = None
    description: Optional[str] = None


class SettingsPanel(Component):
    """Two-pane settings view: page list (left) + page fields (right)."""

    focusable = True

    def __init__(self, pages: List[SettingsPage], id: Optional[str] = None,
                 left_width: int = 20, content_indent: int = 0):
        super().__init__(id)
        if not pages:
            raise ValueError("SettingsPanel requires at least one page")
        self.pages = pages
        self.left_width = max(8, left_width)
        self.content_indent = max(0, content_indent)
        self._selected = 0
        self._pane = "content"  # "list" or "content"
        self._list = ListView(
            [page.name for page in pages],
            on_select=self._on_page_select,
        )
        self._divider = VerticalDivider()
        self._content: Optional[FormContainer] = None
        self._split: Optional[Vsplit] = None
        self._build_content()

    # ── page / content management ───────────────────────────────

    @property
    def selected_page(self) -> SettingsPage:
        return self.pages[self._selected]

    def _build_content(self):
        """(Re)build the right pane for the selected page."""
        page = self.selected_page
        fields: List[Any] = []

        title = page.title or page.name
        fields.append(ComponentField(Label(title, fg=theme.PICO, wrap=False)))
        if page.description:
            fields.append(ComponentField(Label(page.description, fg=theme.MUTED)))
        fields.append(ComponentField(EmptyLine()))

        fields.extend(page.build_fields())

        self._content = FormContainer(fields, field_spacing=0)
        self._content.focus_scope.enter()
        self._rebuild_split()
        self.mark_changed()

    def _rebuild_split(self):
        """Compose the geometry split from the current content pane."""
        children: List[Component] = [self._list, self._divider]
        sizes: List[Any] = [Fixed(self.left_width), Fixed(1)]
        if self._content is not None:
            # Indent the whole content pane uniformly (including FormSections,
            # which ignore per-field ``indent``) via a left padding wrapper.
            content = self._content
            if self.content_indent:
                # Padding tuple is (top, right, bottom, left): indent the left.
                content = Padding(self._content, (0, 0, 0, self.content_indent))
            children.append(content)
            sizes.append(Fill())
        self._split = Vsplit(children, sizes)
        self._split.parent = self

    def _on_page_select(self, name: str):
        index = next(i for i, p in enumerate(self.pages) if p.name == name)
        if index != self._selected:
            self._selected = index
            self._build_content()

    def _set_pane(self, pane: str):
        if pane not in ("list", "content"):
            return
        if pane == self._pane:
            return
        self._pane = pane
        self._list.set_focused(pane == "list")
        if pane == "content" and self._content is not None:
            self._content.focus_scope.enter()
        self.mark_changed()

    # ── layout ──────────────────────────────────────────────────

    def set_layout(self, x: int, y: int, width: int, height: int):
        super().set_layout(x, y, width, height)
        self._split.set_layout(x, y, width, height)

    def layout(self):
        self._split.layout()

    # ── input ───────────────────────────────────────────────────

    def handle_input(self, event: Any) -> bool:
        if isinstance(event, MouseEvent):
            if event.pressed and event.button == 0:
                if self.x <= event.x < self.x + self.left_width:
                    self._set_pane("list")
                    return self._list.handle_input(event)
                self._set_pane("content")
                return self._content.handle_input(event) if self._content else False
            return False

        key = event.key if hasattr(event, "key") else event

        # Tab / Shift+Tab cycle between the page list and the content pane.
        if key == "\t":
            self._set_pane("list" if self._pane == "content" else "content")
            return True
        if key == "\x1b[Z":
            self._set_pane("content" if self._pane == "list" else "list")
            return True

        # When the list pane owns focus, its children get first crack; left/right
        # flow to pane switching at this level.
        if self._pane == "list":
            if key in ("\x1b[D", "h"):
                self._list.handle_input(event)
                return True
            if key in ("\x1b[C", "l"):
                self._set_pane("content")
                return True
            return self._list.handle_input(event)

        # Content pane: let the active field (e.g. ProfileList's action buttons)
        # try left/right first; only fall back to switching back to the list if
        # the field declines them.
        if key in ("\x1b[D", "h"):
            if self._content is not None and self._content.handle_input(event):
                return True
            self._set_pane("list")
            return True
        if key in ("\x1b[C", "l"):
            if self._content is not None and self._content.handle_input(event):
                return True
            return True
        return self._content.handle_input(event) if self._content else False

    # ── rendering ───────────────────────────────────────────────

    def render(self, buffer: Buffer):
        self._split.render(buffer)

    def collect_dirty_rects(self, rects):
        super().collect_dirty_rects(rects)
        self._split.collect_dirty_rects(rects)

    def clear_dirty(self):
        super().clear_dirty()
        self._split.clear_dirty()


__all__ = ["SettingsPanel", "SettingsPage"]
