import pytest

from pico_chat.harness.roles import Role
from pico_chat.ui.conversation_runtime import ConversationRuntime


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


def test_switch_role_rejects_active_generation():
    agent = FakeAgent()
    runtime = ConversationRuntime(agent=agent)
    runtime.current_generation_task = ActiveTask()

    with pytest.raises(RuntimeError, match="current response finishes"):
        runtime.switch_role(Role("reviewer"))

    assert agent.role.name == "initial"
