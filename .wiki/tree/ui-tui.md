# pico_chat/ui/tui/ — Terminal Rendering Engine

Low-level TUI framework. Custom-built; not a wrapper around curses or any third-party library.

See [notes/ui.md](../notes/ui.md) for the component model and layer stack.

---

## Files

### `terminal.py`
`Terminal` — raw terminal I/O.
- Sets/restores raw mode
- Captures keyboard and mouse events (ANSI escape sequences)
- `Terminal.write(data)` — flushes bytes to stdout
- `ANSI` constants: cursor movement, color codes, clear sequences

### `events.py`
Typed event dataclasses shared by terminal input and TUI components:
`KeyEvent`, `MouseEvent`, `PasteEvent`, `ResizeEvent`, `TickEvent`, and `CommandEvent`.
`KeyEvent` is string-compatible for existing handlers while exposing `key` and
`text` metadata. `Terminal.get_input()` normalizes keyboard input before
dispatch; compositor resize notifications use `ResizeEvent`. Reusable widgets
import these event types from this module; `terminal.py` remains the input
adapter that constructs them.

### `focus.py`
`FocusManager` — owns focus for an ordered collection of interactive widgets,
including focus transitions and enabled/focusable filtering.
`FocusScope` — provides an active focus boundary with optional focus trapping
for forms and dialogs, with enter/leave lifecycle callbacks. `focus_at(x, y)`
selects the topmost focusable widget containing a laid-out coordinate.

### `router.py`
`EventRouter` — dispatches events through overlays and the component tree.
Mouse events use component layout rectangles for child-first hit testing and
handled events bubble to parents. Semantic `Action` events are dispatched
through an optional `ActionMap` before root fallback.

### `actions.py`
`Action` — immutable semantic operation with an optional payload.
`ActionMap` — binds action names to handlers independently of physical keys.

### `screen.py` and `navigation.py`
`Screen` owns a root component, optional focus/action scopes, and an optional
screen model supplied by the application.
`Navigator` manages push/pop/replace/back and screen lifecycle hooks.
`ModalHost` delegates modal ownership to the compositor overlay stack and can
present modal screens with lifecycle hooks.

### `chat_screen.py`
`ChatScreen` composes the tab bar, chat history, and input workspace while
leaving conversation state and callbacks in `chatTUI`.

### `example_screen.py`
`ExampleScreen` — minimal library-only screen demonstrating component
composition, layout, focus, semantic actions, and rendering without
application-specific state.

### `buffer.py`
`Cell` — single character with foreground and background `RGB`.
`Buffer` — 2D grid of `Cell` objects representing the full screen.
`SubBuffer` — viewport into a parent buffer; enables clipping for component rendering.
- `write_str(x, y, text, fg, bg)` — writes ANSI-aware text into the grid

### `compositor.py`
`Compositor` — orchestrates the render loop.
- Async render loop, ~30 FPS default
- `invalidate()` — marks frame dirty; next loop iteration redraws
- Overlay stack for floating UI (menus, permission prompts)
- FPS tracking
- Ctrl-C shutdown consumes canonical `KeyEvent` metadata while retaining raw
	string compatibility

### `container.py`
`Container` groups child components. Concrete: `Vsplit` (column split), `Hsplit` (row split).
- Flexible sizing: fixed integers, percentages, and auto/fill slots
- `layout()` calculates child rectangles before `render()` paints them
- `Padding` insets a child by fixed edges
- `Align` positions content using preferred or explicit dimensions
- `Stack`/`Overlay` layer children in shared geometry; later children paint on top
- `ScrollView` clips one child to a viewport and supports canonical `KeyEvent`
	keyboard navigation plus mouse scrolling
- Size policies: `Fixed`, `Percent`, `Content`, and `Fill`
- Components support `min_width`, `max_width`, `min_height`, and `max_height` constraints

### `colors.py`
`RGB` — color class with hex parsing and ANSI escape code generation.
`theme` dict — named color palette used throughout the UI.

### `layout_utils.py`
Text utilities for rendering:
- `wrap_text(text, width)` — wraps at word boundaries, ANSI-aware
- `display_width(text)` — character display width using `wcwidth` (handles Unicode/CJK)
- `strip_ansi(text)` — removes ANSI escape codes

### `fuzzy.py`
`fuzzy_score(query, candidate)` — scoring function for fuzzy search.
Used by `SelectionMenu` to rank completions.

### `msg_types.py`
`MsgType` base class and all concrete message type classes. Each type defines `title`, `frame_color`, `content_color`, and `actions`.
`MsgAction` enum — per-message action buttons (DELETE, COPY, EDIT, RETRY, STOP, ALLOW, DENY, OUTPUT, STEER, PAUSE, RESUME) with keyboard shortcut keys.
See [notes/ui.md](../notes/ui.md) for the full type table and how to add a new type.

### `ascii_table.py`
`TableStyle` — border/padding configuration with named styles (`squared`, `rounded`, `simple`, `double`).
`AsciiTable` — renders a 2-D table (headers + rows) as an ASCII string with column alignment and truncation. No external dependencies. Used by the markdown table renderer.

### `syntax_highlight.py`
Syntax highlighter for code blocks in markdown rendering.
- `highlight_line(line, lang)` — returns `List[Tuple[str, str]]` of (text, highlight-type) segments
- `_resolve_lang(lang)` — normalises language identifiers
- `_get_highlight_color(hl_type)` — maps a highlight type to an RGB color
- `_resolve_hex_color(value)` — hex string → RGB tuple

---

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| [components/](./ui-tui-components.md) | Reusable UI widgets (Box, TextComponent, InputComponent, etc.) |
