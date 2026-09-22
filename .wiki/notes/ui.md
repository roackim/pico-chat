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

Typed event dataclasses are defined in `tui/events.py`. Shared focus ownership
is provided by `tui/focus.py`; `FormContainer` uses `FocusManager` while
retaining its existing form navigation API.
`FocusScope` provides modal focus boundaries; `FormPopup` enters its scope when
shown and releases it when hidden. `EventRouter` dispatches keyboard events to
the active focus target after application policy handling.
`EventRouter` provides overlay-priority dispatch and layout-based mouse
hit-testing for compositor input.
Keyboard input is normalized to string-compatible `KeyEvent` objects at the
terminal boundary, and terminal resize notifications are dispatched as
`ResizeEvent` objects.
The application-level input/history focus state is backed by `FocusScope`; its
domain-specific Up/Down and inline-editing rules remain in `chatTUI`.

Each conversation tab owns its runtime agent, history panel, queue, worker, and
conversation-local tool/permission state. The selected runtime's history panel
is mounted directly into the active chat workspace, so switching tabs does not
copy messages through a shared panel. Slash commands use one application-level
worker and remain responsive while conversation generation is running.

## Status Bar

The chat workspace includes a one-line `StatusBar`. Its visible fields and
order come from `pico_cfg.config.ui_status_bar_fields`; the default is:

```toml
[ui]
status_bar_fields = ["endpoint_model", "role", "context"]
```

The default display is `endpoint:model  role default  ctx 12.4k/32k`.
Available values include `endpoint_model`, `endpoint`, `model`, `context`,
`role`, `state`, and `workspace`. Provider-reported prompt usage replaces the
context estimate after a response supplies authoritative usage data.

The `context` field is colorized by how full the context window is:
green below 33%, orange/amber below 66%, and red at or above 66%.

The `role` field reflects the active conversation role and is refreshed
whenever the role changes (via `/roles use`, the `/permissions` role editor,
or a conversation import that applies a saved role).

## Conversation import/export

`/export <file>` writes `{"role": ..., "history": [...]}`.
`/import <file>`:
- Fuzzy-autocompletes `.json` files in the current directory.
- Restores the saved role; if the role no longer exists, it defaults to
  `default` and posts a warning message in the chat.
- Rebuilds visible messages, splitting assistant thinking/content with the
  same `ThinkingTagParser` the harness uses (so imported reasoning renders as
  a `ThinkingMsg`).

## Library Contracts

### Widget Lifecycle and Ownership

Containers assign child geometry through `set_layout()` and `layout()`. The
compositor renders the root tree after layout, then renders registered overlays
above it. Components mark content changes with `mark_changed()` and geometry
changes with `mark_layout_changed()`; the compositor uses those states to
request redraws. Widgets own presentation and local interaction, screens own
workflow and focus/action scope, and the application owns domain state and
services.

### Event and Focus Flow

`EventRouter` checks overlays from newest to oldest first. An unhandled event
then passes through the application interceptor, semantic `ActionMap`, mouse
hit path, focused widget, or root fallback as appropriate. Mouse paths are
built from component rectangles and are tried child-first; a component stops
propagation by returning `True`. The application interceptor handles policy
and focus transitions. `FocusScope` selects the keyboard target and keeps
modal focus bounded.

### Layout and Coordinates

Coordinates are zero-based terminal cells. Component rectangles use absolute
`x`, `y`, `width`, and `height`; the right and bottom edges are exclusive.
Containers allocate child rectangles before rendering. `Padding` insets a
child, `Align` positions it within its allocation, `Stack` paints children in
order, and `ScrollView` clips content to its viewport. Rendering writes to the
allocated `Buffer` or `SubBuffer` and should not perform layout for siblings.

### Screens and Navigation

Create a screen by composing components into a root, then pass optional
`FocusScope`, `ActionMap`, and model values to `Screen`. Install an initial
screen with `Navigator`; use `push`, `pop`, `replace`, or `back` for movement.
Use `ModalHost.present_screen()` for modal screens so enter/leave lifecycle
hooks and overlay ownership are handled together.

