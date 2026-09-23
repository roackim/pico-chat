# Markdown Streaming Refactor — Plan

**Status:** proposed (no code yet) · **Created:** 2026-09-23
**Scope:** `pico_chat/ui/tui/components/markdown.py` (touch `box.py` /
`message_view.py` only if `dirty_from` semantics require it).
**Companion docs:** `plans/cleanup_round2.md`, `test/test_streaming_incremental.py`,
`notes/bench_render.py`.

Goal: make an incremental append cost **independent of total message length**,
by committing completed markdown lines atomically and re-parsing only the open
region. This is a prerequisite for (and independently valuable before) any
stream-interpolation feature.

---

## 1. Problem statement

`MarkdownComponent.update(append=True)` has a fast path, but it is gated on
`_last_stable_blank()` (`markdown.py:685`), which only cuts at a blank line
outside a fenced code block.

- Streaming ordinary prose (one long paragraph, no blank lines) → `boundary == 0`
  → `_do_parse_and_wrap()` re-parses and **re-wraps the entire message on every
  append**. This is O(total) per token.
- Even when the boundary hits, `_update_incremental()` re-parses the whole
  prefix whenever `text[:boundary]` changes (`markdown.py:783`), so advancing
  the boundary more frequently would re-introduce O(total).
- The tail-*raster* path (`Box.render` → `take_dirty_from_line` →
  `MessageView` clip) is already correct and cheap; the cost is in parse/wrap,
  not paint.

Evidence: no stream/append scenario exists in `notes/bench_render.py`; the
existing samples in `test_streaming_incremental.py` include the
"one long paragraph with no blank lines" case but only guard *correctness*, not
cost.

## 2. Invariants (must not break)

- `test_streaming_incremental.py`: incremental parse/render result **identical**
  to a full parse/render at every chunk size (1, 2, 5, 13), including a full
  rendered `Buffer` snapshot comparison.
- Public `MarkdownComponent` surface unchanged: `update`, `update(append=True)`,
  `take_dirty_from_line`, `get_preferred_height`, `set_layout`, `render`.
- `Box`/`MessageView` tail-raster contract unchanged (`dirty_from` is the first
  changed **wrapped** line; `None` = full redraw).

## 3. Design

### 3.1 Resumable block parser state

`BlockParser.parse()` is a state machine over `in_code_block` / `in_table`.
Replace whole-text parsing with an incremental parser that **carries state**
across appends:

```
class IncrementalBlockParser:
    committed: list[Block]          # blocks whose meaning cannot change
    open_start_line: int            # first line of the open region
    fence: str | None               # open fence marker, or None
    in_table: bool
```

- `feed(lines, final: bool)` consumes newly-complete lines and commits any that
  are provably immutable, returning newly committed blocks.
- The parser must be **state-seeded**, not restarted: a suffix cannot be parsed
  with a fresh parser once the boundary can fall inside a fence/table.

### 3.2 Commit rule (line atomicity)

A line is committed only when future appends cannot change its classification
or content:

- Never commit the **last** line (it may grow without a terminating `\n`).
- Never commit lines inside an **open code fence** (except everything up to the
  open last line once the fence is closed).
- Never commit any row of an **open table**; commit the whole table once a
  non-table line closes it.
- Classification depends on line *i* and line *i+1* (table-header lookahead), so
  commit lags arrival by one line.

Start conservative: commit all lines up to the open region; if the open region
is a fence/table, hold it whole. Optimise later only if benchmarks demand it.

### 3.3 Append-only parse/wrap caches

Replace `_prefix_src` / `_prefix_parsed` / `_prefix_wrapped` with:

- `_committed_parsed: list[list[StyledSegment]]` — appended to, never reparsed.
- `_committed_wrapped: list[list[StyledSegment]]` — appended to, never rewrapped.

On append: commit new full lines → parse+wrap only their blocks → extend the
caches. The open region is parsed+wrapped fresh each append and concatenated
after the caches (never mutating them).

