"""Stream chunks for harness-to-UI communication."""

from dataclasses import dataclass
from typing import Optional, Literal


@dataclass
class Chunk:
    """Base class for all stream chunks from harness."""
    pass


@dataclass
class MessageStart(Chunk):
    """Signals the start of a new message with its harness ID."""
    message_id: str
    role: str  # "user" or "assistant"


@dataclass
class Thinking(Chunk):
    """LLM reasoning content (e.g., DeepSeek R1 chain-of-thought)."""
    content: str


@dataclass
class Content(Chunk):
    """Regular response content from LLM."""
    content: str


@dataclass
class ToolStart(Chunk):
    """A tool execution is starting."""
    name: str
    args: str


@dataclass
class ToolComplete(Chunk):
    """A tool execution completed."""
    name: str
    result: str
    status: Literal["ok", "denied", "error"] = "ok"


@dataclass
class ToolWaitInput(Chunk):
    """Tool is waiting for user input."""
    prompt: str


@dataclass
class ToolError(Chunk):
    """A tool execution failed."""
    name: str
    error: str


@dataclass
class GenerationMetrics(Chunk):
    """Live generation metrics for performance monitoring."""
    tokens: int
    tokens_per_second: float
    ttft_ms: Optional[float] = None  # Time to first token
    duration_ms: Optional[float] = None  # Total duration