### API Stability

The stable library surface is the typed events, `Action`/`ActionMap`, focus
scopes, `Component`, layout primitives, reusable components, `Screen`,
`Navigator`, and `ModalHost`. Modules named
as application adapters, private attributes (leading `_`), compositor internals,
and legacy `chatTUI` callbacks remain internal and may change during migration.

### Library-Only Example

`pico_chat.ui.tui.example_screen.ExampleScreen` is a minimal screen composed
only from library primitives. It demonstrates root composition, focus scope,
semantic activation, layout, and rendering without chat or harness state.

## Integration Boundary

Migration is vertical and behavior-preserving: add focused coverage before
replacing a legacy path, keep compatibility at the application boundary, and
remove legacy paths only after production references reach zero. User-visible
behavior that must remain unchanged includes modal priority and Escape
cancellation, focus restoration after modal dismissal, tab selection and close
behavior, keyboard and mouse routing, resize handling, scrolling, and the
existing chat input/history navigation policy.
The running application now presents form popups through `ModalHost`; direct
compositor ownership remains available for isolated callers and compatibility
tests.

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
- Input interception: when popup is visible, the `EventRouter` overlay-priority
    path routes input to the popup before normal focus handling
- Auto-sizing: `max_width_ratio` / `max_height_ratio` control popup dimensions relative to terminal
- Currently used by: `/help` (command list), `/status` (async with placeholder), `/tools`, `/permissions`, `/debug` help

## Forms System (`tui/components/form.py`, `form_popup.py`)

Modal form dialogs for interactive input (server configuration, settings, etc.).
`FormPopup` can be owned directly by `ModalHost` through its `FormPopupScreen`
adapter, while retaining the legacy compositor overlay path.

### Field Types (`form.py`)

| Field | Rendered | Value Type | Navigation |
|-------|----------|------------|------------|
| `ToggleField` | `[x] Label` / `[ ] Label` | `bool` | Space/Enter toggles |
| `TextField` | `Label: value_cursor` | `str` | Typing, arrow keys, Home/End |
| `TextAreaField` | Label + multiline content | `str` | Enter inserts newline, arrows navigate |
| `CheckboxListField` | `Label:` + `[ ]`/`[x]` per option | `List[int]` | Up/Down moves cursor, Space/Enter toggles |
| `RadioListField` | `Label:` + `()`/`(x)` per option | `Optional[int]` | Up/Down moves cursor, Space/Enter selects |

All fields extend `FormField` ABC with: `get_value()`, `set_value()`, `render()`, `handle_input()`, `get_preferred_height()`.
Field value and validation state can be held by standalone models from
`components/field_models.py`; widgets synchronize editor changes to their model.
`FormFieldSpec` and `build_fields()` in `components/form_schema.py` provide
declarative construction for the same widgets. Models validate synchronously
by default and expose `validate_async()` for future asynchronous checks.

### FormContainer (`form.py`)

Vertical layout manager for a list of fields:
- **Tab / Shift+Tab** moves focus between fields
- **Up / Down arrows** also navigate between fields
- Input routes to the focused field
- Scroll offset for forms taller than available height
- 1-row spacing between fields
- Recomputes field heights and offsets before rendering, so a field whose
    child rows change size does not overwrite fields below it
- Accepts `InputResult` focus intents from composite fields; a child handles
    local navigation first and requests `focus="previous"` or `focus="next"`
    only at its boundary
- `activate_focused()` calls the field's public `activate()` method, keeping
    Enter, Space, and mouse activation on the same action path

### Building complex interactive forms

Use a form as three separate layers rather than putting persistence and
navigation into one field:

1. **Model** — owns domain state, validation, and persistence. UI callbacks
     should call public model methods and receive a safe, already-updated value.
     For roles this is `RoleEditorModel`, which owns the active role draft and
     operations such as `select()`, `create()`, `rename()`, `duplicate()`,
     `remove()`, and `update()`.
