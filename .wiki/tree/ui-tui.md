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
