# Format Streaming Plan

## Context

The TUI rendering pipeline has improved FPS and basic viewport culling, but CPU usage still grows during long LLM streaming responses.

Current root causes identified:
- Message streaming currently triggers full message reformatting on each chunk (`Message.append -> reformat -> _format_line_wrap`), which scales with accumulated message size.
- Box rendering still re-rasterizes full message box content on message changes.
- Blitting and offscreen culling are improved, but they do not solve full-text rewrap cost.

Future product direction:
- Markdown interpretation may be introduced later (including block structures such as tables).
- The streaming strategy should remain compatible with richer formatting and avoid a rewrite.

---

## Objective

Design and implement a streaming text/layout pipeline that:
1. Keeps per-chunk cost close to **O(delta)** instead of **O(total_message_size)**.
2. Preserves correctness under resize, focus/style updates, and non-append edits.
3. Supports future markdown/block formatting (including tables) with localized invalidation.
4. Integrates with current dirty-rect compositor approach.

---

## Constraints

- Existing TUI architecture should be evolved incrementally (avoid risky full rewrite).
- Streaming must remain visually responsive (no "wait for interaction" regressions).
- Idle behavior should still obey target FPS pacing semantics.
- Fallback paths must be robust: when fast-path assumptions break, correctness wins.
- Design must tolerate future block-level formatting (paragraphs, code blocks, tables).

---

## Concerned Files (Starter Exploration Map)

### Primary streaming + formatting
- `pico_chat/ui/chat_message.py`
- `pico_chat/ui/tui/layout_utils.py`
- `pico_chat/ui/tui/components/text.py`

### Rendering + buffering
- `pico_chat/ui/tui/components/box.py`
- `pico_chat/ui/tui/buffer.py`
- `pico_chat/ui/tui/compositor.py`

### Message container + viewport behavior
- `pico_chat/ui/chat_history_panel.py`
- `pico_chat/ui/tui/container.py`

### App orchestration / streaming lifecycle
- `pico_chat/ui/app.py`

---

## Plan

## Phase A — Introduce a format/layout model boundary

### A1. Message model split
Add explicit per-message state layers:
- `raw_text`
- `blocks` (initially a single plain-text block)
- `layout_lines` (visual lines for current width/style)
- invalidation cursor(s): `invalid_from_block_idx`, optional `invalid_from_line_idx`

### A2. Keep current behavior as fallback
- Preserve existing full `reformat` path.
- Add a feature-gated fast path used only for append streaming updates.

Deliverable:
- No functional UI change yet, only data model + fallback-safe plumbing.

---

## Phase B — Incremental append formatting (plain text first)

### B1. Append-only fast path
For normal streaming chunks:
- Parse only appended delta from `raw_text[last_processed_index:]`.
- Continue wrapping from current tail line state.
- Append new visual lines without reprocessing finalized prefix.

### B2. Invalidation behavior
Fallback to full re-layout when:
- width changes,
- explicit `set_text`/edit-in-middle occurs,
- parser confidence is low,
- format mode changes.

Deliverable:
- Streaming cost scales with chunk size, not full message size.

---

## Phase C — Incremental rendering path in Box/SubBuffer

### C1. SubBuffer growth usage
- Use `SubBuffer.grow(new_height)` when message grows in append-only mode.
- Re-raster only impacted tail region + border/footer rows as needed.

### C2. Tail dirty-rect reporting
- Emit dirty rect limited to modified rows rather than full message box.
- Keep full-box redraw fallback for style/focus/resize changes.

Deliverable:
- Lower raster and copy work per streaming chunk.

---

## Phase D — Markdown-ready block evolution

### D1. Block types
Evolve `blocks` from plain text to typed blocks:
- paragraph
- code block
- (future) table/list/quote

### D2. Localized relayout
- Map source span -> block(s) -> line ranges.
- Re-layout only impacted block range for append-safe cases.

Deliverable:
- Architecture supports markdown/tables without redoing the streaming engine.

---

## Phase E — Instrumentation and guardrails

Track metrics to validate impact and prevent regressions:
- `stream_chunks`
- `fast_path_hits` vs `full_fallbacks`
- `lines_relaid_per_chunk`
- `box_rows_rerasterized_per_chunk`
- frame/render timing + CPU snapshots (manual benchmarking)

Acceptance goals:
- CPU growth with long streams is significantly flatter than baseline.
- Streaming responsiveness remains immediate.
- Correctness preserved across resize/focus/scroll/edit operations.

---

## Suggested Implementation Order

1. Phase A (model boundary)
2. Phase B (plain-text incremental append)
3. Phase C (SubBuffer grow + tail dirty rect)
4. Phase E (metrics + verify)
5. Phase D (typed markdown blocks)

---

## Notes for Future Handoff

- Prefer small, reversible PRs by phase.
- Keep each phase behind clear fallback logic.
- Validate after each phase with long streaming responses and resize/scroll interaction tests.
- Start with plain text incremental logic first; markdown blocks should layer on top of the same invalidation model.
