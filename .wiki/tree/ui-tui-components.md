# pico_chat/ui/tui/components/ — UI Components

Reusable TUI widgets. All extend `Component` from `base.py`.

See [notes/ui.md](../notes/ui.md) for the component model overview.

---

## Base

### `base.py`
`Component` abstract class — the contract all widgets implement.
- `render(buffer: SubBuffer)` — draw into allocated buffer area
- `handle_input(event)` — return `True` if event was consumed
- `dirty` — flag set when state changes; compositor redraws on next frame
- `set_layout(x, y, w, h)` — called by container before render

---

## Widgets

### `text.py`
`TextComponent` — displays static or dynamically updated text with auto-scroll.
Used as base for `ChatHistoryPanel`.
`Label` — reusable text widget with ANSI-aware wrapping and left, center, or
right horizontal alignment plus top, center, or bottom vertical alignment.

### `box.py`
`Box` — wraps another component with a border, optional title, and optional action buttons.
Focus state changes border color. Actions appear as labeled buttons in the border.
Constructor params include `compact_when_unfocused` (render without borders when unfocused) and `parent_msg` (link to owning message).
`_render_compact_to_subbuffer()` — compact borderless render path.
`_action_hit_regions` — tracks screen positions of action buttons during render for click detection.
Supports **action flash feedback**: when `parent_msg._flash_action_key` is set, the matching action button renders with `reverse=True` for brief visual feedback.

### `button.py`
`Button` — focusable control activated by Enter, Space, or a left mouse click;
supports disabled state, callbacks, and semantic `activate` actions. Keyboard
activation consumes canonical `KeyEvent` values while retaining raw-string
compatibility.

### `choice.py`
`Checkbox` — focusable boolean control with keyboard and mouse toggling.
`RadioGroup` — focusable single-selection list with arrow-key navigation and
keyboard or mouse selection. Both normalize canonical `KeyEvent` values while
retaining raw-string compatibility.

Popup, form, debug, config, and action-bar controls also normalize canonical
`KeyEvent` values while retaining their existing raw-string and mouse paths.

### `list_view.py`
`SelectionModel` stores ordered items and a selected index independently of
rendering. `ListView` provides focusable keyboard/mouse navigation with
scrolling, while `Select` adds a compact field that opens an inline list. These
widgets consume canonical `KeyEvent` values while retaining raw-string input.

### `table_view.py`
`TableView` renders measured or explicitly sized columns with a fixed header,
vertical row scrolling, horizontal clipping, and mouse/keyboard row selection.
Keyboard navigation consumes canonical `KeyEvent` values.

### `bars.py`
`BarStyle` centralizes bar padding and theme colors. `StatusBar` renders left
and right status text, while `ActionBar` renders keyboard/mouse actions with
shared spacing and focus styling.

### `menu.py`
`SelectionMenu` — floating dropdown list.
- Fuzzy search filtering via `fuzzy.py`
- Keyboard navigation (up/down/enter/escape)
- Used for autocomplete popups in `InputComponent`

### `input/basic.py`
Reusable cursor-aware text editors:
- `LineInput` — single-line value editing with placeholder and reverse-video cursor
- `BoxInput` — multiline value editing with cursor navigation and boxed layout support
Both editors consume canonical `KeyEvent` metadata while retaining raw-string
compatibility.
`TextField` and `TextAreaField` delegate their editing behavior to these components.

### `debug_panel.py`
`DebugLogPanel` — scrolling log display (extends `TextComponent`).
- Renders a capped list of log lines
- Max line length enforced to prevent layout breakage
- Auto-scrolls to bottom on new entries (`auto_scroll_bottom=True`)
- Toggled visible/hidden via Hsplit layout in `app.py`

### `config_overlay.py`
`ConfigOverlay` — server configuration tab component.
- Renders server rows and dispatches add, edit, remove, and use callbacks
- Supports keyboard shortcuts, mouse actions, and scrolling
- Keyboard shortcuts consume canonical `KeyEvent` metadata while retaining
	raw-string compatibility

### `popup.py`
`Popup` — centered overlay popup built on `Box` + `TextComponent`.
- Component tree: `Popup` → `Box` (borders/title/action bar) → `TextComponent` (content)
- `show(title, content)` — displays popup, auto-centers, registers with compositor
- `PopupScreen` — adapts read-only popup visibility to `ModalHost` lifecycle ownership