2. **Fields/components** — own local value editing and rendering. Compose
     `FormField` implementations for scalar values, and compose `ProfileRow`
     and `Button` instances for repeated interactive content. Keep selection,
     keyboard focus, and text-editing state distinct.
3. **Container/popup** — owns sibling focus, scrolling, modal cancellation,
     submission, and layout. It should not inspect private state or special-case
     a particular child type.

#### Recommended composition pattern

```python
model = RoleEditorModel()
fields = [
        ProfileList("Roles", options=model.role_names(), value=0,
                                on_select=load_profile, on_create=create_profile,
                                on_rename=rename_profile, on_duplicate=duplicate_profile,
                                on_remove=remove_profile),
        FormSectionTitle("Settings:"),
        HorizontalSelector("Read", options=["allow", "ask", "deny"],
                                             value=0, on_change=save_draft),
        ToggleField("Use container", value=False, on_change=save_draft),
]
container = FormContainer(fields)
```

The exact callbacks are application-specific, but the flow should remain:

- `on_select` calls `model.select(name)` and copies the returned draft into
    the controls with `set_value()`.
- Scalar field `on_change` callbacks construct a complete draft from the
    fields and call `model.update(draft)`; do not mutate the role store
    directly from a widget.
- Create/duplicate/rename/remove callbacks update the model first, then
    refresh the profile-list options and selected index. Rebuild the list's
    rows after changing its options.
- A dynamic list must report its full preferred height. `FormContainer`
    recalculates offsets during render, which keeps the controls below the list
    aligned after rows are added or removed.

#### Input routing contract

New composite fields should override `handle_input_result()` and return an
`InputResult`:

- `handled=True` stops propagation.
- `redraw=True` asks the owning container to repaint.
- `focus="next"` or `focus="previous"` bubbles a sibling-navigation request
    to `FormContainer`; the child must not choose a sibling itself.
- At an internal edge, consume the arrow key and move the local cursor. At a
    boundary, return the focus intent instead.

Leaves should expose `activate()`. `Button` uses it for Enter, Space, and
left-click, while `ProfileRow` delegates to its focused button. This makes
keyboard and mouse behavior identical and avoids parent code branching on
concrete child types. Existing boolean `handle_input()` fields remain
compatible through `InputResult.from_legacy()`.

#### Inline editing and repeated rows

For rename-like interactions, keep an explicit editing index and draft text
on the composite control. While editing, printable characters and deletion
are handled locally; Enter commits through the model callback and Escape
cancels without changing the model. A row should contain a selection control
plus independent action buttons for rename, duplicate, and remove. Activating
the row selects it; moving focus among its action buttons must not change the
selected profile.

#### Testing checklist

Test the model without rendering, then test the component and popup paths:

- selection is independent from focus and loads/applies the complete draft;
- Enter, Space, and click invoke the same action;
- local arrow movement bubbles only at first/last boundaries;
- Tab and Shift+Tab move between top-level fields;
- rename supports typing, deletion, commit, and Escape cancellation;
- create, duplicate, and remove update list rows and following-field layout;
- persistence and invalid-name errors leave the model unchanged on failure;
- Escape dismisses only the active modal and does not leak to the app.

### FormPopup (`form_popup.py`)

Modal overlay wrapping a `FormContainer` inside a `Box`:
- `show(title, fields, on_submit, on_cancel)` — displays form, registers with compositor
- `hide()` — dismisses, unregisters from compositor
- **Action bar**: `[Enter] ok` / `[Esc] cancel` in bottom border
- **Validation**: required and custom model validation block submit with an error message
- **Lifecycle**: `dirty` reports changed model values; `reset()` restores initial values, and cancel resets before dismissing
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

## Single Conversation

There is one conversation per process. The app (`chatTUI`) owns the agent,
history panel, message queue, generation task, tool state, and pause/steer
state directly; there is no `ConversationRuntime`, `TabView`, or `TabBar`.

## Shutdown

