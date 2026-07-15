"""
Modal form popup — a centered overlay containing form fields with OK/Cancel.

Usage::

    form = FormPopup(compositor=compositor)
    form.show(
        title="Add Server",
        fields=[
            TextField("Name", required=True),
            RadioListField("Type", options=["openrouter", "llamacpp"]),
            TextField("Model or URL", required=True),
        ],
        on_submit=lambda values: print(values),
        on_cancel=lambda: print("cancelled"),
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from pico_chat.ui.tui.components.base import Component
from pico_chat.ui.tui.components.box import Box
from pico_chat.ui.tui.components.form import FormContainer, FormField, TextField
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.terminal import MouseEvent
from pico_chat.ui.tui.colors import theme


# ── lightweight action descriptors for the bottom bar ──────────

@dataclass(frozen=True)
class _FormAction:
    key: str
    label: str

    def format(self) -> str:
        return f"[{self.key}] {self.label}"


_OK_ACTION = _FormAction("Enter", "ok")
_CANCEL_ACTION = _FormAction("Esc", "cancel")


class FormPopup(Component):
    """A centered modal overlay that displays form fields.

    Renders via the compositor overlay system.  Consumes all input while
    visible — ``on_submit(values)`` on OK, ``on_cancel()`` on Esc.
    """

    def __init__(self, compositor: Optional[Any] = None, id: Optional[str] = None,
                 max_width_ratio: float = 0.6, max_height_ratio: float = 0.7):
        super().__init__(id)
        self.max_width_ratio = max_width_ratio
        self.max_height_ratio = max_height_ratio

        self.is_visible = False
        self._form_container: Optional[FormContainer] = None
        self._on_submit: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_cancel: Optional[Callable[[], None]] = None
        self._error_msg: Optional[str] = None

        # Box wrapping the FormContainer (built in _build_box)
        self._box: Optional[Box] = None

        # Compositor integration
        self.compositor = compositor
        self._registered_with_compositor = False

    # ── compositor registration ────────────────────────────────

    def set_compositor(self, compositor):
        self.compositor = compositor

    def _sync_compositor(self):
        if not self.compositor:
            return
        if self.is_visible and not self._registered_with_compositor:
            self.compositor.add_overlay(self)
            self._registered_with_compositor = True
        elif not self.is_visible and self._registered_with_compositor:
            self.compositor.remove_overlay(self)
            self._registered_with_compositor = False

    # ── show / hide ────────────────────────────────────────────

    def show(self, title: str, fields: List[FormField],
             on_submit: Callable[[Dict[str, Any]], None],
             on_cancel: Optional[Callable[[], None]] = None):
        """Display the form popup.

        Args:
            title:   Box title.
            fields:  List of ``FormField`` instances.
            on_submit: Called with ``{field.label: field.get_value()}``.
            on_cancel: Called when the user dismisses the form (optional).
        """
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self._error_msg = None

        self._form_container = FormContainer(fields)
        self._box = Box(
            self._form_container,
            title=title,
            fg=theme.PERMISSION,
            focused=True,
            actions=[_OK_ACTION, _CANCEL_ACTION],
        )

        self.is_visible = True
        self._center_and_layout()
        self._sync_compositor()
        if self.compositor:
            self.compositor.request_render()

    def hide(self):
        was_visible = self.is_visible
        self.is_visible = False
        self._form_container = None
        self._box = None
        self._sync_compositor()
        if was_visible and self.compositor:
            self.compositor.request_render()

    # ── layout ─────────────────────────────────────────────────

    def _center_and_layout(self):
        if not self.compositor or not self._form_container or not self._box:
            return

        term_w = self.compositor.width
        term_h = self.compositor.height

        # Preferred width: longest label + option text + padding
        content_w = 40  # reasonable default
        if self._form_container.fields:
            for f in self._form_container.fields:
                # rough estimate
                label_len = len(f.label) + 4
                if isinstance(f, TextField):
                    label_len += 20  # space for input
                content_w = max(content_w, label_len)

        popup_w = min(int(term_w * self.max_width_ratio), content_w + 6)
        popup_w = max(popup_w, 30)

        # Preferred height: all fields + borders + error line
        inner_h = self._form_container.get_preferred_height(popup_w - 4)
        error_h = 1 if self._error_msg else 0
        popup_h = min(int(term_h * self.max_height_ratio), inner_h + 2 + error_h + 2)
        popup_h = max(popup_h, 6)

        self.x = max(0, (term_w - popup_w) // 2)
        self.y = max(0, (term_h - popup_h) // 2)
        self.width = popup_w
        self.height = popup_h

        # Layout box inside overlay
        self._box.set_layout(self.x, self.y, self.width, self.height)

    # ── submit / cancel ────────────────────────────────────────

    def _try_submit(self) -> bool:
        """Validate and submit.  Returns True if submitted."""
        if not self._form_container or not self._on_submit:
            return False

        # Validate required fields
        for f in self._form_container.fields:
            if f.required:
                val = f.get_value()
                if val is None or (isinstance(val, str) and not val.strip()):
                    self._error_msg = f"'{f.label}' is required"
                    self._center_and_layout()
                    self.mark_changed()
                    return False

        values = {f.label: f.get_value() for f in self._form_container.fields}
        self.hide()
        self._on_submit(values)
        return True

    def _do_cancel(self):
        self.hide()
        if self._on_cancel:
            self._on_cancel()

    # ── input ──────────────────────────────────────────────────

    def handle_input(self, event: Any) -> bool:
        if not self.is_visible:
            return False

        # Keyboard
        if isinstance(event, str):
            if event == "\x1b":  # Escape
                self._do_cancel()
                return True
            if event == "\r" or event == "\n":  # Enter — check if a text field is focused
                fc = self._form_container.get_focused_field() if self._form_container else None
                # If a text field is focused and the user presses Enter, move to next field
                # (not submit).  Shift is not easily detectable in raw mode, so use a
                # heuristic: if the focused field is NOT a TextField, Enter submits.
                if fc and isinstance(fc, TextField):
                    # Move focus to next field instead of submitting
                    self._form_container.focus_next()
                    return True
                else:
                    return self._try_submit()
            if event == "\x1b[Z":  # Shift+Tab — let FormContainer handle
                if self._form_container:
                    return self._form_container.handle_input(event)
            if event == "\t":  # Tab — let FormContainer handle
                if self._form_container:
                    return self._form_container.handle_input(event)

            # Clear error on any keypress
            if self._error_msg:
                self._error_msg = None

            # Route to form container
            if self._form_container:
                return self._form_container.handle_input(event)

        # Mouse
        if isinstance(event, MouseEvent) and event.pressed and not event.drag:
            if event.button == 0:  # Left click
                bottom_y = self.y + self.height - 1
                # Action bar click
                if event.y == bottom_y and self._box:
                    for start, end, action in self._box._action_hit_regions:
                        abs_start = self.x + start
                        abs_end = self.x + end
                        if abs_start <= event.x < abs_end:
                            if action.key == "Enter":
                                return self._try_submit()
                            elif action.key == "Esc":
                                self._do_cancel()
                                return True

                # Click on a field to focus it
                if self._form_container:
                    self._handle_field_click(event)

        # Consume all input when visible
        return True

    def _handle_field_click(self, event: MouseEvent):
        """Focus the field that was clicked."""
        if not self._form_container:
            return
        container = self._form_container
        for i, field in enumerate(container.fields):
            fy = container._field_offsets[i] - container._scroll_offset
            fh = container._field_heights[i]
            field_y = self._box.y + 1 + fy  # +1 for top border
            field_bottom = field_y + fh
            if field_y <= event.y < field_bottom:
                container._set_focus(i)
                container._ensure_focus_visible()
                return

    # ── rendering ──────────────────────────────────────────────

    def render(self, buffer: Buffer):
        if not self.is_visible or not self._box:
            return

        self._box.set_layout(self.x, self.y, self.width, self.height)
        self._box.render(buffer)

        # Error message overlay (above bottom border)
        if self._error_msg:
            err_y = self.y + self.height - 2
            err_text = f" ⚠ {self._error_msg} "
            ex = self.x + 1
            buffer.write_str(ex, err_y, err_text,
                             fg=theme.ERROR, max_width=self.width - 2)

    # ── children for dirty tracking ────────────────────────────

    @property
    def children(self):
        if self._box:
            return [self._box]
        return []
