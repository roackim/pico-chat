"""Tests for Phase 2: cancel/stop of a running shell command."""

import asyncio
import pytest
from pico_chat.harness.tools import ShellTool, MinimalToolset, ToolError
from pico_chat.harness.tool_permissions import (
    ToolPermissionsProfile, FilePermissions, RunPermissions,
)

def _no_container_permissions():
    """Permissive profile running commands directly (no bubblewrap)."""
    return ToolPermissionsProfile(
        name="test",
        read=FilePermissions("allow", "allow"),
        write=FilePermissions("allow", "allow"),
        patch=FilePermissions("allow", "allow"),
        run=RunPermissions(
            allow=set(), ask=set(), deny=set(), others="allow",
            chain_policy="ask", use_container=False,
        ),
        search="allow",
    )

def asyncio_run(coro):
    return asyncio.run(coro)


def test_run_async_returns_formatted_output(tmp_path):
    tool = ShellTool(tmp_path, permissions=_no_container_permissions())
    out = asyncio_run(tool.run_async("echo hello"))
    assert "hello" in out
    assert "[exit:0]" in out


def test_cancel_active_run_kills_command(tmp_path):
    tool = ShellTool(tmp_path, permissions=_no_container_permissions())

    async def scenario():
        # Launch a long-running command.
        task = asyncio.create_task(tool.run_async("sleep 30"))
        await asyncio.sleep(0.2)  # let the subprocess start
        assert tool._active_proc is not None
        stopped = tool.cancel_active()
        assert stopped is True
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            raise AssertionError("cancelled command did not finish promptly")
        assert task.done()

    asyncio_run(scenario())


def test_run_async_no_active_proc_when_cancelled(tmp_path):
    tool = ShellTool(tmp_path, permissions=_no_container_permissions())

    async def scenario():
        task = asyncio.create_task(tool.run_async("sleep 30"))
        await asyncio.sleep(0.2)
        tool.cancel_active()
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            pass
        assert tool._active_proc is None

    asyncio_run(scenario())


def test_minimal_toolset_run_async_and_cancel(tmp_path):
    ts = MinimalToolset(tmp_path, permissions=_no_container_permissions())
    out = asyncio_run(ts.run_async("echo hi"))
    assert "hi" in out

    async def scenario():
        task = asyncio.create_task(ts.run_async("sleep 30"))
        await asyncio.sleep(0.2)
        assert ts.cancel_active_run() is True
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            raise AssertionError("did not cancel")

    asyncio_run(scenario())


def test_run_async_timeout_cleans_up(tmp_path):
    tool = ShellTool(tmp_path, permissions=_no_container_permissions())
    with pytest.raises(ToolError):
        asyncio_run(tool.run_async("sleep 30", timeout=1))
    assert tool._active_proc is None