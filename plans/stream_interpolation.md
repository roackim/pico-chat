# Stream Interpolation (Smoothing) — Plan

**Status:** proposed (no code yet) · **Created:** 2026-09-23
**Depends on:** `plans/markdown_streaming_refactor.md` (M1–M4) — the revealer feeds
`Message.reveal_to`, which must be cheap on append.
**Companion docs:** `plans/markdown_streaming_refactor.md`,
`notes/bench_render.py`, `.wiki/notes/principles.md`.

Goal: decouple the rate text *arrives* from the rate it *appears*, so streamed
output reveals smoothly instead of in network-sized bursts. Applies to **any**
visible streamed text (content and reasoning), with no message-type sniffing.

---

## 1. Decisions (locked)

- Smoothing only — never hold text longer than one chunk and never add a
  configurable cushion.
- **`smooth_target_fps`** sets the reveal cadence, independent of render fps.
  Grain (chars per step) is derived, not configured: bigger chunk or slower
  render → bigger grain.
- **One-chunk buffer.** On arrival, spread that chunk over `min(dt_since_prev,
  100 ms)`; if the next chunk arrives first, merge and recompute. Worst-case
  added latency is one chunk / 100 ms by construction.
- Grain unit = **non-whitespace grapheme clusters**; intervening whitespace is
  released for free; coarse steps land on grapheme-safe word ends.
- **No cursor** is rendered in LLM messages. Reveal is appending text.
- Config surface: `stream_smoothing` (bool) and `smooth_target_fps` (int). The
  100 ms cap and default window are constants, not keys.

## 2. Architecture

### 2.1 `StreamRevealer` — pure controller

`pico_chat/ui/stream_revealer.py`, no TUI imports. All time is passed in, so it
is deterministic and unit-testable.

```
class StreamRevealer:
    def __init__(self, target_fps: int, max_window: float = 0.100): ...
    def ingest(self, text: str, now: float) -> None      # arrival
    def pending(self) -> int                              # non-ws clusters left
    def tick(self, now: float) -> str                     # slice to release ("" = none)
    def drain(self) -> str                                # release everything
    def active(self) -> bool
```

State: `_pending: str`, `_deadline: float | None`, `_last_arrival: float | None`,
`_step_interval = 1 / target_fps`.

### 2.2 Ownership

- `chatTUI` owns `self.stream_revealer` and the active streamed message +
  `self.stream_revealed` (chars released).
- `generation_presenter.process_generation` translates events → `revealer.ingest`
  and wires which message is active; it does **not** append text to the message
  directly for Token/Reasoning anymore.
- `chatTUI._on_frame(now)` drives `revealer.tick`, applies the slice via
  `message.reveal_to(...)`, maintains auto-scroll, and returns whether work
  remains.

### 2.3 Clock — `Compositor` frame callbacks

Add a minimal, generic API to `compositor.py`:

```
def add_frame_callback(self, cb: Callable[[float], bool]) -> None
def remove_frame_callback(self, cb: Callable[[float], bool]) -> None
```

In `Compositor.run`, once per iteration (alongside the existing `TickEvent`
dispatch at `compositor.py:203`), invoke registered callbacks with
`time.perf_counter()`; if any returns `True`, `request_render()`. Iterate over a
copy so callbacks can unregister themselves.

This replaces `set_streaming_active`/`streaming_active`: the revealer returning
`True` is what keeps frames coming while text is animating; idle frames stop.

## 3. Controller algorithm

Given `pending = arrived − released` (measured in non-ws grapheme clusters):

**On `ingest(text, now)`:**
1. `dt = now − _last_arrival` if set, else `default_window` (= 100 ms).
2. `window = clamp(dt, 0, max_window)`.
3. `_pending += text`; `_last_arrival = now`; `_deadline = now + window`.
4. Merging clears any partial progress notion: the deadline is always relative
   to the newest arrival, so a fast producer keeps the reveal ≤ 100 ms behind.

