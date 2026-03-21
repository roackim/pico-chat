"""Message type definitions for Pico-Chat."""

from typing import Optional

class MsgType:
    """Base class for message types."""
    name: str = "default"
    title: str = ""
    frame_color: str = "DEFAULT"
    content_color: Optional[str] = None

class UserMsg(MsgType):
    name = "user"
    title = "user"
    frame_color = "USER"

class PicoMsg(MsgType):
    name = "pico"
    title = "pico"
    frame_color = "PICO"

class SysMsg(MsgType):
    name = "system"
    title = "system"
    frame_color = "MUTED"
    content_color = "MUTED"

class SysMsgError(SysMsg):
    name = "error"
    title = "error"
    frame_color = "ERROR"
    content_color = "ERROR"

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
