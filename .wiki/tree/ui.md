# pico_chat/ui/ — Chat UI Layer

Async TUI built from scratch. Handles chat display, user input, message actions, and slash commands.

See [notes/ui.md](../notes/ui.md) for the full architecture overview.

---

## Files

### `app.py`
`chatTUI` — main application class.
- Sets up layout, compositor, and component tree
- Runs the async event loop
- Routes incoming `Chunk` objects from the harness to the chat display
- Dispatches user input to the harness or command handler
- Manages popup overlay via `show_popup()` / `hide_popup()`; input intercepted in `handle_global_input()` when popup is visible

### `chat_history_panel.py`
`ChatHistoryPanel` — extends `TextComponent` for scrollable message display.
- `add_message(text, msg_type, title=None, ...)` — creates a `Message`, appends it, scrolls to bottom
- `new_message(...)` — creates but does not append (use with `replace_message`)
- `replace_message(old, new)` — swap a placeholder message with a final one
- `clear()` — removes all messages
- `start_inline_edit(message)` / `stop_inline_edit(save)` — in-place message editing via `Box.inline_editor`
- Handles keyboard focus, per-message focus navigation, and width-change reformatting
- **Mouse selection**: drag-to-select text within messages; selection highlight rendered as reverse-video overlay; auto-copies to clipboard on release
- **Action click handling**: `_hit_test_action_bar()` computes button hit regions for action buttons in box bottom borders; clicking dispatches the action with a brief reverse-video flash feedback
- **Parameter hints**: `_get_parameter_hint()` reads `Command.params` from the registry to show schema-driven argument hints when typing `/commands`
- `y` key yanks current selection to clipboard

### `chat_message.py`
`Message` — wraps content with a `MsgType`, colors, padding, and action set.
- Constructor accepts `msg_type`, `title`, `frame_color`, `content_color`, `left_margin`, `harness_message_ids`
- `finalize()` — marks message complete; removes STOP action, enables DELETE
- `get_active_actions()` — returns actions appropriate for current state
- Internally composed of a `TextComponent` inside a `Box`
- See [notes/ui.md](../notes/ui.md) for the full MsgType and MsgAction reference.

### `chat_action_handlers.py`
`ChatActionHandlers` mixin for `chatTUI`.
- Copy to clipboard via `xclip` or `wl-copy` (auto-detected)
- Delete message from history
- `handle_edit_action` — expanded in-place editing: edits paused AI messages (thinking prefill), finalized `ThinkingMsg` (edit reasoning as prefill), finalized `PicoMsg` (finds preceding `ThinkingMsg`), and `UserMsg` (edit + wipe subsequent messages)
- Retry (re-send last user message)

### `commands.py`
Slash command system with generic parameter schema.
- `Param` dataclass: `name`, `completions` (static list or callable), `path` (filesystem scan), `required`
- `Command` base class: `name`, `description`, `subcommands`, `params: List[Param]`, `execute(ui, args)`
- `Command.resolve_command(parts)` — walks subcommand tree, returns `(deepest_cmd, arg_offset)`
- `Command.get_completions(arg_index)` — resolves completions from `Param` schema (static list, callable, or `path=True` filesystem scan)
- `COMMANDS` dict — module-level registry; all top-level commands registered here
- `handle_command(ui, text)` — strips `/`, looks up `COMMANDS`, dispatches
- `get_command_list()` / `get_subcommand_list(cmd)` — used by input autocomplete
- Commands with sub-operations pass a `subcommands` dict to the constructor (e.g. `ServerCommand`)
- Commands starting with `_` are hidden from `/help`
- Registered commands: `help`, `clear`, `compact`, `exit`, `stop`, `resume`, `prefill`, `status`, `server`, `tools`, `debug`, `permissions`, `openrouter`, `cd`, `pwd`, `conversation`, `tab`
- Server management commands (`ServerAddCommand`, `ServerUseCommand`, etc.) use `Param` for server name completions (reads `pico_cfg.config.servers.keys()`)
- `CdCommand` uses `Param("DIR", path=True)` for filesystem completion
- `HelpCommand` renders output in a popup overlay via `ui.show_popup()` instead of chat history
- `StatusCommand` renders in popup (async: shows "Checking..." placeholder, then updates with actual status)
- `ToolsCommand` renders in popup
- `PermissionsCommand` renders in popup
- `DebugCommand` (no args) renders subcommand help in popup
- See [notes/ui.md](../notes/ui.md) for how to add a new command.

### Shell Commands (`$` prefix)
- `$ <command>` — Execute shell command directly (not visible to LLM)
- Example: `$ ls -la`, `$ git status`, `$ python3 script.py`
- Output displayed as system message with exit code and timing
- 30-second timeout for safety

### `logging_handlers.py`
`TuiLogHandler` — Python `logging.Handler` that routes log records to the debug panel.
Filters out high-volume noise from known verbose loggers.

---

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| [tui/](./ui-tui.md) | Low-level terminal rendering engine |
