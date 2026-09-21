"""Regression tests for incremental (append-only) streaming.

Guards the fast path in MarkdownComponent.update(append=True) and the tail
raster in Box/_render_thread_to_subbuffer: the incremental result must be
identical to a full parse/render at every step of a chunked stream.
"""

import pytest

from pico_chat.ui.chat_history_panel import ChatHistoryPanel
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components.markdown import MarkdownComponent
from pico_chat.ui.tui.msg_types import PicoMsg, UserMsg


SAMPLES = [
    "# Title\n\nFirst **bold** para.\n\nSecond `code` para.\n\n- a\n- b\n\n> quote\n\n---\n\nend\n",
    "one long paragraph with no blank lines at all until the very end here",
    "```python\nprint('hi')\n\nprint('blank above')\n```\n\nafter code\n",
    "| a | b |\n|---|---|\n| 1 | 2 |\n\n| c | d |\n|---|---|\n| 3 | 4 |\n\nplain\n",
    "## H\npara one\n\n### H2\n\n- x\n\nfinal **bold** `c` [l](u)\n",
    "intro\n\n```\ncode one\n\ncode two\n```\n\noutro text\n\nmore\n",
    "",
]


def _flatten(comp):
    return [[seg.text for seg in line] for line in comp._wrapped_lines]


@pytest.mark.parametrize("sample", SAMPLES)
@pytest.mark.parametrize("chunk", [1, 2, 5, 13])
def test_incremental_parse_matches_full(sample, chunk):
    inc = MarkdownComponent("")
    inc.set_layout(0, 0, 30, 200)
    cur = ""
    for i in range(0, len(sample), chunk):
        cur += sample[i:i + chunk]
        inc.update(cur, append=True)
        full = MarkdownComponent(cur)
        full.set_layout(0, 0, 30, 200)
        assert _flatten(inc) == _flatten(full)


def _snapshot(buf):
    return [
        [(c.char, c.fg, c.bg, c.bold, c.reverse, c.underline, c.is_wide_char_continuation)
         for c in row]
        for row in buf.cells
    ]


def _fresh(text, width, height):
    panel = ChatHistoryPanel(max_width=width)
    panel.add_message("hello", msg_type=UserMsg()).finalize()
    panel.add_message(text, msg_type=PicoMsg())
    panel.set_layout(0, 0, width, height)
    buf = Buffer(width, height)
    panel.render(buf)
    return buf


@pytest.mark.parametrize("sample", SAMPLES)
@pytest.mark.parametrize("size", [(90, 24), (40, 12)])
def test_incremental_render_matches_full(sample, size):
    width, height = size
    full = sample * 3
    panel = ChatHistoryPanel(max_width=width)
    panel.add_message("hello", msg_type=UserMsg()).finalize()
    msg = panel.add_message("", msg_type=PicoMsg())
    panel.set_layout(0, 0, width, height)
    buf = Buffer(width, height)

    cur = ""
    for i in range(0, len(full), 3):
        cur += full[i:i + 3]
        msg.append(full[i:i + 3])
        panel.render(buf)
        reference = _fresh(cur, width, height)
        assert _snapshot(buf) == _snapshot(reference), f"diverged at {len(cur)} chars"
