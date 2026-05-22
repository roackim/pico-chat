"""Stream chunks for harness-to-UI communication."""

from dataclasses import dataclass
from typing import Optional, Literal
from enum import Enum


class ToolStatus(Enum):
    """Explicit tool execution states."""
    PERMISSION_REQUESTED = "permission_requested"  # Asking for permission
    APPROVED = "approved"                          # Permission granted (auto or manual)
    DENIED = "denied"                              # Permission denied (auto or manual)
    EXECUTING = "executing"                        # Tool is running
    COMPLETED = "completed"                        # Tool finished successfully
    ERROR = "error"                                # Tool execution failed

    @property
    def is_terminal(self) -> bool:
        """Whether this status ends the tool execution."""
        return self in (ToolStatus.DENIED, ToolStatus.COMPLETED, ToolStatus.ERROR)


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
class ToolStatusChange(Chunk):
    """Tool call status update - emitted for ALL state transitions."""
    tool_call_id: str
    tool_name: str
    tool_args: str  # JSON string
    status: ToolStatus
    
    # Optional fields based on status
    permission_prompt: Optional[str] = None      # When PERMISSION_REQUESTED
    auto_decision: Optional[bool] = None         # True if auto-approved/denied
    result: Optional[str] = None                 # When COMPLETED
    error: Optional[str] = None                  # When ERROR
    denial_reason: Optional[str] = None          # When DENIED


@dataclass
class ToolDraft(Chunk):
    """Streaming draft update for a tool call being constructed by the model."""
    tool_call_id: str
    tool_name: str
    tool_args: str


@dataclass
class GenerationMetrics(Chunk):
    """Live generation metrics for performance monitoring."""
    tokens: int
    tokens_per_second: float
    ttft_ms: Optional[float] = None  # Time to first token
    duration_ms: Optional[float] = None  # Total duration


@dataclass
class SubagentsWaiting(Chunk):
    """Emitted when the harness is auto-waiting for background subagents to finish."""
    count: int


@dataclass
class SubagentResult(Chunk):
    """Emitted when a background subagent completes (one per subagent)."""
    index: int
    task: str
    result: str


@dataclass
class SubagentsDone(Chunk):
    """Emitted when all background subagents have finished or been aborted."""
    completed: int
    aborted: int
