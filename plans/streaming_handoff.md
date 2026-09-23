# Streaming Work — Handoff

**Created:** 2026-09-23 · **Status:** planned, no code yet
**Read first:** `.wiki/notes/principles.md`, `HANDOFF.md`, then the two plans below.

Two sequential workstreams. Do them in order and land each on its own:

1. `plans/markdown_streaming_refactor.md` — per-line atomic incremental markdown.
2. `plans/stream_interpolation.md` — adaptive reveal smoothing.

Start with (1). It is an independently justified performance fix and may remove
most perceived stream jank on its own. Measure before starting (2).

---

## Why

`MarkdownComponent.update(append=True)` has an incremental path, but its fast
path is gated on `_last_stable_blank()` (`markdown.py:685`), which only cuts at a
blank line outside a code fence. Streaming prose (one long paragraph) → boundary
0 → **full re-parse + re-wrap of the whole message on every token**. The tail
*raster* path is already fine (`Box.render` `box.py:250` → `take_dirty_from_line`
→ `MessageView` clip `message_view.py:110`); the cost is parse/wrap.

## Locked decisions (both plans)

- Interpolate **any** visible streamed text — content and reasoning, no type
  sniffing. No cursor rendered in LLM messages.
- Markdown: approach **A** (render the open line plain; inline-parse on newline).
- Grain = **non-whitespace grapheme clusters**; whitespace free; coarse steps
  snap to word ends.
- Smoothing only, no cushion knob. **One-chunk buffer / 100 ms cap**, merge on
  overlap, snap when behind.
- `smooth_target_fps` sets reveal cadence; grain is derived.
- Config minimal: `stream_smoothing`, `smooth_target_fps`.
- Clock = `Compositor.add_frame_callback` (not routing `TickEvent` into widgets).
- `base_text` stays canonical full arrived text; `_reveal_len` is the rendered
  prefix; `ingest()` vs `reveal_to(n)`.
- Displace `set_streaming_active` / `streaming_active` and the per-token
  `request_render()` (`generation_presenter.py:66`).

## Confirmed at session start (assumed accepted, flag if not)

- Natural `Done`: let the revealer drain, then finalize from the frame callback
  (spinner persists ≤100 ms). Snap only at hard boundaries.
- Vendor a small `ui/tui/graphemes.py` cluster splitter rather than adding a
  `regex` dependency.

## Guardrails

- `test/test_streaming_incremental.py` — incremental must equal full at every
  chunk size (1, 2, 5, 13), parse **and** rendered `Buffer` snapshot.
- `harness/` must not import `ui/` (`test/test_core_ui_boundary.py`).
- Public `MarkdownComponent` surface unchanged (`update`, `take_dirty_from_line`,
  `get_preferred_height`, `set_layout`, `render`).

## Gates (every step)

```bash
.pixi/envs/default/bin/python -m pytest test/ -q
.pixi/envs/default/bin/python -m compileall -q pico_chat
.pixi/envs/default/bin/python -m vulture pico_chat --min-confidence 80
.pixi/envs/default/bin/python -m pytest test/test_core_ui_boundary.py -q
.pixi/envs/default/bin/python -m pytest test/test_streaming_incremental.py -q
.pixi/envs/default/bin/python notes/bench_render.py --load notes/bench_baseline.json
```

## Benchmarks

`notes/bench_render.py` exists (`steady`/`rerender`/`scroll`/`hittest`, baselines
`notes/bench_baseline*.json`) but does **not** cover the append/stream path. Add
a `stream` scenario + a pure `update(append=True)` µs/append micro-bench; save to
`notes/bench_stream_baseline.json`. Use it to prove "no performance impact".

## Do not

- Commit or `git add` (user commits manually).
- Add features/UI beyond the two plans. Config files are the settings UI.