### `form.py`
Form field components and layout container.
- `FormField` — ABC for all fields: `get_value()`, `set_value()`, `render()`, `handle_input()`
- `InputResult` — explicit routing result with `handled`, optional sibling
	`focus` intent, and `redraw`; legacy boolean handlers are adapted with
	`from_legacy()`
- Fields can bind to a standalone `FieldModel` for value, dirty, reset, and synchronous validation state.
- `ToggleField` — `[x]`/`[ ]` boolean toggle
- `TextField` — single-line text input with cursor
- `TextAreaField` — multiline text input with cursor navigation
- `CheckboxListField` — multi-select `[ ]`/`[x]` list
- `RadioListField` — single-select `()`/`(x)` list
- `InlineChoiceField` / `HorizontalSelector` — compact horizontal selector
- `FormActionField` / `ButtonField` — clickable and keyboard-activatable form action
- `ProfileListField` — legacy profile list retained for compatibility
- `ProfileList` — composable dynamic list of `ProfileRow` controls plus a
	real create button; selection and action focus are separate
- `ProfileRow` — profile selection control composed with rename, duplicate, and
	remove `Button` leaves
- `FormContainer` — vertical layout manager with Tab/Shift+Tab focus
	navigation, scroll offset, dynamic height recomputation, and `InputResult`
	focus-intent routing

`button.py` provides the reusable `Button` component. Use `activate()` as the
single semantic action path for Enter, Space, and left mouse click.

`input_result.py` defines `InputResult` and `FocusIntent` for composable
controls. A leaf returns a focus intent only when it reaches a local edge;
the nearest `FormContainer` performs the sibling move.

`profile_editor_model.py` provides `ProfileEditorModel`, the persistence and
selection boundary used by the permissions editor. It isolates drafts,
immediately applies and saves edits, and exposes profile lifecycle operations
without requiring a TUI or widget.

### `field_models.py`
Standalone form value models independent of rendering and layout.
- `FieldModel` — generic value, initial value, dirty tracking, reset, required validation, and custom synchronous validation.
- `validate_async()` — optional asynchronous validation extension after synchronous checks.
- `TextFieldModel`, `BoolFieldModel`, `ChoiceFieldModel` — typed convenience models for common field values.

### `form_schema.py`
Declarative construction helpers for regular form fields.
- `FormFieldSpec` — describes field label, kind, value, options, and validation callbacks.
- `build_field()` / `build_fields()` — construct existing field widgets in schema order.

### `form_popup.py`
`FormPopup` — modal overlay wrapping a `FormContainer` inside a `Box`.
- `FormPopupScreen` — `Screen` adapter for `ModalHost` lifecycle ownership; compositor-only usage remains supported.
- `show(title, fields, on_submit, on_cancel)` — displays form, registers with compositor
- Action bar: `[Enter] ok` / `[Esc] cancel`
- Required and model validation with error message overlay
- `dirty` / `reset()` expose and restore form state; cancel resets before dismissal
- Enter on TextField moves to next field; Enter on other fields submits
- Mouse: clickable actions, click-to-focus fields
- Used by: `/server add` (no-args form mode)
- Optional semantic action sink emits `submit`, `cancel`, and `next` while legacy callbacks remain supported
- `hide()` — dismisses popup, unregisters from compositor
- Auto-centers based on terminal dimensions (`max_width_ratio`, `max_height_ratio`)
- **Bottom action bar** with `[Esc] close` — uses Box's native action rendering, so it looks and positions exactly like message box actions
- **Clickable action bar**: hit regions populated by Box during render; click detection reuses Box's `_action_hit_regions` coordinate system
- **Scroll**: arrow keys (±1 line), mouse wheel (±3 lines), clamped to bounds
- `PopupAction` dataclass — lightweight action compatible with Box's action format protocol (`.format()` → `[key] label`)
- Scroll position indicator (`3/20`) overlaid on bottom-right when content overflows
- Input is fully intercepted when popup is visible (all keys consumed)
- Used by `/help`, `/status`, `/tools`, `/permissions`, `/debug` help