**On `tick(now)`** (called every frame; reveal at most once per `_step_interval`):
1. If `_pending` empty → return `""`; clear deadline.
2. If `now < _last_step + _step_interval` → return `""`.
3. `remaining = nonws_clusters(_pending)`.
4. `steps_left = max(1, round((_deadline − now) * target_fps))`.
5. `grain = ceil(remaining / steps_left)`.
6. Slice `_pending` forward by `grain` non-ws clusters (whitespace between
   released for free; never split a cluster); return the slice.
7. If `now ≥ _deadline`, release **all** remaining (we are behind: stop being
   pretty). This is the catch-up path.

**On `drain()`:** return all `_pending`, clear.

Properties:
- Steady arrival → `dt` stable → `grain` stable → constant-looking reveal.
- Burst → deadline ≤ 100 ms → grain grows → drains fast.
- Stalled render → `now ≥ deadline` → snap (bounded memory, no spiral).
- Fast render / small chunk → grain = 1 cluster → finest smoothness.
- `smooth_target_fps` above the actual render fps degrades to the frame rate,
  grain grows accordingly — no config mismatch possible.

## 4. Grapheme clusters

No stdlib segmentation exists (`wcwidth` gives widths only). Add
`pico_chat/ui/tui/graphemes.py`:

- `split_clusters(text) -> list[str]` honouring: combining marks
  (`unicodedata.combining`), ZWJ sequences (U+200D), variation selectors,
  skin-tone modifiers, regional-indicator pairs, Hangul jamo.
- `count_nonws(text) -> int` and `advance_nonws(text, n) -> int` (char offset of
  the n-th non-ws boundary).
- Reuses `wcwidth` for display width where needed, but the reveal unit is the
  cluster, not width.

Bounded scope (~60 lines + tests). If vendoring is rejected, fall back to
code-point boundaries and accept a one-frame artifact for ZWJ emoji — but the
cluster helper is small and correct.

## 5. Message API changes

`Message` currently conflates "arrived" and "rendered" in `base_text` +
`reformat`. Split them:

- `base_text` remains the **canonical full arrived text** (used by `/export`,
  metrics, finalize). Add `ingest(text)` → `base_text += text` only, no reformat.
- Add `_reveal_len: int`; `reveal_to(n)` sets `_reveal_len = min(n, len(base_text))`
  and re-renders `base_text[:_reveal_len]` via the existing markdown
  `update(append=True)` fast path (works because the prefix only grows).
- `finalize()` drains: `reveal_to(len(base_text))` before marking finalized.
- Existing `append()` is expressed as `ingest` + `reveal_to(len(base_text))` for
  non-streamed callers, so non-stream paths are unchanged.

`get_preferred_height`/`set_layout` are unaffected: they already operate on the
rendered component, which now holds the revealed prefix.

## 6. Lifecycle & flush semantics

Ordering matters more than smoothness at hard boundaries. Flush (drain
synchronously) and finalize before:

- `ToolCall` / `PermissionRequest` (the tool block must follow the text).
- reasoning↔content switch (previous message must be complete before the new
  one is appended).
- `Error`, `CancelledError` (retain arrived text, then the notice).
- message replacement / conversation clear / `/import`.

On natural `Done`: **do not** jump. Mark the stream ended; let the revealer
drain over its remaining window, and finalize (gutter ✓, message actions) from
the frame callback once `revealer` is empty. The message stays un-finalized
(spinner) while text is still animating — consistent, and bounded by ≤100 ms.

Auto-scroll: the current post-event `chat.scroll_offset = 0` block
(`generation_presenter.py:233`) must also run on each reveal tick, otherwise
animating text below the fold won't scroll.

## 7. Config

`ui.toml` (flat keys, per existing convention):

```toml
# stream_smoothing = true
# smooth_target_fps = 60
```

Map to `ui_stream_smoothing` / `ui_smooth_target_fps` in `pico_cfg`. Constants:
`max_window = 0.100`, `default_window = 0.100`, `min_cluster_grain = 1`.

