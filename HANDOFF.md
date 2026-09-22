# Pico-Chat — Handoff

**Branch:** `cleanup` · **Suite:** 510 passing · **Last updated:** 2026-09-22

Read this to resume. The big simplification (R1–R9) is done; the recent work is
UI/UX polish. The working tree is dirty with the latest UI changes — the user
commits manually, so **nothing is staged by the assistant**.

Canonical plans: `SIMPLIFICATION.md` (R1–R11), `plans/message_ui_rework.md`.

---

## 1. Commands

```bash
.pixi/envs/default/bin/python -m pytest test/ -q            # 458 passing
.pixi/envs/default/bin/python -m compileall -q pico_chat
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80
.pixi/envs/default/bin/python -m pytest test/test_core_ui_boundary.py -q   # R9 guard
```

No lint/typecheck beyond these. Keep the suite green and the R9 guard passing.

---

## 2. Architecture (current)

- **Events:** `harness/events.py` is the one harness→UI union (`Start`, `Token`,
  `Reasoning`, `ToolCall`, `PermissionRequest`, `ToolResult`, `Usage`, `Error`,
  `Done`). `chunks.py` is gone.
- **Endpoints:** `harness/endpoint.py` is one concrete `Endpoint` (config +
  httpx transport). `llm_server*.py` / `server_service.py` deleted.
- **Config:** user-level only, split per concern under `~/.config/pico-chat/`:
  `ui.toml`, `context.toml`, `subagents.toml`, `debug.toml`, `styles.toml`,
  `servers.toml`, `roles/<name>.toml`, disposable `state.toml`. `/config
  <section>` edits a file and reloads. `pico.toml` is gone.
- **One conversation per process:** no tabs/`ConversationRuntime`. `chatTUI`
  owns agent, panel, queue, task, tool/permission state.
- **Message selection + action line:** selected message gets `▌`; an `ActionBar`
  above the input shows actions (right-aligned, muted) or input-prefix hints.
  Actions are only COPY/OUTPUT/ALLOW/DENY (delete/edit/retry/stop/etc. removed).
- **Activity surface:** `SysMsg*` routed to an `ActivityPopup` (`/activity`) +
  status-bar toasts, not the transcript.
- **`@` file picker:** `ContextCompletion` trigger `@`, subsequence
  `fuzzy_match` ranking (dirs first), scroll-following full-width menu, `USER`
  accent, `n/m` counter.
- **Clipboard:** `ui/clipboard.py` (`copy_to_clipboard`) — native helpers then OSC 52.

---

## 3. Done recently (UI polish)

- Message prefix bar `▌` — full message height; USER accent for user, MUTED for
  pico; user content normal color.
- Inter-message blank line: `ui_msg_v_margin` (default `1`, configurable).
- Message padding centralized in `Box` thread mode (`content_pad_left/right`);
  content components render unpadded; width math de-duplicated.
- `Message.append()` strips leading whitespace on the first streamed chunk
  (models often open with a space).
- Action line right-aligned (`ActionBar.set_align_right`), muted, no prefix.
- Fuzzy menu: `USER` highlight (bold, no reverse, no underline), scroll-follow,
  full width; TAB replaces the whole current word (cursor-independent).
- Ctrl+C quits on first press (`agent_worker` races `shutdown_event`;
  `shutdown_watcher` cancels in-flight generation; `main.py` swallows stray
  `KeyboardInterrupt`).
- `/model` modal picker, `ui_max_input_height` (input cap + scroll).
- **Clipboard:** `ui/clipboard.py` is the single owner; native
  `xclip`/`xsel`/`wl-copy` first, then OSC 52 (`harness/clipboard.py`)
  as the fallback so copying works over SSH. `handle_copy_action`,
  `_auto_copy_selection`, and `/debug get_context` all use it. The OSC 52
  payload truncates on a 4-byte base64 boundary so it stays decodable.
  Feedback distinguishes verified copies (`copied ✓`) from OSC 52
  (`sent via OSC 52`). Note: VTE terminals (Ptyxis/GNOME Terminal) ignore
  OSC 52 — use `ssh -X` (X11 forwarding, xclip) or an OSC 52 terminal.

---

## 4. What needs change

### Next: optional picker polish
Breadcrumb/header for the drilled directory; tail-truncation for very deep
paths; dir/file styling. (Match highlighting was deliberately removed.)

### Optional structural refactor (noted, not planned in detail)
- Extract a `MessageView` so `Box` sheds message-specific modes; make padding
  the single owner end-to-end.
- Split `ChatHistoryPanel` (layout/scroll vs selection/text-selection vs caches).
Deferred from the plan: replace the bespoke TUI toolkit; derive tool schemas
from signatures; built-in mini editor.

---

## 5. Gotchas

- Tests isolate config by monkeypatching **module functions**
  (`pico_cfg.get_config_dir`, `get_state_path`, `get_roles_dir`,
  `roles._ROLES_DIR`). Same pattern for new tests.
- `Harness.endpoint` (not `.server`). Test fixtures use
  `harness.endpoint = FakeServer()`.
- `harness/` must not import `ui/` (R9 guard); only `main.py` may import both.
- Clipboard/X11 code must stay import-safe in headless test runs.
- `pico_cfg.config` is a global loaded at import; `/reload` mutates in place.
- Form stack is gone (`TextField`, `FormPopup`, `ConfigOverlay`, `RoleEditorForm`
  etc. no longer exist) — use `Button`/`Label` as test stand-ins.
- Untracked scratch in the tree (`.agents/`, `plans/`, `notes/`, `*.todo`,
  `uv.lock`, `vulture_initial.txt`) — not part of the product.

---

## 6. Working preferences

- Aggressive simplification toward the essence; explicit over implicit
  (`/reload`, no watchers).
- Config files over UI; edit with `$EDITOR`.
- Keeps the custom TUI aesthetic; do not delete the TUI toolkit.
- Terse answers; corrections welcome.
- **Do not commit unless asked.** The user commits manually.
