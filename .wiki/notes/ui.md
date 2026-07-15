# UI Architecture

Pico's TUI is built from scratch — no curses, no third-party TUI framework. It owns the full rendering pipeline.

---

## Layer Stack

```
chatTUI (app.py)
  └─ Compositor (tui/compositor.py)       ← render loop, FPS throttle
       ├─ Container layout (tui/container.py)
       │    ├─ ChatHistoryPanel           ← scrollable message list
       │    ├─ InputComponent             ← multi-line editor
       │    └─ DebugLogPanel (optional)   ← dev logging
       └─ Overlays (floating, on top)
            ├─ SelectionMenu              ← autocomplete dropdowns
            └─ Popup                      ← centered text popups (/help, /status)
```

## Compositor (`tui/compositor.py`)

- Runs an async render loop at ~30 FPS
- Manages overlay stacking (e.g., permission prompts, menus, popups)
- Tracks dirty state; only redraws when something changed
- `Compositor.invalidate()` — marks the frame as needing redraw
- `add_overlay(component)` / `remove_overlay(component)` — register floating components rendered on top of the main tree

## Popup System (`tui/components/popup.py`)

Centered overlay popups for commands that benefit from floating display rather than chat history messages.

- `Popup` extends `Component`, built on `Box` + `TextComponent` component tree
- `show(title, content)` — displays popup, auto-centers, registers with compositor
- `hide()` — dismisses popup, unregisters from compositor
- **Action bar**: `[Esc] close` rendered by Box's native action system — identical positioning and style to message box action bars
- **Clickable action bar**: hit regions computed by Box during render; click detection uses Box's `_action_hit_regions`
- **Scroll**: arrow keys (±1), mouse wheel (±3), clamped to bounds
- `PopupAction(key, label)` dataclass — compatible with Box's `.format()` action protocol, no MsgAction coupling
- Scroll position indicator overlaid on bottom-right when content overflows
- Input interception: when popup is visible, `handle_global_input()` routes all input to the popup
- Auto-sizing: `max_width_ratio` / `max_height_ratio` control popup dimensions relative to terminal
- Currently used by: `/help` (command list), `/status` (async with placeholder), `/tools`, `/permissions`, `/debug` help

## Forms System (`tui/components/form.py`, `form_popup.py`)

Modal form dialogs for interactive input (server configuration, settings, etc.).

### Field Types (`form.py`)

| Field | Rendered | Value Type | Navigation |
|-------|----------|------------|------------|
| `ToggleField` | `[x] Label` / `[ ] Label` | `bool` | Space/Enter toggles |
| `TextField` | `Label: value_cursor` | `str` | Typing, arrow keys, Home/End |
| `TextAreaField` | Label + multiline content | `str` | Enter inserts newline, arrows navigate |
| `CheckboxListField` | `Label:` + `[ ]`/`[x]` per option | `List[int]` | Up/Down moves cursor, Space/Enter toggles |
| `RadioListField` | `Label:` + `()`/`(x)` per option | `Optional[int]` | Up/Down moves cursor, Space/Enter selects |

All fields extend `FormField` ABC with: `get_value()`, `set_value()`, `render()`, `handle_input()`, `get_preferred_height()`.

### FormContainer (`form.py`)

Vertical layout manager for a list of fields:
- **Tab / Shift+Tab** moves focus between fields
- **Up / Down arrows** also navigate between fields
- Input routes to the focused field
- Scroll offset for forms taller than available height
- 1-row spacing between fields

### FormPopup (`form_popup.py`)

Modal overlay wrapping a `FormContainer` inside a `Box`:
- `show(title, fields, on_submit, on_cancel)` — displays form, registers with compositor
- `hide()` — dismisses, unregisters from compositor
- **Action bar**: `[Enter] ok` / `[Esc] cancel` in bottom border
- **Validation**: `required=True` on fields blocks submit with error message
- **Enter behavior**: on `TextField` moves to next field; on other fields submits
- **Mouse**: clickable OK/Cancel buttons, click-to-focus fields
- Callback receives `Dict[str, Any]` mapping field labels to values

### Usage Pattern

