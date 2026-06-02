"""Naive markdown parser and style system for Pico-Chat TUI.

Parses markdown into a list of display lines, each being a list of
StyledSegment objects.  Styles are driven by pico_cfg.config.markdown_styles.
Designed for live re-parsing during streaming — full re-parse per update.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from wcwidth import wcswidth

from pico_chat import pico_cfg
from pico_chat.ui.tui.colors import RGB, theme
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components.base import Component


# ---------------------------------------------------------------------------
# Style resolution helpers
# ---------------------------------------------------------------------------

def _resolve_color(value: Optional[str]) -> Optional[tuple[int, int, int]]:
    """Convert a hex color string (or None) to an RGB tuple."""
    if value is None:
        return None
    c = RGB(value)
    return (c.r, c.g, c.b)


def _get_style(element: str) -> dict:
    """Return the resolved style dict for a markdown element name.

    Reads from pico_cfg.config.markdown_styles, converts hex strings to
    RGB tuples, and fills in missing keys with safe defaults.
    """
    cfg = pico_cfg.config.markdown_styles.get(element, {})
    return {
        "fg": _resolve_color(cfg.get("fg")),
        "bg": _resolve_color(cfg.get("bg")),
        "bold": bool(cfg.get("bold", False)),
        "reverse": bool(cfg.get("reverse", False)),
    }


# ---------------------------------------------------------------------------
# StyledSegment
# ---------------------------------------------------------------------------

@dataclass
class StyledSegment:
    text: str
    fg: Optional[tuple[int, int, int]] = None
    bg: Optional[tuple[int, int, int]] = None
    bold: bool = False
    reverse: bool = False

    @property
    def display_width(self) -> int:
        w = wcswidth(self.text)
        return w if w >= 0 else len(self.text)


# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------

@dataclass
class ParagraphLine:
    """A paragraph / text line — will be inline-parsed into segments."""
    raw: str


@dataclass
class HeaderLine:
    """A header line: # to ######."""
    level: int
    text: str


@dataclass
class CodeBlockLine:
    """A line inside a fenced code block. Not inline-parsed."""
    text: str
    lang: str = ""


@dataclass
class UnorderedListItemLine:
    """A line belonging to an unordered list."""
    text: str
    indent: int = 0


@dataclass
class OrderedListItemLine:
    """A line belonging to an ordered list."""
    number: int
    text: str
    indent: int = 0


@dataclass
class QuoteLine:
    """A blockquote line."""
    text: str
    indent: int = 0


@dataclass
class HrLine:
    """Horizontal rule: --- or *** or ___."""
    pass


@dataclass
class EmptyLine:
    """Blank line between paragraphs."""
    pass


Block = (
    ParagraphLine
    | HeaderLine
    | CodeBlockLine
    | UnorderedListItemLine
    | OrderedListItemLine
    | QuoteLine
    | HrLine
    | EmptyLine
)


# ---------------------------------------------------------------------------
# Block-level parser
# ---------------------------------------------------------------------------

