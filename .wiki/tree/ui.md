# pico_chat/ui/ — Chat UI Layer

Async TUI built from scratch. Handles chat display, user input, message actions, and slash commands.

See [notes/ui.md](../notes/ui.md) for the full architecture overview.

---

## Files

### `app.py`
`chatTUI` — main application class.
- Sets up layout, compositor, and component tree
- Owns a **single conversation**: `agent`, `chat_history_panel`, `message_queue`,
	`current_generation_task`, `active_tool_messages`, `pending_permission_prompt`,
	and pause/steer state live directly on the app (no `ConversationRuntime`)
- Installs one `ChatScreen` (history + input + status bar) through `Navigator`
- The debug console is a `DebugPopup` compositor overlay toggled by `/debug panel`
	(`toggle_debug_console`), not a workspace tab
- Ordinary, edited, retried, and resumed messages share one enqueue path,
	preserving consistent queued state and FIFO ordering
- Application startup launches one `agent_worker` plus one app-level command
	worker; slash commands are consumed independently of generation
- Popup input is routed by registered EventRouter overlays rather than duplicated in `handle_global_input`
- History/input mouse focus is selected through the reusable `FocusScope.focus_at()` API
- Application focus adapters delegate layout geometry to their wrapped components for mouse hit testing
- Completion-menu input is dispatched directly to the input component; no root-handler compatibility fallback remains
- Application focus navigation consumes canonical `KeyEvent` metadata while accepting legacy raw strings
- `switch_role(role)` applies a role and emits a de-duped role-change notice
- Runs the async event loop
- Routes incoming `events.*` from the harness to the chat display
- Dispatches user input to the harness or command handler
- Manages popup overlay via `show_popup()` / `hide_popup()`; input is routed by registered EventRouter overlays

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

### `commands/` (package)
Slash command system with generic parameter schema. The `commands/` package
replaces the legacy single `commands.py`:

- `commands/__init__.py` — public API re-exports (`Command`, `Param`, `COMMANDS`, `handle_command`, etc.) and preserves the historical `pico_chat.ui.commands` import path
- `commands/builtins.py` — the canonical `COMMANDS` registry dict and top-level commands (help, clear, compact, exit, stop, resume, status, server, model, tools, debug, permissions, etc.)
- `commands/base.py` — `Param` and `Command` base classes plus completion helpers
- `commands/server.py` — `ServerAddCommand`, `ServerListCommand`, `ServerInfoCommand`, `ServerRemoveCommand`, `ServerDiagnoseCommand`
- `commands/models.py` — `ModelCommand` (`/model <model>` + `/model list`)

Base contracts:
- `Param` dataclass: `name`, `completions` (static list or callable), `path` (filesystem scan), `required`
- `Command`: `name`, `description`, `subcommands`, `params: List[Param]`, `execute(ui, args)`
- `Command.resolve_command(parts)` — walks subcommand tree, returns `(deepest_cmd, arg_offset)`
- `Command.get_completions(arg_index)` — resolves completions from `Param` schema (static list, callable, or `path=True` filesystem scan)
- `handle_command(ui, text)` — strips `/`, looks up `COMMANDS`, dispatches
- Commands starting with `_` are hidden from `/help`

**Server/model management:**
- `/server` — add, list, info, diagnose, remove. The `use`/switch subcommand was **removed**; switching is done implicitly by selecting a model.
- `/model <model>` — the single model-selection entry point. Refreshes discovery live (it does not trust the cached catalog), verifies the model is actually served by the chosen server, switches the harness to it, and selects it. Accepts an explicit `server:model` form (the model id may itself contain colons, e.g. Ollama quantized tags); if that server does not list the model, the command refuses instead of switching. Model completions are fuzzy-filtered from the cached `model_catalog`.
- `/model list` — discovers models live from every reachable server (via `discover_all_models`), annotated `[server]`.

The input layer's `ArgumentCompletion` reads `Param.completions` to drive
fuzzy argument completion for `/model <model>`. See [notes/ui.md](../notes/ui.md) for how to add a new command.

### `role_editor_model.py` / `role_editor_form.py`
`RoleEditorModel` — UI-independent state and persistence boundary for the
interactive role editor (the single policy surface). It isolates the active
draft, applies role selection immediately, and exposes create, rename,
duplicate, remove, and update operations without requiring a rendered form.
`RoleEditorForm` wires the model to the form fields. There is no separate
permission-profile editor.

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
