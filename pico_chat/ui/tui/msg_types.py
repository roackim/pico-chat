"""Message type definitions for Pico-Chat."""

from typing import Optional, List
from enum import Enum

class MsgAction(Enum):
    """Available actions for messages."""
    DELETE = ("d", "delete")
    COPY = ("c", "copy")
    EDIT = ("e", "edit")
    RETRY = ("r", "retry")
    STOP = ("s", "stop")
    ALLOW = ("a", "allow")
    DENY = ("x", "deny")
    OUTPUT = ("o", "output")
    
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

class UserMsg(MsgType):
    name = "user"
    title = "user"
    actions = [MsgAction.COPY, MsgAction.EDIT]
    frame_color = "USER"

class PicoMsg(MsgType):
    name = "pico"
    title = "pico"
    actions = [MsgAction.COPY, MsgAction.RETRY, MsgAction.STOP]
    frame_color = "PICO"

class SysMsg(MsgType):
    name = "system"
    title = "system"
    frame_color = "MUTED"
    content_color = "MUTED"
    actions = [MsgAction.COPY, MsgAction.DELETE]

class SysMsgError(SysMsg):
    name = "error"
    title = "error"
    frame_color = "ERROR"
    content_color = "ERROR"
    actions = [MsgAction.COPY, MsgAction.EDIT, MsgAction.DELETE]

class SysMsgWarning(SysMsg):
    name = "warning"
    title = "warning"
    frame_color = "WARNING"
    content_color = "WARNING"

class ThinkingMsg(PicoMsg):
    name = "thinking"
    title = "thinking"
    frame_color = "MUTED"
    content_color = "MUTED"
    actions = [MsgAction.COPY, MsgAction.RETRY, MsgAction.DELETE, MsgAction.STOP]

class ToolCallMsg(MsgType):
    name = "tool"
    title = "tool"
    frame_color = "WARNING"
    content_color = None
    actions = [MsgAction.OUTPUT, MsgAction.COPY, MsgAction.DELETE]


class ToolDraftMsg(MsgType):
    name = "tool_draft"
    title = "tool"
    frame_color = "MUTED"
    content_color = "MUTED"
    actions = []

class AskPermissionMsg(MsgType):
    name = "permission"
    title = "permission"
    frame_color = "WARNING"
    content_color = None
    actions = [MsgAction.ALLOW, MsgAction.DENY, MsgAction.COPY]