class BlockParser:
    """Parse markdown text into a list of Block objects (one per line)."""

    def parse(self, text: str) -> List[Block]:
        blocks: List[Block] = []
        lines = text.split("\n")
        i = 0
        in_code_block = False
        code_fence = ""  # the opening fence (``` or ~~~) optionally with lang

        while i < len(lines):
            line = lines[i]

            # --- Code block state machine ---
            if in_code_block:
                # Check for closing fence
                stripped = line.strip()
                if stripped.startswith(code_fence.rstrip()):
                    in_code_block = False
                    i += 1
                    continue
                blocks.append(CodeBlockLine(text=line))
                i += 1
                continue

            # Check for opening fence
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence_char = stripped[0]
                code_fence = fence_char * 3
                lang = stripped[len(code_fence):].strip()
                in_code_block = True
                i += 1
                continue

            # --- Non-code-block lines ---

            # Empty line
            if stripped == "":
                blocks.append(EmptyLine())
                i += 1
                continue

            # Horizontal rule: --- or *** or ___ (at least 3, optional spaces)
            if self._is_hr(stripped):
                blocks.append(HrLine())
                i += 1
                continue

            # Header
            header = self._parse_header(line)
            if header is not None:
                blocks.append(header)
                i += 1
                continue

            # Blockquote
            quote = self._parse_quote(line)
            if quote is not None:
                blocks.append(quote)
                i += 1
                continue

            # Unordered list
            ul_item = self._parse_unordered_list(line)
            if ul_item is not None:
                blocks.append(ul_item)
                i += 1
                continue

            # Ordered list
            ol_item = self._parse_ordered_list(line)
            if ol_item is not None:
                blocks.append(ol_item)
                i += 1
                continue

            # Default: paragraph
            blocks.append(ParagraphLine(raw=line))
            i += 1

        return blocks

    # --- helpers ---

    def _is_hr(self, s: str) -> bool:
        cleaned = s.replace(" ", "")
        if len(cleaned) < 3:
            return False
        return cleaned in ("---", "___") or (all(c == "-" for c in cleaned)) or (all(c == "*" for c in cleaned)) or (all(c == "_" for c in cleaned))

    def _parse_header(self, line: str) -> Optional[HeaderLine]:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            return None
        level = 0
        for ch in stripped:
            if ch == "#":
                level += 1
            else:
                break
        if level > 6:
            return None
        # Must have a space after # (or be just #s)
        rest = stripped[level:]
        if rest and rest[0] != " ":
            return None
        text = rest.strip()
        return HeaderLine(level=level, text=text)

    def _parse_quote(self, line: str) -> Optional[QuoteLine]:
        stripped = line.lstrip()
        if not stripped.startswith(">"):
            return None
        # Remove leading > and optional space
        text = stripped[1:]
        if text and text[0] == " ":
            text = text[1:]
        # Count indent (spaces before >)
        indent = len(line) - len(line.lstrip())
        return QuoteLine(text=text, indent=indent)

    def _parse_unordered_list(self, line: str) -> Optional[UnorderedListItemLine]:
        stripped = line.lstrip()
        if len(stripped) < 2:
            return None
        marker = stripped[0]
        if marker not in ("-", "*", "+"):
            return None
        if stripped[1] != " ":
            return None
        indent = len(line) - len(line.lstrip())
        text = stripped[2:]
        return UnorderedListItemLine(text=text, indent=indent)

    def _parse_ordered_list(self, line: str) -> Optional[OrderedListItemLine]:
        stripped = line.lstrip()
        # Match: digits followed by dot and space
        i = 0
        while i < len(stripped) and stripped[i].isdigit():
            i += 1
        if i == 0 or i >= len(stripped):
            return None
        if stripped[i] != ".":
            return None
        if i + 1 >= len(stripped) or stripped[i + 1] != " ":
            return None
        number = int(stripped[:i])
        indent = len(line) - len(line.lstrip())
        text = stripped[i + 2:]
        return OrderedListItemLine(number=number, text=text, indent=indent)


# ---------------------------------------------------------------------------
# Inline parser
# ---------------------------------------------------------------------------

