# UI Architecture

Pico's TUI is built from scratch — no curses, no third-party TUI framework. It owns the full rendering pipeline.

---

## Layer Stack

```
chatTUI (app.py)
  └─ Compositor (tui/compositor.py)       ← render loop, FPS throttle
       └─ Container layout (tui/container.py)
            ├─ ChatHistoryPanel           ← scrollable message list
            ├─ InputComponent             ← multi-line editor
            └─ DebugLogPanel (optional)   ← dev logging
```

## Compositor (`tui/compositor.py`)

- Runs an async render loop at ~30 FPS
- Manages overlay stacking (e.g., permission prompts, menus)
- Tracks dirty state; only redraws when something changed
- `Compositor.invalidate()` — marks the frame as needing redraw

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

## Input Component (`tui/components/input/`)

The most complex component. Responsibilities are split across sub-modules:

| Module | Responsibility |
|--------|---------------|
| `input.py` | Coordinator; cursor animation, menu orchestration |
| `text_buffer.py` | Text storage, undo/redo |
| `input_handlers.py` | Keyboard, mouse, paste events |
| `command_completion.py` | `/command` autocomplete |
| `subcommand_completion.py` | Subcommand suggestions |
| `context_completion.py` | Context-aware suggestions |
| `path_completion.py` | File path autocomplete |
| `server_completion.py` | Server name suggestions |
| `scroll_manager.py` | Scroll offset for large input |
| `cursor_renderer.py` | Cursor visibility and animation |
| `coordinate_mapper.py` | Screen position → text offset |

## Message Types (`tui/msg_types.py`, `chat_message.py`)

Every message displayed in the chat history has a `MsgType` that controls its title, border color, content color, and available action buttons.

### MsgType Hierarchy

| Class | Title | Frame Color | Actions |
|-------|-------|-------------|---------|
| `MsgType` | *(base)* | DEFAULT | none |
| `UserMsg` | "user" | USER | COPY, EDIT |
| `PicoMsg` | "pico" | PICO | COPY, RETRY, STOP (→DELETE after finalize) |
| `ThinkingMsg` | "thinking" | MUTED | COPY, RETRY, DELETE, STOP |
| `SysMsg` | "system" | MUTED | COPY, DELETE |
| `SysMsgError` | "error" | ERROR | COPY, EDIT, DELETE |
| `SysMsgWarning` | "warning" | WARNING | COPY, DELETE |
| `ToolCallMsg` | "tool" | WARNING | OUTPUT, COPY, DELETE |
| `ToolDraftMsg` | "tool" | MUTED | none |
| `AskPermissionMsg` | "permission" | WARNING | ALLOW, DENY, COPY |

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

### Structure

- `Command` — base class. Constructor: `Command(name, description, subcommands={})`.
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
           super().__init__("mycommand", "One-line description")

       async def execute(self, ui: ChatUIProtocol, args: List[str]):
           # use ui.chat_history_panel.add_message() to show output
           ui.chat_history_panel.add_message("hello", msg_type=SysMsg())
   ```

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
