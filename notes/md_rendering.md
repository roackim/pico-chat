# Markdown Rendering Plan

## Current State

Markdown rendering is **completely disabled**. The file `pico_chat/ui/legacy_markdown_rendering.py` is dead code — it used regex to bake ANSI escape codes directly into strings. This approach is flawed because:

- ANSI codes inside strings corrupt line-width calculations during wrapping
- No per-cell style control (bold/italic are just ANSI sequences, not `Cell` attributes)
- Does not integrate with the Cell-based rendering pipeline

---

## Difficulty: Medium (naive renderer)

The rendering primitives exist — the `Cell` dataclass supports `fg`, `bg`, `bold`, `reverse`. The work is in **parsing + integration**, not rendering.

### Supported Features (Phase 1)

| Feature | Syntax | Approach |
|---------|--------|----------|
| Headers | `#` to `######` | Line-level parse → bold + color |
| Bold | `**text**` | Inline → `bold=True` on Cells |
| Italic | `*text*` | Inline → `reverse=True` or color |
| Inline code | `` `code` `` | Inline → muted fg + bg |
| Code blocks | `` ```lang ... ``` `` | Block → bg-colored block |
| Unordered lists | `-`, `*` | Line-level → bullet + indent |
| Ordered lists | `1.` | Line-level → number + indent |
| Blockquotes | `>` | Line-level → indent + muted color |
| Horizontal rules | `---` | Line-level → box-drawing chars |
| Links | `[text](url)` | Show text, optional color |
| Paragraphs | Blank-line separated | Line-level → spacing |

### Deferred (Phase 2+)

- Nested inline formatting (`**bold *and italic* text**`)
- Tables
- Images
- Footnotes / references
- Escaping (`\*literal\*`)
- Hard breaks (trailing spaces or `\\`)

---

## Rendering Pipeline (current)

```
Message.base_text (raw string)
  → _format_line_wrap() → formatted_text (string with ANSI)
    → TextComponent._lines (split by \n)
      → buffer.write_str() → Cell grid
        → Terminal output
```

The key integration challenge: `Message` currently operates on plain strings. Markdown rendering requires **styled text** — segments with attached style attributes.

---

## Architecture Decision

**Two-component approach:**

1. Keep `TextComponent` for plain text (tool output, system messages, etc.)
2. Add `MarkdownComponent` for rendered markdown (LLM responses)

The raw markdown is always preserved in `Message.base_text`. The rendered version is computed lazily in `MarkdownComponent.render()`.

---

## Implementation Plan

### Step 1 — Styled Segment Representation

Define a simple intermediate representation:

```python
@dataclass
class StyledSegment:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    fg: Optional[RGB] = None
    bg: Optional[RGB] = None
```

A parsed markdown document becomes a list of **blocks**, each containing **inline segments**.

### Step 2 — Naive Markdown Parser

Build a block-level parser (state machine, not regex):

- Split input into lines
- Identify block types: header, code_block, list, blockquote, hr, paragraph
- For each paragraph/block, run an inline parser to extract segments (bold, italic, code, links)

Use a simple sequential scanner. Avoid regex for inline parsing to handle nesting in a controlled way.

### Step 3 — MarkdownComponent

Create `MarkdownComponent(Component)` that:

- Accepts raw markdown text in constructor
- Parses once on init (or re-parses on `update()`)
- In `render(buffer)`, walks styled segments and writes Cells with appropriate attributes
- Handles its own line wrapping, respecting style boundaries (don't split a styled segment mid-word)

### Step 4 — Integrate into Message

Changes to `pico_chat/ui/chat_message.py`:

- Add `render_markdown: bool` parameter to `__init__`
- When `True`, create a `MarkdownComponent` instead of `TextComponent`
- `base_text` always stores raw markdown (already the case)
- `get_formatted()` returns `base_text` for copy/export (raw, not rendered)
- `reformat()` triggers re-wrap in `MarkdownComponent`

### Step 5 — Wire into Chat Flow

Decide which message types render markdown:

- `PicoMsg` / `ThinkingMsg` → render markdown
- `UserMsg` → plain text (user input)
- `ToolCallMsg` / `ToolDraftMsg` → plain text (structured output)
- `SysMsg` variants → plain text

---

## Files to Create

| File | Purpose |
|------|---------|
| `pico_chat/ui/tui/components/markdown.py` | `MarkdownComponent` + parser + `StyledSegment` |

## Files to Modify

| File | Changes |
|------|---------|
| `pico_chat/ui/chat_message.py` | Add `render_markdown` flag, conditional component creation |
| `pico_chat/ui/tui/components/__init__.py` | Export `MarkdownComponent` |
| `pico_chat/ui/legacy_markdown_rendering.py` | Delete or rename to `.bak` |

---

## Files to Reference

### Core Rendering

| File | Why |
|------|-----|
| `pico_chat/ui/tui/components/base.py` | `Component` base class — `render(buffer)`, `mark_changed()` |
| `pico_chat/ui/tui/components/text.py` | `TextComponent` — reference for how text is rendered to buffer |
| `pico_chat/ui/tui/buffer.py` | `Cell` dataclass, `Buffer.set()`, `Buffer.write_str()` — rendering primitives |
| `pico_chat/ui/tui/colors.py` | `RGB`, `theme` — available colors for styling |
| `pico_chat/ui/tui/layout_utils.py` | `wrap_text()`, `display_width()`, `strip_ansi()` — text wrapping utilities |

### Message System

| File | Why |
|------|-----|
| `pico_chat/ui/chat_message.py` | `Message` class — where rendering decision is made |
| `pico_chat/ui/chat_history_panel.py` | `ChatHistoryPanel` — manages message layout, scrolling, reformat on resize |
| `pico_chat/ui/tui/msg_types.py` | `MsgType` hierarchy — decide which types get markdown |

### Existing (Dead) Code

| File | Why |
|------|-----|
| `pico_chat/ui/legacy_markdown_rendering.py` | Reference for what was tried before (and why it didn't work) |

### Architecture Docs

| File | Why |
|------|-----|
| `.wiki/notes/ui.md` | Full UI architecture overview |
| `.wiki/tree/ui.md` | UI module structure |
| `.wiki/tree/ui-tui-components.md` | Component model details |

---

## Estimated Effort

- Parser (block + inline): ~200-300 lines
- `MarkdownComponent` + wrapping: ~100-150 lines
- `Message` integration: ~30-50 lines
- Testing + edge cases: ~50-100 lines

**Total: ~400-600 lines across 1-2 files**