### `markdown.py`
Live markdown parser and renderer. Parses markdown into display lines of `StyledSegment` objects, styled via `pico_cfg.config.markdown_styles`.
- `StyledSegment` — text + fg/bg/bold/reverse/code_block
- Block types: `ParagraphLine`, `HeaderLine`, `CodeBlockLine`, `UnorderedListItemLine`, `OrderedListItemLine`, `QuoteLine`, `HrLine`, `EmptyLine`, `TableLine`
- `BlockParser` — splits raw text into blocks (handles code fences, tables, lists, quotes, HR)
- `InlineParser` — parses inline `**bold**`, `*italic*`, `` `code` ``, `[text](url)`
- `Markdown` — high-level wrapper; `parse(text)` returns `List[List[StyledSegment]]`; `_render_table()` renders `TableLine` groups via `AsciiTable`
- `MarkdownComponent` — `Component` subclass; re-parses on every `update()` (suitable for streaming); segment-aware word wrapping with hard-break for code blocks
See [notes/ui.md](../notes/ui.md) for the rendering overview.

### `tab_bar.py`
`TabBar` — single-line tab bar for multi-conversation support.
- Renders tabs as: `[1] chat  [2] debug  [3] scratch ×`
- Active tab highlighted with bold + underline
- `×` close button on closeable tabs
- Mouse click to select/close tabs
- `set_callbacks(on_select, on_close)` — register tab event handlers
- `add_tab(name, closeable)` / `remove_tab(index)` — manage tabs
- `set_active(index)` — highlight a tab
- Used by: `/tab new | close | switch | list`

### `tab_view.py`
`TabView` — generic owner of tab identity, titles, closability, active selection,
and view instances. It preserves inactive views and calls `Screen` lifecycle
hooks when views are entered, suspended, resumed, or closed.
- `TabItem` — stable tab ID, title, view, and closeability metadata.
- `ActionMap` integration supports activate, close, next, and previous actions.
- Close callbacks run after the tab item and visual strip entry are removed,
  so application domain state can synchronize before replacement selection.
- Applications may keep zero tabs; `TabView.active_index` becomes `None` and
	the tab bar still exposes its new-tab control.
- `chatTUI` uses it for conversation and debug tabs while keeping
	`ConversationState` outside the widget layer.

---

## Input Subcomponent (`input/`)

The multi-line text editor. Responsibilities split across sub-modules:

### `input/input.py`
`InputComponent` — the coordinator.
- Orchestrates cursor animation, completion menu visibility, multi-line layout
- Delegates text storage to `TextBuffer`, key handling to `InputHandlers`
- Extracts canonical `KeyEvent.key` values while retaining raw-string compatibility
- Shows schema-driven parameter hints via `_get_parameter_hint()` (reads `Command.params` from registry)
- `setup_command_registry(registry)` — receives the `COMMANDS` dict from `app.py`

### `input/text_buffer.py`
`TextBuffer` — backing store for the edited text.
- Insert/delete characters and lines
- Undo/redo stack
- Cursor position as `(line, col)` offset

### `input/input_handlers.py`
Handles canonical keyboard, mouse, and paste events.
- Maps key sequences to `TextBuffer` mutations
- Uses `KeyEvent.key` for controls and `KeyEvent.text` for printable insertion
	while retaining raw-string compatibility
- Triggers completion queries on relevant keystrokes

### Completion Modules

| Module | Triggers | Notes |
|--------|----------|-------|
| `command_completion.py` | `/` at start of input | Command name fuzzy search |
| `subcommand_completion.py` | Second word after a `/` command | Subcommand suggestions |
| `context_completion.py` | Context-aware (e.g., after `./`) | Configurable trigger prefix (default: `./`) |
| `argument_completion.py` | After any command with `Param` schema | Generic fuzzy completer; reads `Command.params`, resolves argument index, filters completions via menu |
| `path_completion.py` | After `/` mid-word or explicit file path input | — |
| `server_completion.py` | After `/server` subcommand | Deprecated — superseded by `argument_completion.py` with `Param` schema |

### `input/scroll_manager.py`
Tracks vertical scroll offset when input text overflows the visible area.

### `input/cursor_renderer.py`
Renders the cursor glyph into the buffer. Manages blink animation state.

### `input/coordinate_mapper.py`
Maps screen pixel/cell coordinates back to `(line, col)` in the text buffer.
Used for mouse click positioning.