Ctrl+C is read as a raw `\x03` byte by the compositor's input loop
(`_handle_shutdown_key`), which sets `running = False` and the app
`shutdown_event`. `agent_worker` races its queue against `shutdown_event`, and a
`shutdown_watcher` task cancels any in-flight generation, so one Ctrl+C exits
promptly and cleanly. `main.py` also swallows a stray `KeyboardInterrupt` so a
mis-timed interrupt never prints a traceback.

## Debug Panel

The debug console is a `DebugLogPanel` (extends `TextComponent`) wrapped in a
`DebugPopup` compositor overlay.

- `DebugLogPanel` receives log entries via `TuiLogHandler`
- `/debug panel` calls `toggle_debug_console()`, which shows/hides the overlay
- The overlay occupies the bottom ~30% of the terminal, closes on Escape, and
  passes unhandled input through to the chat
- Auto-scrolls to bottom on new log entries

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
- `LineInput` and `BoxInput` — reusable cursor-aware single-line and multiline editors used by form fields
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
| `UserMsg` | "user" | USER | COPY |
| `PicoMsg` | "pico" | PICO | COPY |
| `ThinkingMsg` | "thinking" | MUTED | COPY |
| `SysMsg` | "system" | MUTED | COPY |
| `SysMsgError` | "error" | ERROR | COPY |
| `SysMsgWarning` | "warning" | WARNING | (inherits COPY) |
| `ToolCallMsg` | "tool" | WARNING | OUTPUT, COPY |
| `ToolDraftMsg` | "tool" | MUTED | none |
| `AskPermissionMsg` | "permission" | PERMISSION | ALLOW, DENY, OUTPUT, COPY |

`ThinkingMsg` and `SysMsgError/Warning` extend `PicoMsg` / `SysMsg` — they inherit defaults and override only what differs.

Actions are deliberately limited to non-destructive operations. State-changing
actions (retry/stop/steer/pause/resume) and removal/edit are **not** message
actions; when needed they belong to explicit commands. `SysMsg*` notices are
routed to the activity surface rather than the transcript (see below).

### MsgAction Enum

| Action | Key | Label |
|--------|-----|-------|
| `COPY` | `c` | copy |
| `OUTPUT` | `o` | output |
| `ALLOW` | `a` | allow |
| `DENY` | `x` | deny |

### Message Selection and the Mode Line

Messages are gutter-threaded and do not render actions inline. User and pico
messages use a `▌` prefix bar spanning the full message height
(`Box.full_height_gutter`) — user in the `USER` accent, pico in `MUTED`
gray; user content is normal text color (the accent is only the bar).
`ChatHistoryPanel` keeps a `focused_message_index` (the selected message); the
selected message's prefix bar is replaced with a brighter `▌` marker (no extra
column, nothing shifts, no leading margin).

An **action line** sits above the input with a blank pad row above it
(`ActionBar.set_top_pad`): an `ActionBar` mounted permanently in the workspace
body (`ChatScreen(..., action_bar=...)`), collapsed to zero rows and expanded to
two (pad + content) when needed. The app (`_update_action_strip`) drives it in
two modes:

- **Message selected** — shows the message's actions (`[c] copy`, `[o] output`,
  permission `[a]/[x]`) in the muted style, right-aligned as a group with the
  `↑↓ move · esc back` hint (`ActionBar.set_align_right`).
  Mouse clicks are dispatched by the app interceptor to
  `ActionBar.handle_input`; key dispatch goes through
  `ChatHistoryPanel.handle_input` → `on_action`. `ChatHistoryPanel` notifies the
  app via `on_selection_changed`.
- **Input focused** — shows a single muted, right-aligned hint:
  `[/] command [@] file [$] shell    ↑↓ move`. `@` works mid-text, so the line
  stays visible while typing. `InputComponent.on_change` (fired on every text
  change) refreshes it.

The status bar stays visible below in both modes. `Esc`/`Enter`/`i` clear the
message selection and collapse the line.

### Activity Surface and Toasts