```python
from pico_chat.ui.tui.components.form import TextField, RadioListField
from pico_chat.ui.tui.components.form_popup import FormPopup

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
```

Currently used by: `/server add` (no-args form mode)

## Debug Panel

The debug console is a `DebugLogPanel` (extends `TextComponent`) wrapped in a `Box`.

- `DebugLogPanel` receives log entries via `TuiLogHandler`
- Toggled visible/hidden via Hsplit layout mutation in `toggle_debug_console()`
- Auto-scrolls to bottom on new log entries
- Planned: move to a separate conversation (not popup)

## Buffer (`tui/buffer.py`)

- Grid of `Cell` objects (character + foreground RGB + background RGB)
- `SubBuffer` — a viewport into a parent buffer, enables clipping
- Components write to their allocated `SubBuffer`; compositor merges and flushes to terminal

## Components (`tui/components/`)

All components extend `Component` (base.py):
- `render(buffer)` — draw self into SubBuffer
- `handle_input(event)` — process keyboard/mouse events
- `dirty` flag — set when state changes, cleared after render

Key components:
- `Box` — bordered wrapper with optional title and action buttons
- `TextComponent` — static/scrollable text display
- `SelectionMenu` — floating dropdown with fuzzy filtering
- `InputComponent` — multi-line editor (see below)
- `DebugLogPanel` — scrolling log display
- `MarkdownComponent` — live markdown renderer (see [Markdown Rendering](#markdown-rendering) below)

## Input Component (`tui/components/input/`)

The most complex component. Responsibilities are split across sub-modules:

| Module | Responsibility |
|--------|---------------|
| `input.py` | Coordinator; cursor animation, menu orchestration, schema-driven parameter hints |
| `text_buffer.py` | Text storage, undo/redo |
| `input_handlers.py` | Keyboard, mouse, paste events |
| `command_completion.py` | `/command` autocomplete |
| `subcommand_completion.py` | Subcommand suggestions |
| `context_completion.py` | Context-aware suggestions |
| `path_completion.py` | File path autocomplete |
| `argument_completion.py` | **Generic argument completer** — reads `Command.params` from registry, fuzzy filters completions per argument index |
| `scroll_manager.py` | Scroll offset for large input |
| `cursor_renderer.py` | Cursor visibility and animation |
| `coordinate_mapper.py` | Screen position → text offset |

### Schema-Driven Parameter Hints

When typing a `/command`, the input component shows grey hints for upcoming parameters. This is driven by the `Param` dataclass on each `Command`:

1. `resolve_command(parts)` walks the command/subcommand tree to find the deepest matching `Command` and the argument offset
2. `_get_parameter_hint()` reads `cmd.params[arg_index:]` and joins them with spaces
3. Hints are rendered at the end of the current text (not at the cursor position)
4. The current argument being typed is skipped from the hints

## Mouse Interaction Model

The TUI supports full mouse interaction via ANSI SGR mode (`?1006h`).

### Text Selection
- **Start**: Click on message content area → `start_selection()` records anchor position
- **Drag**: Mouse move events → `update_selection()` extends highlight (throttled at 50ms for performance)
- **End**: Mouse release → `end_selection()` finalizes selection and auto-copies to clipboard
- **Yank**: Press `y` to copy current selection to clipboard at any time
- Selection is rendered as a reverse-video overlay via `_render_selection()` using segment-level fast-skip optimization
- Hit testing uses a cached line map (`_line_map_cache`) invalidated on scroll/message changes

### Action Button Clicks
- Action buttons (e.g. `[c] copy`) in box bottom borders are clickable
- `_hit_test_action_bar()` computes button hit regions on-demand (replicates Box border layout calculation)
- Clicking triggers the action with a brief **reverse-video flash** feedback (150ms)
- Flash is managed by `_flash_msg` / `_flash_action_key` / `_flash_until` on `ChatHistoryPanel`
- Box renders the flash by checking `parent_msg._flash_action_key` and applying `reverse=True`

## Message Types (`tui/msg_types.py`, `chat_message.py`)

Every message displayed in the chat history has a `MsgType` that controls its title, border color, content color, and available action buttons.

### MsgType Hierarchy

| Class | Title | Frame Color | Actions |
|-------|-------|-------------|---------|
| `MsgType` | *(base)* | DEFAULT | none |
| `UserMsg` | "user" | USER | COPY, EDIT, DELETE, STEER |
| `PicoMsg` | "pico" | PICO | COPY, EDIT, RETRY, STOP (→DELETE after finalize), PAUSE, RESUME |
| `ThinkingMsg` | "thinking" | MUTED | COPY, EDIT, RETRY, DELETE, STOP, PAUSE, RESUME |
| `SysMsg` | "system" | MUTED | COPY, DELETE |
| `SysMsgError` | "error" | ERROR | COPY, EDIT, DELETE |
| `SysMsgWarning` | "warning" | WARNING | COPY, DELETE |
| `ToolCallMsg` | "tool" | WARNING | OUTPUT, COPY, DELETE |
| `ToolDraftMsg` | "tool" | MUTED | none |
| `AskPermissionMsg` | "permission" | PERMISSION | ALLOW, DENY, OUTPUT, COPY |

`ThinkingMsg` and `SysMsgError/Warning` extend `PicoMsg` / `SysMsg` — they inherit defaults and override only what differs.

### MsgAction Enum

Each action has a keyboard shortcut key and a label displayed in the box border:

| Action | Key | Label |
|--------|-----|-------|
| `COPY` | `c` | copy |
| `DELETE` | `d` | delete |
| `EDIT` | `e` | edit |
| `RETRY` | `r` | retry |
| `STOP` | `s` | stop |
| `ALLOW` | `a` | allow |
| `DENY` | `x` | deny |
| `OUTPUT` | `o` | output |
| `STEER` | `t` | steer |
| `PAUSE` | `p` | pause |
| `RESUME` | `u` | resume |

### How to Add a New Message Type

1. **Define the class** in `pico_chat/ui/tui/msg_types.py`:
   ```python
   class MyMsg(MsgType):
       name = "my_type"
       title = "my title"           # shown in box border
       frame_color = "WARNING"      # key in theme dict (colors.py)
       content_color = "MUTED"      # optional; None = default text color
       actions = [MsgAction.COPY, MsgAction.DELETE]
   ```
   Use an existing class as a base if it's a variant (e.g. `class MyMsg(SysMsg)`).

2. **Import it** wherever you create messages (usually `app.py` already imports all types).

3. **Use it** when adding to the chat panel:
   ```python
   ui.chat_history_panel.add_message("text", msg_type=MyMsg())
   ```

4. **Handle any new actions** — if you added a new `MsgAction`, wire up a handler callback in `ChatHistoryPanel` (e.g. `on_my_action`) and connect it in `app.py` via `ChatActionHandlers`.

### How Messages Are Displayed

`ChatHistoryPanel.add_message(text, msg_type, title=None, ...)` creates a `Message` object and appends it.
`Message` wraps a `TextComponent` inside a `Box`. The `Box` renders the border, title, and action buttons.
`ChatHistoryPanel` is the owner of the message list — it handles layout, focus, scrolling, and width-change reformatting.

---

## Commands (`commands.py`)

Slash commands typed by the user (e.g. `/server`, `/status`, `/tools`, `/help`).

Server management commands (`ServerAddCommand`, `ServerUseCommand`, etc.) are thin UI adapters — all business logic lives in `harness/server_service.py`. The commands call the service and render the results.

### Registered Commands

`help`, `clear`, `compact`, `exit`, `stop`, `resume`, `prefill`, `status`, `server`, `tools`, `debug`, `permissions`, `openrouter`, `cd`, `pwd`

### Structure

- `Param` dataclass — defines a command argument: `name`, `completions` (static list or callable returning list), `path` (filesystem scan if True), `required` (default False)
- `Command` — base class. Constructor: `Command(name, description, subcommands={}, params=[])`.
- `Command.resolve_command(parts)` — walks subcommand tree, returns `(deepest_cmd, arg_offset)` for hint/completion resolution
- `Command.get_completions(arg_index)` — resolves completions from `Param` schema (static list, callable, or `path=True` filesystem scan via `_scan_dirs()`)
- `execute(ui, args)` — async method to override. `ui` is the `chatTUI` instance; `args` is a list of string tokens after the command name.
- `COMMANDS: Dict[str, Command]` — module-level registry mapping name → instance.
- `handle_command(ui, text)` — strips the leading `/`, looks up `COMMANDS`, calls `execute`.

### Subcommands

Commands with sub-operations (e.g. `/server add`, `/server remove`) pass a `subcommands` dict to the `Command` constructor. The parent `execute()` reads `args[0]` and dispatches to the matching sub-command instance.

### How to Add a New Command

1. **Define the class** in `pico_chat/ui/commands.py`:
   ```python
   class MyCommand(Command):
       def __init__(self):
           super().__init__("mycommand", "One-line description",
               params=[
                   Param("NAME", required=True),
                   Param("TYPE", completions=["type1", "type2"], required=True),
                   Param("PATH", path=True),
               ])

       async def execute(self, ui: ChatUIProtocol, args: List[str]):
           # use ui.chat_history_panel.add_message() to show output
           ui.chat_history_panel.add_message("hello", msg_type=SysMsg())
   ```

   The `Param` definitions automatically provide:
   - **Parameter hints** shown as grey text after the command name
   - **Fuzzy autocomplete** in the argument completion menu
   - **Filesystem scanning** when `path=True`

2. **Register it** in the `COMMANDS` dict at the bottom of the file:
   ```python
   COMMANDS: Dict[str, Command] = {
       ...
       "mycommand": MyCommand(),
   }
   ```

3. That's it. The command is now:
   - Callable as `/mycommand` in the chat input
   - Listed by `/help` automatically
   - Available in the input autocomplete (fed by `get_command_list()`)

For commands with subcommands, instantiate sub-command classes and pass them as a dict to the `subcommands` parameter. See `ServerCommand` in `commands.py` for an example.

### Hiding a Command from `/help`

Prefix the name with `_` (e.g. `"_internal"`). `HelpCommand` skips names starting with `_`.

## Terminal I/O (`tui/terminal.py`)

- Sets raw mode, captures mouse/keyboard events
- `ANSI` constants for escape codes
- `Terminal.write()` flushes the buffer to stdout

## Colors and Layout

- `tui/colors.py` — `RGB` class, theme dictionary, hex parsing
- `tui/layout_utils.py` — `wrap_text()`, `display_width()` (wcwidth-aware for Unicode), `strip_ansi()`
- `tui/container.py` — `Vsplit`/`Hsplit` layout with int, float (%), and string size units

## Markdown Rendering

Live markdown rendering for chat messages, added to support streaming output with rich formatting.

### Modules

- `tui/components/markdown.py` — parser + `MarkdownComponent` (re-parses on every `update()`, suitable for streaming)
- `tui/ascii_table.py` — `AsciiTable` renders markdown tables with squared-style borders
- `tui/syntax_highlight.py` — `highlight_line(line, lang)` tokenises code blocks for coloring

### Pipeline

1. `BlockParser` splits raw text into blocks (paragraphs, headers, code fences, lists, quotes, HR, tables)
2. `InlineParser` parses inline `**bold**`, `*italic*`, `` `code` ``, `[text](url)`
3. `Markdown.parse()` returns `List[List[StyledSegment]]` (display lines)
4. `MarkdownComponent` wraps lines to the component width (word-wrap for prose, hard-break for code blocks/tables)
5. `render()` writes styled segments to the buffer

### Styling

Styles are driven by `pico_cfg.config.markdown_styles` (see [config.md](./config.md)). Each element (`header1`–`header6`, `bold`, `italic`, `code`, `code_block`, `quote`, `list`, `hr`, `table`, `link`, `paragraph`) maps to `fg`/`bg`/`bold`/`reverse`.

### Tables

Markdown tables (`| ... | ... |` with a `---` separator row) are detected by `BlockParser`, grouped into `TableLine` runs, and rendered via `AsciiTable` with the `squared` style. Table lines are rendered with `code_block=True` so the wrapper hard-breaks instead of word-wrapping, preserving column alignment.
