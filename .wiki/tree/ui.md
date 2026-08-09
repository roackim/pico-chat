# pico_chat/ui/ — Chat UI Layer

Async TUI built from scratch. Handles chat display, user input, message actions, and slash commands.

See [notes/ui.md](../notes/ui.md) for the full architecture overview.

---

## Files

### `app.py`
`chatTUI` — main application class.
- Sets up layout, compositor, and component tree
- Manages conversation tabs and the closeable debug-console workspace tab
- Uses generic `TabView` entries for tab identity and view ownership while keeping `ConversationState` as application-level domain state
- Uses `TabView` as the sole production tab-selection and close state path
- Uses an empty workspace when no tabs exist; the first ordinary message creates a closeable conversation tab
- Queued-message styling and concurrent generation output are scoped to the conversation that owns the active generation
- The selected `ConversationRuntime` history panel is mounted directly into the
	live workspace, keeping visible messages independent across tabs
- Ordinary, edited, retried, and resumed messages share one runtime enqueue path, preserving consistent queued state and FIFO ordering
- Application startup launches only `ConversationRuntime` workers; no legacy global worker remains
- Application startup also launches one app-level command worker; slash commands
	are consumed independently of per-conversation generation workers
- Popup and form input are routed by registered EventRouter overlays rather than duplicated in `handle_global_input`
- Permission-request messages remain boxed and purple even when they are not focused; long run commands are preserved for wrapping in the message box
- History/input mouse focus is selected through the reusable `FocusScope.focus_at()` API
- Application focus adapters delegate layout geometry to their wrapped components for mouse hit testing
- Completion-menu input is dispatched directly to the input component; no root-handler compatibility fallback remains
- Application focus navigation consumes canonical `KeyEvent` metadata while accepting legacy raw strings
- `ConversationRuntime` owns each tab's agent, message panel, queue, worker, generation task, tool state, permissions, and pause state
- `ConversationRuntime.switch_role()` is the single role-switch boundary; it rejects changes during an active generation before delegating to the conversation agent
- Installs chat and debug workspace layouts through `ChatScreen` as Navigator-managed screen instances
- Delegates runtime chat/debug workspace replacement to `Navigator`; pre-run setup only constructs the screen root
- Passes active conversation state to `ChatScreen` as an external screen model
- Runs the async event loop
- Routes incoming `Chunk` objects from the harness to the chat display
- Dispatches user input to the harness or command handler
- Manages popup overlay via `show_popup()` / `hide_popup()`; input is routed by registered EventRouter overlays
- Provides `show_confirmation()` for compact Enter/Esc confirmation modals layered over an existing form
- Leaves tab mouse hit testing to `EventRouter` and the `TabBar`/`TabView` component path

The application-specific panels and command callbacks remain outside the
library contract; reusable widgets and screens are documented in
`../notes/ui.md`.

### `chat_history_panel.py`
`ChatHistoryPanel` — extends `TextComponent` and is used directly as the
scrollable message component in `ChatScreen`.
- `restore_messages(messages)` — restores message objects while rebuilding
	panel-owned message and scroll state
- `add_message(text, msg_type, title=None, ...)` — creates a `Message`, appends it, scrolls to bottom
- `new_message(...)` — creates but does not append (use with `replace_message`)
- `replace_message(old, new)` — swap a placeholder message with a final one
- `clear()` — removes all messages
- `start_inline_edit(message)` / `stop_inline_edit(save)` — in-place message editing via `Box.inline_editor`
- Handles keyboard focus, per-message focus navigation, and width-change reformatting
- Owns the message collection and lays out visible message components directly;
	there is no parallel child-container compatibility state
- **Mouse selection**: drag-to-select text within messages; selection highlight rendered as reverse-video overlay; auto-copies to clipboard on release
- **Action click handling**: `_hit_test_action_bar()` computes button hit regions for action buttons in box bottom borders; clicking dispatches the action with a brief reverse-video flash feedback
- Keyboard and mouse message actions share the `on_action(message, action)` callback boundary
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

### `commands/`
Slash command package with a compatibility-preserving public API and domain
facades for the concrete command groups.
- `base.py` owns the generic parameter schema, command contract, and dynamic
	completion helpers.
- `core.py`, `server.py`, `debug.py`, `permissions.py`, `conversation.py`, and
	`tabs.py` provide focused import surfaces for their command domains.
- `conversation.py` owns conversation export/import and the parent dispatcher;
	imports accept legacy history arrays and restore exported roles before replay.
- `server.py` owns server add/list/use/remove/info commands and their parent
	dispatcher; the commands delegate configuration changes to `ServerService`.
- `tabs.py` owns tab new/close/switch/list commands and their parent dispatcher.
- `debug.py` owns debug panel/context/log commands; `ToolsCommand` remains in
	`builtins.py` until the tool-inspection slice is extracted.
- `permissions.py` owns the unified role/profile permissions editor and applies
	role selection and edits through `ConversationRuntime.switch_role()`; before
	the first tab exists, it applies changes to the initial agent used to create
	the first conversation runtime. Role changes emit a muted system notice in
	the conversation, replacing the immediately previous role notice.
- The permissions role editor routes role saves and active-role deletion through
	`ConversationRuntime.switch_role()` and reports active-generation rejection
	inside the chat history instead of escaping the callback.
- `roles.py` owns the legacy `/roles` inspection and lifecycle command.
- `registry.py` owns the registry and dispatch helper exports.
- `builtins.py` retains core commands, tool inspection, OpenRouter, and workspace
	commands during the staged extraction; existing
	`pico_chat.ui.commands` imports remain valid.
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
- `PermissionsCommand` renders the unified conversation-role editor in a popup;
	the editor controls role metadata, prompt, enabled tools, granular policies,
	and role lifecycle. Role deletion is confirmed in a compact modal and refuses
	to remove the final remaining role. Legacy permission-profile subcommands
	remain compatible.
- `RolesCommand` remains a lightweight compatibility/inspection command while
	the primary role editor is hosted by `/permissions`.
- The interactive no-argument permissions editor composes `ProfileList`,
  `FormSection` groups, horizontal policy selectors, and container toggles.
  Role changes are bound through `RoleEditorForm`; legacy permission-profile
  editing remains backed by `ProfileEditorModel`.
- `DebugCommand` (no args) renders subcommand help in popup
- See [notes/ui.md](../notes/ui.md) for how to add a new command.

### `profile_editor_model.py`
`ProfileEditorModel` — UI-independent state and persistence boundary for the
interactive permissions editor. It isolates the active draft, applies profile
selection immediately, and exposes create, rename, duplicate, remove, and
update operations without requiring a rendered form.

### `role_editor_model.py`
`RoleEditorModel` — UI-independent lifecycle and draft boundary for the unified
conversation-role editor hosted by `/permissions`. Handles built-in duplication,
saved-role selection, in-place persistence, and editable role drafts.

### `role_editor_form.py`
`RoleEditorForm` — declarative field and binding boundary for the unified role
editor. Builds sectioned fields, synchronizes selected roles into the widgets,
and applies edited tool, file-policy, and container settings through
`RoleEditorModel`.

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
