"""
Test suite for the subagent system.

Covers: depth-limit guard, timeout, context-limit, scaffolder permission
profile, background queuing, wait_for_subagents, and harness-level
abort_subagents.

All tests use mocked Harness.chat so no real LLM backend is required.
"""

import asyncio
import contextlib
from pathlib import Path
from unittest.mock import patch

import pytest

from pico_chat.harness.tool_wrappers import SubagentTool, WaitForSubagentsTool
from pico_chat.harness.tool_permissions import scaffolder
import pico_chat.pico_cfg as pico_cfg_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(tmp_path: Path, depth: int = 0, pending: list | None = None) -> SubagentTool:
    if pending is None:
        pending = []
    return SubagentTool(workspace_path=tmp_path, depth=depth, pending_subagents=pending)


@contextlib.contextmanager
def _cfg(max_depth: int = 2, timeout: float = 10, max_context=None):
    """Temporarily override subagent config values."""
    orig = (
        pico_cfg_module.config.subagent_max_depth,
        pico_cfg_module.config.subagent_timeout,
        pico_cfg_module.config.subagent_max_context,
    )
    try:
        pico_cfg_module.config.subagent_max_depth = max_depth
        pico_cfg_module.config.subagent_timeout = timeout
        pico_cfg_module.config.subagent_max_context = max_context
        yield
    finally:
        (
            pico_cfg_module.config.subagent_max_depth,
            pico_cfg_module.config.subagent_timeout,
            pico_cfg_module.config.subagent_max_context,
        ) = orig


# ---------------------------------------------------------------------------
# Scaffolder permission profile
# ---------------------------------------------------------------------------

class TestScaffolderProfile:
    """The scaffolder profile must be read-only inside the repo only."""

    def test_read_inside_allowed(self):
        assert scaffolder.get_read_permission(True) == "allow"

    def test_read_outside_denied(self):
        assert scaffolder.get_read_permission(False) == "deny"

    def test_write_denied_everywhere(self):
        assert scaffolder.get_write_permission(True) == "deny"
        assert scaffolder.get_write_permission(False) == "deny"

    def test_patch_denied_everywhere(self):
        assert scaffolder.get_patch_permission(True) == "deny"
        assert scaffolder.get_patch_permission(False) == "deny"

    def test_run_others_denied(self):
        assert scaffolder.get_run_permission().others == "deny"

    def test_run_allow_list_empty(self):
        assert len(scaffolder.get_run_permission().allow) == 0

    def test_profile_name(self):
        assert scaffolder.name == "scaffolder"


# ---------------------------------------------------------------------------
# Depth-limit guard
# ---------------------------------------------------------------------------

class TestSubagentDepthLimit:
    """SubagentTool must refuse to spawn when depth >= subagent_max_depth."""

    def test_depth_at_limit_returns_message(self, tmp_path):
        with _cfg(max_depth=1):
            tool = _make_tool(tmp_path, depth=1)
            result = asyncio.run(tool.execute(task="explore repo"))
        assert "depth limit" in result.lower()

    def test_depth_above_limit_returns_message(self, tmp_path):
        with _cfg(max_depth=2):
            tool = _make_tool(tmp_path, depth=3)
            result = asyncio.run(tool.execute(task="explore repo"))
        assert "depth limit" in result.lower()

    def test_depth_below_limit_proceeds(self, tmp_path):
        """At depth 0 with max_depth=1 the tool must NOT be blocked."""
        async def _chat(task):
            from pico_chat.harness import chunks
            yield chunks.MessageStart(message_id="test", role="assistant")
            yield chunks.Content(content="findings")

        with _cfg(max_depth=1, timeout=5):
            tool = _make_tool(tmp_path, depth=0)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _chat
                result = asyncio.run(tool.execute(task="explore repo"))

        assert "depth limit" not in result.lower()
        assert "findings" in result


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------

class TestSubagentTimeout:
    """Subagent must be aborted and return a timeout message when it exceeds the limit."""

    def test_timeout_returns_timeout_message(self, tmp_path):
        async def _slow(task):
            await asyncio.sleep(9999)
            yield  # never reached

        with _cfg(max_depth=2, timeout=0.05):
            tool = _make_tool(tmp_path, depth=0)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _slow
                result = asyncio.run(tool.execute(task="long task"))

        assert "timed out" in result.lower()

    def test_timeout_message_includes_duration(self, tmp_path):
        async def _slow(task):
            await asyncio.sleep(9999)
            yield

        with _cfg(max_depth=2, timeout=0.05):
            tool = _make_tool(tmp_path, depth=0)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _slow
                result = asyncio.run(tool.execute(task="slow task"))

        assert "0.05" in result