class InlineParser:
    """Parse a single line of markdown text into a list of StyledSegment.

    Handles: **bold**, *italic*, `code`, [text](url).
    Uses a sequential character scanner — no regex — for controlled boundary
    handling.  Unmatched openers are emitted as plain text.
    """

    def parse(self, text: str) -> List[StyledSegment]:
        segments: List[StyledSegment] = []
        i = 0
        n = len(text)

        while i < n:
            # Inline code: `...`
            if text[i] == "`":
                end = text.find("`", i + 1)
                if end == -1:
                    # Unclosed backtick — emit as plain
                    segments.append(StyledSegment(text[i]))
                    i += 1
                else:
                    code_text = text[i + 1:end]
                    style = _get_style("code")
                    segments.append(StyledSegment(code_text, **style))
                    i = end + 1
                continue

            # Bold: **...**
            if text[i:i + 2] == "**":
                end = text.find("**", i + 2)
                if end == -1:
                    segments.append(StyledSegment(text[i]))
                    i += 1
                else:
                    inner = text[i + 2:end]
                    style = _get_style("bold")
                    segments.append(StyledSegment(inner, **style))
                    i = end + 2
                continue

            # Italic: *...*  (but not **)
            if text[i] == "*" and (i + 1 >= n or text[i + 1] != "*"):
                end = self._find_closing_star(text, i + 1)
                if end is None:
                    segments.append(StyledSegment(text[i]))
                    i += 1
                else:
                    inner = text[i + 1:end]
                    style = _get_style("italic")
                    segments.append(StyledSegment(inner, **style))
                    i = end + 1
                continue

            # Link: [text](url)
            if text[i] == "[":
                result = self._parse_link(text, i)
                if result is not None:
                    seg, consumed = result
                    segments.append(seg)
                    i += consumed
                    continue

            # Plain character
            segments.append(StyledSegment(text[i]))
            i += 1

        return segments

    def _find_closing_star(self, text: str, start: int) -> Optional[int]:
        """Find the first single * at or after start that isn't followed by another *."""
        i = start
        n = len(text)
        while i < n:
            if text[i] == "*":
                # Make sure it's a single star (not **)
                if i + 1 >= n or text[i + 1] != "*":
                    return i
                # Skip past **
                i += 2
            else:
                i += 1
        return None

    def _parse_link(self, text: str, start: int) -> Optional[tuple[StyledSegment, int]]:
        """Try to parse a [text](url) link starting at position start.

        Returns (segment, chars_consumed) or None if not a valid link.
        """
        # Find closing ]
        bracket_end = text.find("]", start + 1)
        if bracket_end == -1:
            return None
        # Must be immediately followed by (
        if bracket_end + 1 >= len(text) or text[bracket_end + 1] != "(":
            return None
        # Find closing )
        paren_end = text.find(")", bracket_end + 2)
        if paren_end == -1:
            return None

        link_text = text[start + 1:bracket_end]
        # url = text[bracket_end + 2:paren_end]  # available but not rendered
        style = _get_style("link")
        seg = StyledSegment(link_text, **style)
        consumed = paren_end - start + 1
        return (seg, consumed)


# ---------------------------------------------------------------------------
# Markdown — high-level wrapper
# ---------------------------------------------------------------------------

class Markdown:
    """Parse markdown text into a list of display lines (each a list of
    StyledSegment).

    Usage:
        md = Markdown()
        lines = md.parse("# Hello **world**")
        # lines -> [ [<StyledSegment("# Hello world") with header1 style> ] ]

        # For live updates during streaming:
        md = Markdown()
        for chunk in stream:
            lines = md.parse(full_text_so_far)
    """

    def __init__(self):
        self._block_parser = BlockParser()
        self._inline_parser = InlineParser()

    def parse(self, text: str) -> List[List[StyledSegment]]:
        """Return a list of lines; each line is a list of StyledSegment."""
        if not text:
            return []

        blocks = self._block_parser.parse(text)
        result: List[List[StyledSegment]] = []

        for block in blocks:
            rendered = self._render_block(block)
            result.extend(rendered)

        return result

    def _render_block(self, block: Block) -> List[List[StyledSegment]]:
        if isinstance(block, EmptyLine):
            return [[]]

        if isinstance(block, HeaderLine):
            element_name = f"header{block.level}"
            style = _get_style(element_name)
            # Add header marker for visual clarity
            marker = self._header_marker(block.level)
            segments = [StyledSegment(marker, **style)]
            # Inline-parse the header text for bold/code/etc inside headers
            inner = self._inline_parser.parse(block.text)
            # Merge header style into each segment
            for seg in inner:
                seg.bold = seg.bold or style["bold"]
                seg.reverse = seg.reverse or style["reverse"]
                if seg.fg is None:
                    seg.fg = style["fg"]
                if seg.bg is None:
                    seg.bg = style["bg"]
            segments.extend(inner)
            return [segments]

        if isinstance(block, CodeBlockLine):
            style = _get_style("code_block")
            return [[StyledSegment(block.text, **style)]]

        if isinstance(block, QuoteLine):
            style = _get_style("quote")
            segments = [StyledSegment("> ", **style)]
            inner = self._inline_parser.parse(block.text)
            for seg in inner:
                seg.reverse = seg.reverse or style["reverse"]
                if seg.fg is None:
                    seg.fg = style["fg"]
                if seg.bg is None:
                    seg.bg = style["bg"]
            segments.extend(inner)
            return [segments]

        if isinstance(block, UnorderedListItemLine):
            style = _get_style("list")
            indent_str = "  " * block.indent
            segments = [StyledSegment(indent_str + "- ")]
            inner = self._inline_parser.parse(block.text)
            for seg in inner:
                if seg.fg is None:
                    seg.fg = style["fg"]
                if seg.bg is None:
                    seg.bg = style["bg"]
            segments.extend(inner)
            return [segments]

        if isinstance(block, OrderedListItemLine):
            style = _get_style("list")
            indent_str = "  " * block.indent
            prefix = f"{indent_str}{block.number}. "
            segments = [StyledSegment(prefix)]
            inner = self._inline_parser.parse(block.text)
            for seg in inner:
                if seg.fg is None:
                    seg.fg = style["fg"]
                if seg.bg is None:
                    seg.bg = style["bg"]
            segments.extend(inner)
            return [segments]

        if isinstance(block, HrLine):
            style = _get_style("hr")
            # Sentinel segment — MarkdownComponent.render replaces with box-drawing chars
            return [[StyledSegment("hr", **style)]]

        if isinstance(block, ParagraphLine):
            return [self._inline_parser.parse(block.raw)]

        return [[]]

    def _header_marker(self, level: int) -> str:
        markers = ["", "## ", "### ", "#### ", "##### ", "###### ", "####### "]
        return markers[level] if level < len(markers) else ""


