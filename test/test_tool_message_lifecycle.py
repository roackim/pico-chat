"""Tests for tool-message lifecycle status glyphs.

Verifies the "no ✓ until finished" rule and that a loading spinner is shown
while a tool command is running.
"""

from pico_chat.ui.chat_message import Message
from pico_chat.ui.tui.msg_types import ToolCallMsg
from pico_chat.ui.tui.colors import theme


class _StubRunTool:
    """Minimal RunTool-like wrapper exposing cancel_active_run()."""
    def __init__(self, toolset):
        self.toolset = toolset

    def cancel_active_run(self) -> bool:
        return self.toolset.cancel_active_run()


def _tool(msg_type=None, status=None, finalized=False):
    msg = Message("", msg_type=msg_type or ToolCallMsg(), max_width=40)
    msg.tool_name = "run"
    msg.tool_args = '{"command": "ls"}'
    if status is not None:
        msg.tool_status = status
    if finalized:
        msg.finalize()
    return msg


def test_spinner_while_not_finalized():
    msg = _tool(status="approved | executing", finalized=False)
    glyph, color = msg.status_glyph()
    assert glyph in ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    assert color == theme.MUTED


def test_no_done_mark_while_running():
    """A running command never reports a ✓ glyph."""
    msg = _tool(status="approved | executing", finalized=False)
    glyph, _ = msg.status_glyph()
    assert glyph not in ("✓", "✗")


def test_check_mark_only_after_finalized_completed():
    msg = _tool(status="approved | completed", finalized=True)
    glyph, color = msg.status_glyph()
    assert glyph == "✓"
    assert color == theme.SUCCESS


def test_error_mark_after_finalized():
    msg = _tool(status="error", finalized=True)
    glyph, color = msg.status_glyph()
    assert glyph == "✗"
    assert color == theme.ERROR


def test_denied_mark_after_finalized():
    msg = _tool(status="denied", finalized=True)
    glyph, color = msg.status_glyph()
    assert glyph == "✗"
    assert color == theme.ERROR


def test_autoapproved_not_terminal():
    """auto-approved is a pending permission state, not a done state."""
    msg = _tool(status="auto-approved", finalized=False)
    glyph, _ = msg.status_glyph()
    assert glyph not in ("✓", "✗")


def test_advance_spinner_rebuilds_tool_display():
    """Spinner animates because advance_spinner rebuilds the tool display."""
    msg = _tool(status="approved | executing", finalized=False)
    before = msg.get_formatted()
    msg.advance_spinner()
    after = msg.get_formatted()
    assert before != after


def test_stop_action_shown_while_running_hidden_when_finalized():
    """STOP is offered only while the tool command is still running."""
    from pico_chat.ui.tui.msg_types import MsgAction

    running = _tool(status="approved | executing", finalized=False)
    done = _tool(status="approved | completed", finalized=True)

    running_actions = [a for a in running.get_active_actions()]
    done_actions = [a for a in done.get_active_actions()]

    assert MsgAction.STOP in running_actions
    assert MsgAction.STOP not in done_actions


def test_harness_stop_tool_kills_run(tmp_path):
    """Harness.stop_tool() terminates the active command."""
    import asyncio
    from pico_chat.harness.harness import Harness
    from pico_chat.harness.tools import MinimalToolset, ShellTool
    from pico_chat.harness.tool_permissions import (
        ToolPermissionsProfile, FilePermissions, RunPermissions,
    )

    perms = ToolPermissionsProfile(
        name="test",
        read=FilePermissions("allow", "allow"),
        write=FilePermissions("allow", "allow"),
        patch=FilePermissions("allow", "allow"),
        run=RunPermissions(allow=set(), ask=set(), deny=set(),
                           others="allow", chain_policy="ask", use_container=False),
        search="allow",
    )

    h = Harness.__new__(Harness)
    ts = MinimalToolset(tmp_path, permissions=perms)
    run_tool = _StubRunTool(ts)
    h.tools_map = {"run_command": run_tool, "run": run_tool}

    async def scenario():
        task = asyncio.create_task(ts.run_async("sleep 30"))
        await asyncio.sleep(0.2)
        assert h.stop_tool() is True
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            raise AssertionError("stop_tool did not terminate the command")

    asyncio.run(scenario())


def test_run_tool_schema_name_is_run():
    """The LLM-facing tool name is 'run' (not 'run_command')."""
    from pico_chat.harness.tool_wrappers import RunTool
    from pico_chat.harness.tools import MinimalToolset
    import tempfile, os

    tmp = tempfile.mkdtemp()
    tool = RunTool(MinimalToolset(tmp, permissions=None))
    assert tool.get_schema()["function"]["name"] == "run"


def test_dynamic_gutter_contextual():
    """Gutter is ? for ask, spinner while running, ✓ when completed."""
    from pico_chat.ui.tui.msg_types import AskPermissionMsg, ToolCallMsg

    ask = Message("", msg_type=AskPermissionMsg(), max_width=40)
    ask.tool_name = "run"
    assert ask.dynamic_gutter()[0] == "?"

    running = _tool(status="approved | executing", finalized=False)
    glyph, _ = running.dynamic_gutter()
    assert glyph in ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    done = _tool(status="approved | completed", finalized=True)
    assert done.dynamic_gutter()[0] == "✓"