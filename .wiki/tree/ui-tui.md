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

### `container.py`
`Container` abstract base. Concrete: `Vsplit` (horizontal split), `Hsplit` (vertical split).
- Flexible sizing: `int` (fixed columns/rows), `float` (percentage), `str` (e.g. `"*"` for fill)
- Allocates `SubBuffer` slices to child components

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
`MsgAction` enum — per-message action buttons (COPY, DELETE, EDIT, RETRY, STOP, ALLOW, DENY, OUTPUT) with keyboard shortcut keys.
See [notes/ui.md](../notes/ui.md) for the full type table and how to add a new type.

---

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| [components/](./ui-tui-components.md) | Reusable UI widgets (Box, TextComponent, InputComponent, etc.) |