# ---------------------------------------------------------------------------
# Context-limit enforcement
# ---------------------------------------------------------------------------

class TestSubagentContextLimit:
    """Subagent must abort when cumulative token count exceeds subagent_max_context."""

    def test_context_limit_returns_abort_message(self, tmp_path):
        async def _heavy(task):
            from pico_chat.harness import chunks
            yield chunks.MessageStart(message_id="test", role="assistant")
            yield chunks.Content(content="x")
            yield chunks.GenerationMetrics(tokens=100, tokens_per_second=50.0, ttft_ms=10.0)

        with _cfg(max_depth=2, timeout=10, max_context=5):
            tool = _make_tool(tmp_path, depth=0)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _heavy
                result = asyncio.run(tool.execute(task="heavy task"))

        assert "context limit" in result.lower() or "aborted" in result.lower()

    def test_no_context_limit_when_none(self, tmp_path):
        """When subagent_max_context is None, large token counts must not abort."""
        async def _big(task):
            from pico_chat.harness import chunks
            yield chunks.MessageStart(message_id="test", role="assistant")
            yield chunks.Content(content="large output")
            yield chunks.GenerationMetrics(tokens=999999, tokens_per_second=50.0, ttft_ms=10.0)

        with _cfg(max_depth=2, timeout=10, max_context=None):
            tool = _make_tool(tmp_path, depth=0)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _big
                result = asyncio.run(tool.execute(task="big task"))

        assert "context limit" not in result.lower()
        assert "large output" in result


# ---------------------------------------------------------------------------
# Foreground execution
# ---------------------------------------------------------------------------

class TestSubagentForeground:
    """Foreground subagents (background=False, default) return the full response text."""

    def test_foreground_returns_content(self, tmp_path):
        async def _chat(task):
            from pico_chat.harness import chunks
            yield chunks.MessageStart(message_id="test", role="assistant")
            yield chunks.Content(content="hello ")
            yield chunks.Content(content="world")

        with _cfg(max_depth=2, timeout=10):
            tool = _make_tool(tmp_path, depth=0)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _chat
                result = asyncio.run(tool.execute(task="say hello"))

        assert result == "hello world"

    def test_empty_response_fallback(self, tmp_path):
        async def _empty(task):
            return
            yield  # makes it a generator

        with _cfg(max_depth=2, timeout=10):
            tool = _make_tool(tmp_path, depth=0)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _empty
                result = asyncio.run(tool.execute(task="silent task"))

        assert "no response" in result.lower()


# ---------------------------------------------------------------------------
# Background queuing
# ---------------------------------------------------------------------------

class TestSubagentBackground:
    """background=True should queue the task and return immediately."""

    def test_background_returns_queued_message(self, tmp_path):
        async def _chat(task):
            from pico_chat.harness import chunks
            yield chunks.Content(content="result")

        async def _run():
            pending = []
            tool = _make_tool(tmp_path, depth=0, pending=pending)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _chat
                result = await tool.execute(task="background task", background=True)
            return result, pending

        with _cfg(max_depth=2, timeout=10):
            result, pending = asyncio.run(_run())

        assert "queued" in result.lower() or "background" in result.lower()
        assert len(pending) == 1

    def test_background_index_increments(self, tmp_path):
        """Each background subagent gets the next sequential index."""
        async def _chat(task):
            from pico_chat.harness import chunks
            yield chunks.Content(content="done")

        async def _run():
            pending = []
            tool = _make_tool(tmp_path, depth=0, pending=pending)
            with patch("pico_chat.harness.harness.Harness") as MockHarness:
                MockHarness.return_value.chat = _chat
                await tool.execute(task="task A", background=True)
                await tool.execute(task="task B", background=True)
            return pending

        with _cfg(max_depth=2, timeout=10):
            pending = asyncio.run(_run())

        assert pending[0]["index"] == 0
        assert pending[1]["index"] == 1


# ---------------------------------------------------------------------------
# WaitForSubagentsTool
# ---------------------------------------------------------------------------

