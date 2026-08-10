"""
Thinking-tag streaming parser.

Extracts the inline thinking-tag state machine from `Harness._stream_llm_response`
into a standalone, testable class.  Handles two input paths:

- ``reasoning_content`` API field (DeepSeek/R1 style) — yielded directly as
  ``Thinking`` chunks, no tag parsing needed.
- Inline content with ``<thinking>``/``</thinking>`` or ``<think>``/``</think>``
  tags — a state machine that splits content into ``Content`` and ``Thinking``
  segments, buffering partial tags across chunk boundaries.

Also encapsulates the periodic ``GenerationMetrics`` emission so the 6×
duplicated metrics-yield block in the original method collapses into a single
helper call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from pico_chat.harness import chunks


# Supported thinking tag delimiters (open, close)
THINKING_TAGS: List[Tuple[str, str]] = [
    ("<think>", "</think>"),
    ("<thinking>", "</thinking>"),
]

# Pre-computed max open-tag length for partial-tag buffering
_MAX_TAG_LEN = max(len(tag[0]) for tag in THINKING_TAGS)


# ---------------------------------------------------------------------------
# Parsed chunk types
# ---------------------------------------------------------------------------

@dataclass
class ParsedContent:
    """A piece of content parsed from the stream — either thinking or regular."""
    text: str
    is_thinking: bool


class ThinkingTagParser:
    """Stateful parser that splits a content stream into thinking/content segments.

    Usage::

        parser = ThinkingTagParser()
        for text_chunk in stream:
            for segment in parser.feed(text_chunk):
                if segment.is_thinking:
                    yield chunks.Thinking(content=segment.text)
                else:
                    yield chunks.Content(content=segment.text)
        for segment in parser.flush():
            ...
    """

    def __init__(self):
        self._buffer: str = ""
        self._in_thinking_block: bool = False
        self._current_open_tag: Optional[str] = None
        # Persists after the block closes — None means reasoning_content path.
        self.detected_open_tag: Optional[str] = None

        # Accumulators
        self.full_content: str = ""
        self.full_reasoning: str = ""

    def feed(self, text: str) -> List[ParsedContent]:
        """Feed a chunk of text and return parsed segments.

        May return an empty list if the buffer is holding back a partial tag.
        """
        self._buffer += text
        results: List[ParsedContent] = []

        while self._buffer:
            if not self._in_thinking_block:
                # Look for the earliest opening tag
                earliest_pos = len(self._buffer)
                found_tag: Optional[Tuple[str, str]] = None

                for open_tag, close_tag in THINKING_TAGS:
                    pos = self._buffer.find(open_tag)
                    if pos != -1 and pos < earliest_pos:
                        earliest_pos = pos
                        found_tag = (open_tag, close_tag)

                if found_tag is not None:
                    open_tag, close_tag = found_tag
                    # Yield content before the tag
                    if earliest_pos > 0:
                        before = self._buffer[:earliest_pos]
                        self.full_content += before
                        results.append(ParsedContent(text=before, is_thinking=False))
                    # Enter thinking block
                    self._in_thinking_block = True
                    self._current_open_tag = open_tag
                    self.detected_open_tag = open_tag
                    self._buffer = self._buffer[earliest_pos + len(open_tag):]
                else:
                    # No opening tag — keep potential partial tag at the end
                    if len(self._buffer) > _MAX_TAG_LEN:
                        safe = self._buffer[:-_MAX_TAG_LEN]
                        self.full_content += safe
                        results.append(ParsedContent(text=safe, is_thinking=False))
                        self._buffer = self._buffer[-_MAX_TAG_LEN:]
                    break  # Wait for more content
            else:
                # Inside a thinking block — look for the matching close tag
                close_tag = next(
                    close for open_, close in THINKING_TAGS
                    if open_ == self._current_open_tag
                )
                close_pos = self._buffer.find(close_tag)

                if close_pos != -1:
                    # Found closing tag
                    thinking_text = self._buffer[:close_pos]
                    if thinking_text:
                        self.full_reasoning += thinking_text
                        results.append(ParsedContent(text=thinking_text, is_thinking=True))
                    # Exit thinking block
                    self._in_thinking_block = False
                    self._current_open_tag = None
                    self._buffer = self._buffer[close_pos + len(close_tag):]
                else:
                    # No closing tag yet — keep potential partial at the end
                    if len(self._buffer) > len(close_tag):
                        safe = self._buffer[:-len(close_tag)]
                        if safe:
                            self.full_reasoning += safe
                            results.append(ParsedContent(text=safe, is_thinking=True))
                        self._buffer = self._buffer[-len(close_tag):]
                    break  # Wait for more content

        return results

    def flush(self) -> List[ParsedContent]:
        """Flush any remaining buffer at end of stream.

        An unclosed thinking block yields its remaining content as thinking
        (the model may have been cut off).
        """
        if not self._buffer:
            return []
        results: List[ParsedContent] = []
        if self._in_thinking_block:
            self.full_reasoning += self._buffer
            results.append(ParsedContent(text=self._buffer, is_thinking=True))
        else:
            self.full_content += self._buffer
            results.append(ParsedContent(text=self._buffer, is_thinking=False))
        self._buffer = ""
        return results


# ---------------------------------------------------------------------------
# Metrics helper
# ---------------------------------------------------------------------------

@dataclass
class MetricsState:
    """Tracks generation metrics for periodic emission."""
    generation_start_time: Optional[float] = None
    total_tokens: int = 0
    last_update: float = 0.0
    ttft_ms: Optional[float] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_usage_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None

    def add_tokens(self, text: str, estimate_fn) -> int:
        """Estimate and accumulate tokens for a text chunk. Returns the count."""
        count = estimate_fn(text)
        self.total_tokens += count
        return count

    def ensure_started(self):
        """Mark the generation start time on first content."""
        if self.generation_start_time is None:
            self.generation_start_time = time.perf_counter()

    def set_usage(self, usage):
        """Replace estimates with authoritative provider usage when available."""
        self.prompt_tokens = usage.prompt_tokens
        self.completion_tokens = usage.completion_tokens
        self.total_usage_tokens = usage.total_tokens
        self.reasoning_tokens = usage.reasoning_tokens
        if usage.completion_tokens is not None:
            self.total_tokens = usage.completion_tokens

    def maybe_metrics(self, interval: float) -> Optional[chunks.GenerationMetrics]:
        """Return a GenerationMetrics chunk if enough time has elapsed, else None."""
        if self.generation_start_time is None:
            return None
        current = time.perf_counter()
        if current - self.last_update >= interval:
            duration = current - self.generation_start_time
            tps = self.total_tokens / duration if duration > 0 else 0
            self.last_update = current
            return chunks.GenerationMetrics(
                tokens=self.total_tokens,
                tokens_per_second=tps,
                ttft_ms=self.ttft_ms,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_tokens=self.total_usage_tokens,
                reasoning_tokens=self.reasoning_tokens,
                estimated=self.completion_tokens is None,
            )
        return None

    def final_metrics(self) -> Optional[chunks.GenerationMetrics]:
        """Return the final GenerationMetrics chunk with duration_ms, or None."""
        if self.generation_start_time is None:
            return None
        duration = time.perf_counter() - self.generation_start_time
        tps = self.total_tokens / duration if duration > 0 else 0
        return chunks.GenerationMetrics(
            tokens=self.total_tokens,
            tokens_per_second=tps,
            ttft_ms=self.ttft_ms,
            duration_ms=duration * 1000,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_usage_tokens,
            reasoning_tokens=self.reasoning_tokens,
            estimated=self.completion_tokens is None,
        )