# ---------------------------------------------------------------------------
# MarkdownComponent — TUI component
# ---------------------------------------------------------------------------

class MarkdownComponent(Component):
    """Renders markdown text as styled segments with segment-aware wrapping.

    Parses on every `update()` call, making it suitable for live streaming
    where the full text changes between calls.
    """

    def __init__(self, text: str = "", fg=None, bg=None, id: Optional[str] = None):
        super().__init__(id)
        self.fg = fg
        self.bg = bg
        self._md = Markdown()
        self._raw_text = text
        self._parsed_lines: List[List[StyledSegment]] = []
        self._wrapped_lines: List[List[StyledSegment]] = []
        self._last_wrap_width = -1
        self._do_parse_and_wrap(text)

    def update(self, text: str):
        """Update with new markdown text. Re-parses and re-wraps."""
        self._raw_text = text
        self._last_wrap_width = -1  # Force re-wrap
        self._do_parse_and_wrap(text)
        self.mark_changed()

    def _do_parse_and_wrap(self, text: str):
        self._parsed_lines = self._md.parse(text)
        # Re-wrap if width is set
        if self.width > 0:
            self._wrapped_lines = self._wrap_all(self._parsed_lines, self.width)
            self._last_wrap_width = self.width
        else:
            self._wrapped_lines = self._parsed_lines

    def set_layout(self, x: int, y: int, width: int, height: int):
        old_width = self.width
        super().set_layout(x, y, width, height)
        # Re-wrap on width change
        if width != old_width and width > 0:
            self._wrapped_lines = self._wrap_all(self._parsed_lines, width)
            self._last_wrap_width = width

    def get_preferred_height(self, width: int) -> int:
        """Calculate height needed for wrapped content."""
        if width <= 0:
            return 0
        if self._last_wrap_width != width:
            self._wrapped_lines = self._wrap_all(self._parsed_lines, width)
            self._last_wrap_width = width
        return len(self._wrapped_lines)

    # --- Wrapping ---

    def _wrap_all(self, lines: List[List[StyledSegment]], max_width: int) -> List[List[StyledSegment]]:
        """Wrap all lines to max_width, preserving segment styles."""
        result: List[List[StyledSegment]] = []
        for line in lines:
            wrapped = self._wrap_line(line, max_width)
            result.extend(wrapped)
        return result

    def _wrap_line(self, segments: List[StyledSegment], max_width: int) -> List[List[StyledSegment]]:
        """Wrap a single line of segments to max_width.

        Splits at word boundaries (spaces between segments or within segments).
        Returns a list of wrapped lines, each being a list of segments.
        """
        # Special case: HR sentinel — return as-is, component.render handles it
        if len(segments) == 1 and segments[0].text == "hr":
            return [segments]

        # Split segments into "words" (runs of non-space text with their styles)
        words = self._split_into_words(segments)

        # If no words (empty line)
        if not words:
            return [[]]

        wrapped: List[List[StyledSegment]] = []
        current_line: List[StyledSegment] = []
        current_width = 0

        for word, word_width in words:
            needed = (current_width + 1 + word_width) if current_line else word_width
            if needed <= max_width:
                # Fits on current line
                if current_line:
                    current_line.append(StyledSegment(" "))
                    current_width += 1
                current_line.extend(word)
                current_width += word_width
            else:
                # Doesn't fit — push current line and start new
                if current_line:
                    wrapped.append(current_line)
                    current_line = []
                    current_width = 0

                # Try to fit word on new line
                if word_width <= max_width:
                    current_line.extend(word)
                    current_width = word_width
                else:
                    # Word is longer than max_width — hard-break it
                    broken = self._break_segments(word, max_width)
                    for part in broken[:-1]:
                        wrapped.append(part)
                    current_line = broken[-1]
                    current_width = sum(s.display_width for s in current_line)

        if current_line:
            wrapped.append(current_line)

        return wrapped if wrapped else [[]]

    def _split_into_words(self, segments: List[StyledSegment]) -> List[tuple[List[StyledSegment], int]]:
        """Split segments into words separated by spaces.

        Returns list of (segments_for_word, word_width).
        """
        words: List[tuple[List[StyledSegment], int]] = []
        current_word: List[StyledSegment] = []

        for seg in segments:
            # Split segment text by spaces, preserving style
            parts = seg.text.split(" ")
            for idx, part in enumerate(parts):
                if part:
                    current_word.append(StyledSegment(part, seg.fg, seg.bg, seg.bold, seg.reverse))
                else:
                    # Space — flush current word
                    if current_word:
                        w = sum(s.display_width for s in current_word)
                        words.append((list(current_word), w))
                        current_word = []
                    # If multiple spaces, emit empty word for spacing
                    if idx > 0 or (idx == 0 and seg.text[0:1] == " "):
                        # Only add spacer if it's not the leading space
                        pass

        if current_word:
            w = sum(s.display_width for s in current_word)
            words.append((list(current_word), w))

        return words

    def _break_segments(self, segments: List[StyledSegment], max_width: int) -> List[List[StyledSegment]]:
        """Hard-break segments that exceed max_width into chunks."""
        result: List[List[StyledSegment]] = []
        current: List[StyledSegment] = []
        current_width = 0

        for seg in segments:
            # Break segment text character by character if needed
            char_widths = []
            for ch in seg.text:
                w = wcswidth(ch)
                if w < 0:
                    w = 1
                char_widths.append(w)

            remaining_text = seg.text
            while remaining_text:
                if not current or current_width + char_widths[0] <= max_width:
                    # Fits
                    ch = remaining_text[0]
                    current.append(StyledSegment(ch, seg.fg, seg.bg, seg.bold, seg.reverse))
                    current_width += char_widths[0]
                    remaining_text = remaining_text[1:]
                    char_widths = char_widths[1:]
                else:
                    # Flush current
                    result.append(list(current))
                    current = []
                    current_width = 0

        if current:
            result.append(current)
        elif not result:
            result.append([])

        return result

    # --- Rendering ---

    def render(self, buffer: Buffer):
        lines = self._wrapped_lines
        default_fg = self.fg if self.fg is not None else theme.DEFAULT
        default_bg = self.bg if self.bg is not None else theme.get_bg()

        for y, line in enumerate(lines):
            if y >= self.height:
                break

            # Special case: HR sentinel
            if len(line) == 1 and line[0].text == "hr":
                hr_style = _get_style("hr")
                hr_char = "\u2500"  # box-drawing horizontal
                style_fg = hr_style["fg"] if hr_style["fg"] else (default_fg.r, default_fg.g, default_fg.b) if isinstance(default_fg, RGB) else None
                buffer.write_str(self.x, self.y + y, hr_char * self.width, fg=style_fg, max_width=self.width)
                continue

            curr_x = 0
            for seg in line:
                if curr_x >= self.width:
                    break
                seg_fg = seg.fg if seg.fg is not None else ((default_fg.r, default_fg.g, default_fg.b) if isinstance(default_fg, RGB) else None)
                seg_bg = seg.bg if seg.bg is not None else ((default_bg.r, default_bg.g, default_bg.b) if default_bg and isinstance(default_bg, RGB) else None)
                buffer.write_str(
                    self.x + curr_x,
                    self.y + y,
                    seg.text,
                    fg=seg_fg,
                    bg=seg_bg,
                    bold=seg.bold,
                    reverse=seg.reverse,
                    max_width=self.width - curr_x,
                )
                curr_x += seg.display_width
