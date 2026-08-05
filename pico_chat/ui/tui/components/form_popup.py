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
from pico_chat.ui.tui.components.form import (
    FormContainer, FormField, TextField, TextAreaField, RadioListField, ProfileListField,
)
from pico_chat.ui.tui.actions import Action, Actions
from pico_chat.ui.tui.events import KeyEvent, TickEvent, PasteEvent
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.events import MouseEvent
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.navigation import ModalHost
from pico_chat.ui.tui.screen import Screen


# ── lightweight action descriptors for the bottom bar ──────────

@dataclass(frozen=True)
class _FormAction:
    key: str
    label: str

    def format(self) -> str:
        return f"[{self.key}] {self.label}"


_OK_ACTION = _FormAction("Enter", "ok")
_CANCEL_ACTION = _FormAction("Esc", "cancel")
_NEW_PROFILE_ACTION = _FormAction("New", "new profile")


class FormPopupScreen(Screen):
    """Screen adapter that lets ``ModalHost`` own a ``FormPopup`` lifecycle."""

    def __init__(self, popup: "FormPopup"):
        super().__init__(popup)
        self.popup = popup

    def on_leave(self) -> None:
        self.popup._hide_state()


class FormPopup(Component):
    """A centered modal overlay that displays form fields.

    Renders via the compositor overlay system.  Consumes all input while
    visible — ``on_submit(values)`` on OK, ``on_cancel()`` on Esc.
    """

    def __init__(self, compositor: Optional[Any] = None, id: Optional[str] = None,
                 max_width_ratio: float = 0.72, max_height_ratio: float = 0.7,
                 modal_host: Optional[ModalHost] = None):
        super().__init__(id)
        self.max_width_ratio = max_width_ratio
        self.max_height_ratio = max_height_ratio

        self.is_visible = False
        self._form_container: Optional[FormContainer] = None
        self._on_submit: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_cancel: Optional[Callable[[], None]] = None
        self._on_action: Optional[Callable[[Action], None]] = None
        self._on_new_profile: Optional[Callable[[], None]] = None
        self._error_msg: Optional[str] = None
        self._background_focus_scope = None
        self._background_focus_index = None

        # Box wrapping the FormContainer (built in _build_box)
        self._box: Optional[Box] = None

        # Compositor integration
        self.compositor = compositor
        self.modal_host = modal_host
        self._modal_screen = FormPopupScreen(self) if modal_host else None
        self._registered_with_compositor = False

    # ── compositor registration ────────────────────────────────

    def set_compositor(self, compositor):
        self.compositor = compositor

    def set_modal_host(self, modal_host: ModalHost):
        self.modal_host = modal_host
        self._modal_screen = FormPopupScreen(self)

    def _sync_compositor(self):
        if self.modal_host:
            return
        if not self.compositor:
            return
        if self.is_visible and not self._registered_with_compositor:
            self.compositor.add_overlay(self)
            self._registered_with_compositor = True
        elif not self.is_visible and self._registered_with_compositor:
            self.compositor.remove_overlay(self)
            self._registered_with_compositor = False

    # ── show / hide ────────────────────────────────────────────

    def _suspend_background_focus(self):
        if not self.compositor or not hasattr(self.compositor, "event_router"):
            return
        scope = self.compositor.event_router.focus_scope
        if scope is None or not scope.active:
            return
        self._background_focus_scope = scope
        self._background_focus_index = scope.focused_index
        scope.manager.clear()

    def _restore_background_focus(self):
        scope = self._background_focus_scope
        index = self._background_focus_index
        self._background_focus_scope = None
        self._background_focus_index = None
        if scope is not None and index is not None:
            scope.manager.focus(index)

    def show(self, title: str, fields: List[FormField],
             on_submit: Callable[[Dict[str, Any]], None],
             on_cancel: Optional[Callable[[], None]] = None,
             on_action: Optional[Callable[[Action], None]] = None,
             on_new_profile: Optional[Callable[[], None]] = None,
             field_spacing: int = 1):
        """Display the form popup.

        Args:
            title:   Box title.
            fields:  List of ``FormField`` instances.
            on_submit: Called with ``{field.label: field.get_value()}``.
            on_cancel: Called when the user dismisses the form (optional).
            on_action: Optional semantic action sink, called before legacy callbacks.
        """
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self._on_action = on_action
        self._on_new_profile = on_new_profile
        self._error_msg = None
        self._suspend_background_focus()

        self._form_container = FormContainer(fields, field_spacing=field_spacing)
        self._box = Box(
            self._form_container,
            title=title,
            fg=theme.PERMISSION,
            focused=True,
            actions=([_NEW_PROFILE_ACTION, _OK_ACTION, _CANCEL_ACTION]
                     if on_new_profile else [_OK_ACTION, _CANCEL_ACTION]),
            focus_in_padding=True,
        )
        self._form_container.focus_scope.enter()

        self.is_visible = True
        self._center_and_layout()
        if self.modal_host and self._modal_screen:
            self.modal_host.present_screen(self._modal_screen)
        else:
            self._sync_compositor()
        if self.compositor:
            self.compositor.request_render()

    def hide(self):
        if self.modal_host and self._modal_screen is not None:
            if self.modal_host.current is self:
                self.modal_host.dismiss_screen(self._modal_screen)
                return
        self._hide_state()

    def _hide_state(self):
        was_visible = self.is_visible
        self.is_visible = False
        if self._form_container:
            self._form_container.focus_scope.leave()
        self._form_container = None
        self._box = None
        self._restore_background_focus()
        self._sync_compositor()
        if was_visible and self.compositor:
            self.compositor.request_render()

    @property
    def dirty(self) -> bool:
        return bool(self._form_container and self._form_container.dirty)

    def reset(self):
        if self._form_container:
            self._form_container.reset()
            self._error_msg = None
            self._center_and_layout()
            self.mark_changed()

    # ── layout ─────────────────────────────────────────────────

    def _center_and_layout(self):
        if not self.compositor or not self._form_container or not self._box:
            return

        term_w = self.compositor.width
        term_h = self.compositor.height

        # Preferred width: longest label + input space + padding.
        # Give text fields room to breathe; the form must be wide enough to
        # comfortably type server names/URLs into.
        content_w = 56  # generous default so the form isn't cramped
        if self._form_container.fields:
            for f in self._form_container.fields:
                label_len = len(f.label) + 4
                if isinstance(f, TextField):
                    label_len += 34  # space for the input value
                content_w = max(content_w, label_len)

        popup_w = min(int(term_w * self.max_width_ratio), content_w + 6)
        popup_w = max(popup_w, 40)

        # Preferred height: all fields + borders + error line
        inner_h = self._form_container.get_preferred_height(popup_w - 4)
        error_h = 1 if self._error_msg else 0
        popup_h = min(
            int(term_h * self.max_height_ratio),
            inner_h + 2 + 2 * self._box.padding + error_h + 2,
        )
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
            if f.model is not None and not f.validate():
                if f.model.error == "This field is required":
                    self._error_msg = f"'{f.label}' is required"
                else:
                    self._error_msg = f"'{f.label}': {f.model.error}"
                self._center_and_layout()
                self.mark_changed()
                return False
            if f.required:
                val = f.get_value()
                if val is None or (isinstance(val, str) and not val.strip()):
                    self._error_msg = f"'{f.label}' is required"
                    self._center_and_layout()
                    self.mark_changed()
                    return False

        values = {f.label: f.get_value() for f in self._form_container.fields}
        self.hide()
        if self._on_action:
            self._on_action(Action(Actions.SUBMIT, values))
        self._on_submit(values)
        return True

    def _do_cancel(self):
        self.reset()
        self.hide()
        if self._on_action:
            self._on_action(Action(Actions.CANCEL))
        if self._on_cancel:
            self._on_cancel()

    def _new_profile(self) -> bool:
        if not self._on_new_profile:
            return False
        self._on_new_profile()
        self._error_msg = None
        self._center_and_layout()
        self.mark_changed()
        return True

    # ── input ──────────────────────────────────────────────────

    def handle_input(self, event: Any) -> bool:
        if not self.is_visible:
            return False

        if isinstance(event, TickEvent):
            return bool(self._form_container and self._form_container.handle_input(event))

        # Bracketed paste — must reach the focused field's editor.
        if isinstance(event, PasteEvent):
            if self._form_container:
                return self._form_container.handle_input(event)
            return True

        # Keyboard
        if isinstance(event, (str, KeyEvent)):
            key = event.key if isinstance(event, KeyEvent) else event
            # Terminal Alt+Enter commonly arrives as ESC followed by CR/LF.
            # Treat it as Enter so modal input cannot leak to the application.
            if key in ("\x1b\r", "\x1b\n", "\x1b[13;3u", "\x1b[27;3;13~"):
                # Alt+Enter is a consumed modifier variant, not the modal's
                # submit command.  This prevents terminal protocol sequences
                # from unexpectedly closing a form.
                if self._form_container:
                    self._form_container.handle_input(KeyEvent("\r"))
                return True
            if key == "\x1b":  # Escape
                self._do_cancel()
                return True
            if key == "\r" or key == "\n":  # Enter
                fc = self._form_container.get_focused_field() if self._form_container else None
                if fc and isinstance(fc, TextAreaField):
                    # Multiline fields insert a newline on Enter.
                    return self._form_container.handle_input(event)
                if self._form_container and self._form_container.activate_focused():
                    return True
                if fc is not None and not self._is_last_field(fc):
                    # Enter advances to the next field; on the last field it submits.
                    # This gives predictable validation: fill fields, then Enter on
                    # the final field (or click [Enter] ok) to validate.
                    if self._on_action:
                        self._on_action(Action(Actions.NEXT))
                    self._form_container.focus_next()
                    return True
                return self._try_submit()
            if key == "\x1b[Z":  # Shift+Tab — let FormContainer handle
                if self._form_container:
                    return self._form_container.handle_input(event)
            if key == "\t":  # Tab — let FormContainer handle
                if self._form_container:
                    return self._form_container.handle_input(event)

            # Clear error on any keypress
            if self._error_msg:
                self._error_msg = None

            # Route to form container
            if self._form_container:
                return self._form_container.handle_input(event)

        # Mouse
        if isinstance(event, MouseEvent) and event.pressed:
            if event.button in (64, 65) and self._form_container:
                max_scroll = max(0, self._form_container._total_height - self._form_container.height)
                delta = max(1, event.scroll_delta) * 3
                if event.button == 64:
                    self._form_container._scroll_offset = max(0, self._form_container._scroll_offset - delta)
                else:
                    self._form_container._scroll_offset = min(
                        max_scroll, self._form_container._scroll_offset + delta)
                self._form_container.mark_changed()
                return True
            if event.drag:
                return True
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
                            elif action.key == "New":
                                return self._new_profile()

                # Click on a field to focus it
                if self._form_container:
                    self._handle_field_click(event)

        # Consume all input when visible
        return True

    def _is_last_field(self, field) -> bool:
        if not self._form_container or not self._form_container.fields:
            return True
        return self._form_container.fields[-1] is field

    def _handle_field_click(self, event: MouseEvent):
        """Focus the field that was clicked."""
        if not self._form_container:
            return
        container = self._form_container
        for i, field in enumerate(container.fields):
            fy = container._field_offsets[i] - container._scroll_offset
            fh = container._field_heights[i]
            field_y = self._box.y + 1 + self._box.padding_y + fy
            field_bottom = field_y + fh
            if field_y <= event.y < field_bottom:
                container._set_focus(i)
                # ProfileListField owns row buttons and must receive the click
                # itself. Generic radio handling would otherwise select the
                # row before its rename/duplicate/remove hit testing runs.
                if isinstance(field, ProfileListField):
                    field.handle_input(event)
                elif isinstance(field, RadioListField):
                    option_index = event.y - field_y - 1
                    if 0 <= option_index < len(field.options):
                        field.set_value(option_index)
                else:
                    field.handle_input(event)
                container._ensure_focus_visible()
                return

    # ── rendering ──────────────────────────────────────────────

    def render(self, buffer: Buffer):
        if not self.is_visible or not self._box:
            return

        # Form fields can change their preferred height dynamically (for
        # example, adding/removing a profile row). Recalculate the popup and
        # all field positions before drawing rather than painting over stale
        # lines from the previous layout.
        self._center_and_layout()
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