Width change (`set_layout`) remains a full re-wrap of everything (rare; keep as
today).

### 3.4 Open-region rendering (approach A — deferred inline parse)

The open (last) line is rendered **plain** (no `InlineParser`) and inline-parsed
only when its `\n` commits it. Rationale: each reveal step currently re-scans the
whole logical line, so char-by-char reveal is O(line²); deferring makes each
append O(delta) for the open line.

- Consistent with today's behaviour, which already emits unmatched `**`/`` ` ``
  literally while streaming.
- Behaviour change to document: a **closed** span (`**bold**`) on a still-open
  line is not styled until the newline lands.
- Code blocks: keep per-line highlighting on commit; the open code line renders
  plain.
- Tables: the open table is fully re-rendered each append (column widths need
  all rows); bounded by table size.

### 3.5 `dirty_from` semantics

`_dirty_from_line = len(_committed_wrapped)` (start of the open region), reduced
to the minimum since the last render. Consequences:

- Appending to a paragraph dirties only the open line's wrapped rows.
- Appending a table row dirties from the **table start** (since the whole open
  table is re-rendered).
- Closing a fence/table folds the now-committed lines into the caches and dirties
  from the fold point.

## 4. Workstreams

- **M1 — Resumable parser + commit rule.** Add `IncrementalBlockParser` with
  carried state; keep the old whole-text `BlockParser.parse` as the reference
  implementation used by tests/full-parse fallback.
- **M2 — Append-only caches.** Rework `_update_incremental` to extend caches;
  delete `_last_stable_blank` and the prefix-reparse branch.
- **M3 — Open region + approach A.** Plain-render the open line; parse on commit.
  Table re-render via open region.
- **M4 — `dirty_from` wiring.** Derive from committed width; verify table/fence
  cases against `Box`/`MessageView`.
- **M5 — Benchmarks.** Extend `notes/bench_render.py` with a `stream` scenario
  (append a chunk to a growing `PicoMsg` each frame, increasing repeat counts)
  and a pure `MarkdownComponent.update(append=True)` micro-bench
  (µs/append vs total length for prose / code / table). Save to
  `notes/bench_stream_baseline.json`.
- **M6 — Cleanup.** Remove dead incremental state and fallbacks; run vulture.

Each workstream ends green on the §6 gates.

## 5. Tests

Keep all existing. Add:

- Incremental == full across streams that cross: fence open/close, blank lines
  inside fences, adjacent tables, table at end of stream, fence never closed,
  table header at end of stream, long single paragraph.
- `dirty_from` equals the first changed wrapped line for paragraph append and
  table-row append.
- Idempotence: `update(same, append=True)` produces no dirty change.
- Perf assertion (optional, generous): per-append time flat as total length
  grows by 10×.

## 6. Gates

```bash
.pixi/envs/default/bin/python -m pytest test/ -q
.pixi/envs/default/bin/python -m compileall -q pico_chat
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80
.pixi/envs/default/bin/python -m pytest test/test_streaming_incremental.py -q
.pixi/envs/default/bin/python notes/bench_render.py --load notes/bench_baseline.json
```

## 7. Risks / fallback

- **Risk:** state-seeded parsing is the crux; getting fence/table resume wrong
  breaks the incremental==full invariant. The parametrized tests catch it.
- **Fallback:** if full resumability proves too risky, widen `_last_stable_blank`
  to "last committed line outside a stateful region" (still far better than
  blank-only) and gate the open region on blank-or-newline. Same interface, less
  state.
- **Risk:** approach A delays styling of closed spans on the open line. If
  unacceptable, keep inline parsing on the open line and accept O(line) per
  append, coalescing reveal updates by word for long lines.

## 8. Out of scope

The stream-interpolation revealer (smoothing, `smooth_target_fps`, one-chunk
buffer, `Compositor.on_frame`). This plan makes that feature cheap; it does not
build it.
