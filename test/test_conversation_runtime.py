import pytest

from pico_chat.harness.roles import Role
from pico_chat.ui.conversation_runtime import ConversationRuntime
from pico_chat.ui.tui.msg_types import SysMsg


class FakeAgent:
    def __init__(self):
        self.role = Role("initial")

    def set_role(self, role):
        self.role = role


class ActiveTask:
    def done(self):
        return False

    def cancel(self):
        return True


def test_switch_role_delegates_to_conversation_agent():
    agent = FakeAgent()
    runtime = ConversationRuntime(agent=agent)
    role = Role("reviewer")

    result = runtime.switch_role(role)

    assert result is role
    assert agent.role is role


def test_switch_role_adds_muted_notice_to_conversation():
    runtime = ConversationRuntime(agent=FakeAgent())

    runtime.switch_role(Role("reviewer"))

    assert len(runtime.messages) == 1
    assert runtime.messages[0].base_text == "Role changed: initial -> reviewer"
    assert isinstance(runtime.messages[0].type, SysMsg)


def test_consecutive_role_changes_replace_the_previous_notice():
    runtime = ConversationRuntime(agent=FakeAgent())

    runtime.switch_role(Role("reviewer"))
    runtime.switch_role(Role("researcher"))

    assert len(runtime.messages) == 1
    assert runtime.messages[0].base_text == "Role changed: reviewer -> researcher"


def test_switch_role_rejects_active_generation():
    agent = FakeAgent()
    runtime = ConversationRuntime(agent=agent)
    runtime.current_generation_task = ActiveTask()

    with pytest.raises(RuntimeError, match="current response finishes"):
        runtime.switch_role(Role("reviewer"))

    assert agent.role.name == "initial"
