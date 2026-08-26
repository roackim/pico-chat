"""Conversation-owned state and execution resources for the chat UI."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from pico_chat.ui.chat_history_panel import ChatHistoryPanel
from pico_chat.ui.chat_message import Message
from pico_chat.ui.tui.msg_types import SysMsg


def _show_role_change(panel: ChatHistoryPanel, previous_name: str, role_name: str) -> None:
    if previous_name == role_name:
        return

    text = f"Role changed: {previous_name} -> {role_name}"
    messages = getattr(panel, "messages", [])
    last = messages[-1] if messages else None
    if getattr(last, "_is_role_change_notice", False):
        replacement = panel.new_message(text, msg_type=SysMsg(), title="role")
        replacement._is_role_change_notice = True
        panel.replace_message(last, replacement)
        return

    notice = panel.add_message(text, msg_type=SysMsg(), title="role")
    if notice is not None:
        notice._is_role_change_notice = True


class ConversationRuntime:
    """Own one conversation's agent, UI model, and asynchronous work."""

    def __init__(
        self,
        agent: Any = None,
        name: str = "chat",
        kind: str = "chat",
        agent_factory: Optional[Callable[[], Any]] = None,
    ):
        self.name = name
        self.kind = kind
        self.agent = agent
        self._agent_factory = agent_factory
        self.chat_history_panel = ChatHistoryPanel()
        self.message_queue: asyncio.Queue[tuple[str, Message]] = asyncio.Queue()
        self.current_generation_task: Optional[asyncio.Task] = None
        self.worker_task: Optional[asyncio.Task] = None
        self.active_tool_messages: dict[str, Message] = {}
        self.pending_permission_prompt: Optional[str] = None
        self.active_user_input: Optional[str] = None
        self.active_user_msg: Optional[Message] = None
        self.paused_user_input: Optional[str] = None
        self.paused_user_msg: Optional[Message] = None
        self.requeue_after_cancel = False

    @property
    def messages(self) -> list[Message]:
        return self.chat_history_panel.messages

    @property
    def harness_history(self) -> list:
        return getattr(self.ensure_agent(), "history", [])

    @harness_history.setter
    def harness_history(self, value: list) -> None:
        self.ensure_agent().history = list(value)

    def ensure_agent(self) -> Any:
        """Create the agent lazily for tabs opened after the initial tab."""
        if self.agent is None:
            if self._agent_factory is None:
                raise RuntimeError("Conversation runtime has no agent factory")
            self.agent = self._agent_factory()
        return self.agent

    @property
    def is_generating(self) -> bool:
        return (
            self.current_generation_task is not None
            and not self.current_generation_task.done()
        )

    def enqueue(self, text: str, message: Message) -> None:
        self.message_queue.put_nowait((text, message))

    def stop_generation(self) -> bool:
        if self.is_generating:
            self.current_generation_task.cancel()
            return True
        return False

    def switch_role(self, role: Any) -> Any:
        """Apply a role when no response is currently being generated."""
        if self.is_generating:
            raise RuntimeError("Role changes apply after the current response finishes.")
        agent = self.ensure_agent()
        previous_name = getattr(getattr(agent, "role", None), "name", "default")
        agent.set_role(role)
        _show_role_change(self.chat_history_panel, previous_name, role.name)
        return agent.role
