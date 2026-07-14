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

### `box.py`
`Box` — wraps another component with a border, optional title, and optional action buttons.
Focus state changes border color. Actions appear as labeled buttons in the border.
Constructor params include `compact_when_unfocused` (render without borders when unfocused) and `parent_msg` (link to owning message).
`_render_compact_to_subbuffer()` — compact borderless render path.
`_action_hit_regions` — tracks screen positions of action buttons during render for click detection.
Supports **action flash feedback**: when `parent_msg._flash_action_key` is set, the matching action button renders with `reverse=True` for brief visual feedback.

### `menu.py`
`SelectionMenu` — floating dropdown list.
- Fuzzy search filtering via `fuzzy.py`
- Keyboard navigation (up/down/enter/escape)
- Used for autocomplete popups in `InputComponent`

### `debug_panel.py`
`DebugLogPanel` — scrolling log display.
- Renders a capped list of log lines
- Max line length enforced to prevent layout breakage
- Toggled visible/hidden in the compositor overlay stack

### `markdown.py`
Live markdown parser and renderer. Parses markdown into display lines of `StyledSegment` objects, styled via `pico_cfg.config.markdown_styles`.
- `StyledSegment` — text + fg/bg/bold/reverse/code_block
- Block types: `ParagraphLine`, `HeaderLine`, `CodeBlockLine`, `UnorderedListItemLine`, `OrderedListItemLine`, `QuoteLine`, `HrLine`, `EmptyLine`, `TableLine`
- `BlockParser` — splits raw text into blocks (handles code fences, tables, lists, quotes, HR)
- `InlineParser` — parses inline `**bold**`, `*italic*`, `` `code` ``, `[text](url)`
- `Markdown` — high-level wrapper; `parse(text)` returns `List[List[StyledSegment]]`; `_render_table()` renders `TableLine` groups via `AsciiTable`
- `MarkdownComponent` — `Component` subclass; re-parses on every `update()` (suitable for streaming); segment-aware word wrapping with hard-break for code blocks
See [notes/ui.md](../notes/ui.md) for the rendering overview.

---

## Input Subcomponent (`input/`)

The multi-line text editor. Responsibilities split across sub-modules:

### `input/input.py`
`InputComponent` — the coordinator.
- Orchestrates cursor animation, completion menu visibility, multi-line layout
- Delegates text storage to `TextBuffer`, key handling to `InputHandlers`
- Shows schema-driven parameter hints via `_get_parameter_hint()` (reads `Command.params` from registry)
- `setup_command_registry(registry)` — receives the `COMMANDS` dict from `app.py`

### `input/text_buffer.py`
`TextBuffer` — backing store for the edited text.
- Insert/delete characters and lines
- Undo/redo stack
- Cursor position as `(line, col)` offset

### `input/input_handlers.py`
Handles raw keyboard, mouse, and paste events.
- Maps key sequences to `TextBuffer` mutations
- Triggers completion queries on relevant keystrokes

### Completion Modules

| Module | Triggers | Notes |
|--------|----------|-------|
| `command_completion.py` | `/` at start of input | Command name fuzzy search |
| `subcommand_completion.py` | Second word after a `/` command | Subcommand suggestions |
| `context_completion.py` | Context-aware (e.g., after `@`) | — |
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