Non-conversation output (shell commands/results, command status, errors, role
changes, generation-stopped notices) must not live in the transcript.
`ChatHistoryPanel.add_message` routes `SysMsg`/`SysMsgError`/`SysMsgWarning` to
`activity_sink` when set; the app's sink appends to the **activity overlay**
(a `DebugPopup`-style overlay toggled by `/activity`) and shows a transient
**toast** in the status bar (`StatusBar.set_toast`, auto-expiring). The returned
message is detached (not appended). Explicit `ui.activity(text)` writes to the
overlay only.

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

`ChatHistoryPanel.add_message(text, msg_type, title=None, ...)` creates a `Message` object and appends it (or routes it to the activity sink for `SysMsg*`).
`Message` wraps a `TextComponent`/`MarkdownComponent` inside a thread-mode `Box`
(role gutter, no border).

**Padding is owned by the `Box`.** The panel passes the wrap width to `Message`
(content width = panel width − gutter − padding); `Box` lays the child out at
`x + gutter + content_pad_left` with width reduced by the right pad. Content
components render *unpadded* (plain text is no longer pre-padded and
`MarkdownComponent` gets `left_pad=0`), so "where content starts and how wide it
is" has a single owner. `Message.append()` drops leading whitespace on the first
chunk, since models often open with a space.

Messages are separated by `ui_msg_v_margin` blank lines (default `1`; set it in
`ui.toml`). `ChatHistoryPanel` is the owner of the message list — it handles
layout, selection, scrolling, and width-change reformatting.

---

## Commands (`commands/` package)

Slash commands typed by the user (e.g. `/server`, `/model`, `/status`, `/tools`, `/help`).

The command system lives in the `pico_chat/ui/commands/` package (replacing the legacy single `commands.py`): `builtins.py` holds the `COMMANDS` registry, `base.py` defines `Param`/`Command`, and `server.py`/`models.py` hold the server and model commands. Server management commands are thin UI adapters — all business logic lives in `harness/server_service.py`. The commands call the service and render the results.

### Registered Commands

`help`, `clear`, `reload`, `config`, `edit`, `export`, `import`, `compact`, `exit`, `stop`, `status`, `server`, `model`, `tools`, `debug`, `roles`, `openrouter`, `cd`, `pwd`

### Server & model selection

- `/server` — add, list, info, diagnose, remove. The `use`/switch subcommand was **removed**; switching is implicit via model selection.
- `/model` — opens a searchable picker; `/model <model>` selects directly (the single selection entry point). Refreshes discovery live, resolves a model across all servers, switches the harness to the serving server, and selects it. An explicit `server:model` form (model id may contain colons, e.g. Ollama quantized tags) is verified against that server before switching. Fuzzy completion is driven by `Param.completions` reading the cached catalog. The picker (`SearchModal`) shows the cached catalog instantly, refreshes in the background, tags the current model with a green `active`, shows the model id with muted aligned server/context, and supports type-to-filter.

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

1. **Define the class** in `pico_chat/ui/commands/` (e.g. a new module, or `builtins.py`):
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

For commands with subcommands, instantiate sub-command classes and pass them as a dict to the `subcommands` parameter. See `ServerCommand` in `commands/server.py` for an example.

### Hiding a Command from `/help`

Prefix the name with `_` (e.g. `"_internal"`). `HelpCommand` skips names starting with `_`.

## Terminal I/O (`tui/terminal.py`)

- Sets raw mode, captures mouse/keyboard events
- `ANSI` constants for escape codes
- `Terminal.write()` flushes the buffer to stdout

## Colors and Layout

- `tui/colors.py` — `RGB` class, theme dictionary, hex parsing
- `tui/layout_utils.py` — `wrap_text()`, `display_width()` (wcwidth-aware for Unicode), `strip_ansi()`
- `tui/container.py` — explicit layout pass; `Vsplit`/`Hsplit` support fixed, percentage, content, and fill policies, with `Padding`, `Align`, `Stack`/`Overlay`, and `ScrollView`

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
