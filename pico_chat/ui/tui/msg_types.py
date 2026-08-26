"""Message type definitions for Pico-Chat."""

from typing import Optional, List
from enum import Enum

class MsgAction(Enum):
    """Available actions for messages."""
    DELETE = ("d", "delete")
    COPY = ("c", "copy")
    RETRY = ("r", "retry")
    STOP = ("s", "stop")
    ALLOW = ("a", "allow")
    DENY = ("x", "deny")
    OUTPUT = ("o", "output")
    STEER = ("t", "steer")   # inject queued message as thinking prefill
    PAUSE = ("p", "pause")   # cancel generation + capture thinking so far
    RESUME = ("u", "resume") # re-send with captured thinking prefill
    
    def __init__(self, key: str, label: str):
        self.key = key
        self.label = label
    
    def format(self) -> str:
        """Format action as [key] label."""
        return f"[{self.key}] {self.label}"

class MsgType:
    """Base class for message types."""
    name: str = "default"
    title: str = ""
    frame_color: str = "DEFAULT"
    content_color: Optional[str] = None
    actions: List[MsgAction] = []
    # Thread-mode gutter symbol and color (None = use frame_color).
    gutter: str = "▸"
    gutter_color: Optional[str] = None

class UserMsg(MsgType):
    name = "user"
    title = "user"
    actions = [MsgAction.COPY, MsgAction.DELETE, MsgAction.STEER]
    frame_color = "USER"
    gutter = "▸"

class PicoMsg(MsgType):
    name = "pico"
    title = "pico"
    actions = [MsgAction.COPY, MsgAction.RETRY, MsgAction.DELETE, MsgAction.STOP, MsgAction.PAUSE, MsgAction.RESUME]
    frame_color = "PICO"
    gutter = "▸"

class SysMsg(MsgType):
    name = "system"
    title = "system"
    frame_color = "MUTED"
    content_color = "MUTED"
    actions = [MsgAction.COPY, MsgAction.DELETE]
    gutter = "·"

class SysMsgError(SysMsg):
    name = "error"
    title = "error"
    frame_color = "ERROR"
    content_color = "ERROR"
    actions = [MsgAction.COPY, MsgAction.DELETE]
    gutter = "✗"

class SysMsgWarning(SysMsg):
    name = "warning"
    title = "warning"
    frame_color = "WARNING"
    content_color = "WARNING"
    gutter = "!"

class ThinkingMsg(PicoMsg):
    name = "thinking"
    title = "thinking"
    frame_color = "MUTED"
    content_color = "MUTED"
    actions = [MsgAction.COPY, MsgAction.RETRY, MsgAction.DELETE, MsgAction.STOP, MsgAction.PAUSE, MsgAction.RESUME]
    gutter = "…"

class ToolCallMsg(MsgType):
    name = "tool"
    title = "tool"
    frame_color = "WARNING"
    content_color = None
    actions = [MsgAction.OUTPUT, MsgAction.COPY, MsgAction.DELETE]
    gutter = "⚙"


class ToolDraftMsg(MsgType):
    name = "tool_draft"
    title = "tool"
    frame_color = "MUTED"
    content_color = "MUTED"
    actions = []
    gutter = "⚙"

class AskPermissionMsg(MsgType):
    name = "permission"
    title = "permission"
    frame_color = "PERMISSION"
    content_color = None
    actions = [MsgAction.ALLOW, MsgAction.DENY, MsgAction.OUTPUT, MsgAction.COPY]
    gutter = "?"