class TestWaitForSubagents:
    """WaitForSubagentsTool collects results from pending background subagents."""

    def test_no_pending_returns_message(self):
        async def _run():
            return await WaitForSubagentsTool(pending_subagents=[]).execute()

        result = asyncio.run(_run())
        assert "no pending" in result.lower()

    def test_collects_results(self):
        async def _run():
            async def _a(): return "result A"
            async def _b(): return "result B"
            pending = [
                {"index": 0, "task": "task A", "future": asyncio.create_task(_a())},
                {"index": 1, "task": "task B", "future": asyncio.create_task(_b())},
            ]
            return await WaitForSubagentsTool(pending_subagents=pending).execute()

        result = asyncio.run(_run())
        assert "result A" in result
        assert "result B" in result

    def test_clears_pending_after_wait(self):
        async def _run():
            async def _done(): return "done"
            pending = [{"index": 0, "task": "t", "future": asyncio.create_task(_done())}]
            await WaitForSubagentsTool(pending_subagents=pending).execute()
            return pending

        pending = asyncio.run(_run())
        assert len(pending) == 0

    def test_exception_in_subagent_reported(self):
        async def _run():
            async def _fail():
                raise RuntimeError("boom")
            pending = [{"index": 0, "task": "bad task", "future": asyncio.create_task(_fail())}]
            return await WaitForSubagentsTool(pending_subagents=pending).execute()

        result = asyncio.run(_run())
        assert "error" in result.lower() or "boom" in result.lower()


# ---------------------------------------------------------------------------
# Harness-level subagent integration
# ---------------------------------------------------------------------------

class TestHarnessSubagentIntegration:
    """Test that Harness correctly sets up subagent context and abort mechanism."""

    def test_subagent_uses_scaffolder_permissions(self, tmp_path):
        """A Harness at depth > 0 should use the scaffolder profile."""
        from pico_chat.harness.harness import Harness
        from pico_chat.harness import tool_permissions

        with patch("pico_chat.harness.harness.create_server"):
            h = Harness(workspace_path=str(tmp_path), depth=1)

        assert h._tool_permissions is tool_permissions.scaffolder

    def test_subagent_role_isolated_from_parent_role(self, tmp_path):
        """A child harness keeps scaffolder policy even when a parent role is supplied."""
        from pico_chat.harness.harness import Harness
        from pico_chat.harness import tool_permissions
        from pico_chat.harness.roles import Role

        parent_role = Role.from_permission_profile(tool_permissions.permissive)
        with patch("pico_chat.harness.harness.create_server"):
            h = Harness(workspace_path=str(tmp_path), depth=1, role=parent_role)

        assert h.role.name == "scaffolder"
        assert h._tool_permissions is tool_permissions.scaffolder

    def test_root_harness_uses_global_permissions(self, tmp_path):
        """A Harness at depth 0 should use None (global permissions)."""
        from pico_chat.harness.harness import Harness

        with patch("pico_chat.harness.harness.create_server"):
            h = Harness(workspace_path=str(tmp_path), depth=0)

        assert h._tool_permissions is None

    def test_abort_subagents_sets_event(self, tmp_path):
        from pico_chat.harness.harness import Harness

        with patch("pico_chat.harness.harness.create_server"):
            h = Harness(workspace_path=str(tmp_path), depth=0)

        assert not h._abort_subagents_event.is_set()
        h.abort_subagents()
        assert h._abort_subagents_event.is_set()

    def test_subagent_tools_require_approval(self, tmp_path):
        """Delegation must honor the main harness permission gate."""
        from pico_chat.harness.harness import Harness

        with patch("pico_chat.harness.harness.create_server"):
            h = Harness(workspace_path=str(tmp_path), depth=0)

        assert h._check_tool_permission("subagent", {}) == "ask"
        assert h._check_tool_permission("wait_for_subagents", {}) == "ask"

    def test_subagent_write_denied_by_scaffolder(self, tmp_path):
        """A depth>0 Harness should deny write requests via the scaffolder profile."""
        from pico_chat.harness.harness import Harness

        with patch("pico_chat.harness.harness.create_server"):
            h = Harness(workspace_path=str(tmp_path), depth=1)

        result = h._check_tool_permission("write", {"path": str(tmp_path / "file.txt")})
        assert result == "deny"

    def test_subagent_run_denied_by_scaffolder(self, tmp_path):
        """A depth>0 Harness should deny all run requests via the scaffolder profile."""
        from pico_chat.harness.harness import Harness

        with patch("pico_chat.harness.harness.create_server"):
            h = Harness(workspace_path=str(tmp_path), depth=1)

        result = h._check_tool_permission("run", {"command": "ls"})
        assert result == "deny"

    def test_subagent_read_inside_repo_allowed(self, tmp_path):
        """A depth>0 Harness should allow reads inside the workspace."""
        from pico_chat.harness.harness import Harness

        with patch("pico_chat.harness.harness.create_server"):
            h = Harness(workspace_path=str(tmp_path), depth=1)

        inside_file = str(tmp_path / "README.md")
        result = h._check_tool_permission("read", {"path": inside_file})
        assert result == "allow"