## 8. Displacement (delete before you design)

- Remove `Compositor.set_streaming_active` / `streaming_active`.
- Remove the per-`Token`/`Reasoning` `request_render()` in
  `generation_presenter.py:66` (frame callback drives it).
- `Message.append` stops being the streaming primitive; Token/Reasoning no
  longer call it.
- Any stream-smoothing knobs stay out of config beyond the two keys above.

## 9. Workstreams

- **S1 — Frame callbacks.** Add `add/remove_frame_callback` to `Compositor`;
  unit-test invocation + render request + safe mutation.
- **S2 — Grapheme helper.** `graphemes.py` + tests (ZWJ, combining, jamo,
  regional indicators, whitespace runs).
- **S3 — `StreamRevealer`.** Pure controller + deterministic tests with an
  injected clock (§10). No UI wiring.
- **S4 — Message split.** `ingest`/`reveal_to`/drain-on-finalize; update
  non-stream callers; existing message tests stay green.
- **S5 — Wiring.** `chatTUI._on_frame`, active-message plumbing in
  `generation_presenter`, auto-scroll per tick, deferred finalize on `Done`.
- **S6 — Config + cleanup.** Two keys; remove `streaming_active`; vulture.
- **S7 — Benchmarks & docs.** Extend `notes/bench_render.py` with a smoothed
  stream scenario; record baseline; update `.wiki/notes/ui.md`.

Each workstream ends green on §11 gates.

## 10. Tests

Pure (S3, injected clock — no sleeps):
- Steady arrival reveals at ~arrival rate, grain ≈ 1.
- Large burst drains within `max_window`, never earlier than one step.
- New chunk during reveal merges and shortens the deadline (catch-up).
- `now ≥ deadline` releases all remaining.
- Whitespace-only pending releases fully.
- Cluster boundaries never split; non-ws counting ignores spaces.
- `drain()` empties; `active()` correct.

Integration:
- Fake harness emits Token/Reasoning; drive `_on_frame` manually; assert the
  visible text lags then converges exactly to full at drain.
- Boundary flush ordering: token → tool call → permission → result renders in
  order with no text after the tool block.
- Cancel/error: arrived text retained, notice follows.
- Reasoning→content: reasoning complete before content appears.
- `finalize` deferred until drained; spinner present while animating.
- Feature off (`stream_smoothing = false`) → today's direct-append behavior.

Perf:
- Reuse `notes/bench_render.py` `stream` scenario; assert per-frame reveal does
  not regress frame time vs `notes/bench_baseline.json`.
- After markdown M1–M4, `reveal_to` append cost is flat w.r.t. message length.

## 11. Gates

```bash
.pixi/envs/default/bin/python -m pytest test/ -q
.pixi/envs/default/bin/python -m compileall -q pico_chat
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80
.pixi/envs/default/bin/python -m pytest test/test_core_ui_boundary.py -q
.pixi/envs/default/bin/python -m pytest test/test_streaming_incremental.py -q
.pixi/envs/default/bin/python notes/bench_render.py --load notes/bench_baseline.json
```

## 12. Risks

- **Boundary ordering** (text vs tool/permission blocks) is the main
  correctness risk; flush rules in §6 are the contract, tested explicitly.
- **Finalize coupling**: deferring finalize to the frame callback must not leak
  un-finalized messages if the stream task is torn down; the presenter's
  `finally` must force `drain` + finalize as a backstop.
- **Cluster helper correctness** affects only transient frames, but bad width
  math can mis-wrap; keep it covered.
- **`/export` during streaming** reads full `base_text` (arrived), which is
  correct; confirm no code re-derives text from the rendered component.

## 13. Sequencing

1. Markdown M1–M4 (standalone; may already remove most perceived jank).
2. Measure. If still choppy, proceed.
3. S1–S2 (infra), S3 (controller, pure), S4 (message split).
4. S5–S7 (wiring, config, cleanup, benches).
