"""
Test suite for tool permissions system.

Tests permission enforcement for read/write/patch/run operations
with inside/outside repo granularity and ask/allow/deny states.
"""
import asyncio
import json
import pytest
from pathlib import Path
from pico_chat.harness import chunks
from pico_chat.harness.harness import Harness
from pico_chat.harness.llm_status import AgentState
from pico_chat.harness.tools import MinimalToolset, ToolError
from pico_chat.harness.tool_permissions import (
    ToolPermissionsProfile,
    FilePermissions,
    RunPermissions,
)
import pico_chat.harness.tool_permissions as tool_permissions_module

# Shared test helpers (from conftest)
from conftest import NoopDebugStream, StubReadTool, run_harness_tool_call


def test_permission_profile_round_trip(tmp_path, monkeypatch):
    profile_path = tmp_path / "permission-profiles.toml"
    monkeypatch.setattr(tool_permissions_module, "_PROFILE_PATH", profile_path)
    profile = tool_permissions_module.ToolPermissionsProfile(
        name="custom",
        read=FilePermissions(inside_repo="ask", outside_repo="deny"),
        write=FilePermissions(inside_repo="allow", outside_repo="deny"),
        patch=FilePermissions(inside_repo="allow", outside_repo="deny"),
        search="allow",
        run=RunPermissions(
            allow={"ls"}, ask={"git"}, deny={"sudo"}, others="ask",
            chain_policy="deny", use_container=True, container_network=False,
        ),
    )

    tool_permissions_module.save_profile(profile.name, profile)
    loaded = tool_permissions_module.load_profile("custom")

    assert tool_permissions_module.list_profiles() == ["custom"]
    assert loaded.read.inside_repo == "ask"
    assert loaded.run.allow == {"ls"}
    assert loaded.run.chain_policy == "deny"

    tool_permissions_module.apply_profile(loaded)
    assert tool_permissions_module.permissions.name == "custom"
    assert tool_permissions_module.permissions.run.use_container is True


def _build_harness_stub(tmp_path, read_tool):
    from pico_chat.harness.permission_gate import PermissionGate
    harness = Harness.__new__(Harness)
    harness.debug_stream = NoopDebugStream()
    harness.state = AgentState.IDLE
    harness.history = []
    harness.workspace = str(tmp_path)
    harness.tools_map = {"read": read_tool}
    harness._permission_gate = PermissionGate(workspace=str(tmp_path), permissions=None)
    harness._tool_permissions = None
    return harness


class TestReadPermissions:
    """Test read permission enforcement."""

    def test_read_supports_line_ranges_and_line_numbers(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("one\ntwo\nthree\nfour\n")
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )

        tools = MinimalToolset(tmp_path, permissions=permissions)

        assert tools.read("test.txt", offset=1, limit=2) == "two\nthree\n"
        assert tools.read("test.txt", offset=1, limit=2, include_line_numbers=True) == (
            "     2\ttwo\n     3\tthree\n"
        )

    def test_read_rejects_invalid_offset(self, tmp_path):
        (tmp_path / "test.txt").write_text("content")
        tools = MinimalToolset(tmp_path)

        with pytest.raises(ToolError, match="Invalid offset"):
            tools.read("test.txt", offset=-1)

    def test_read_marks_character_truncation(self, tmp_path):
        (tmp_path / "test.txt").write_text("abcdefgh")
        tools = MinimalToolset(tmp_path)

        result = tools.read("test.txt", max_chars=3)
        assert result.startswith("abc\n[truncated:")
    
    def test_read_allowed_inside_repo(self, tmp_path):
        """Read should work when allowed inside repo."""
        # Setup
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Execute
        result = tools.read("test.txt")
        
        # Assert
        assert result == "content"
    
    def test_read_denied_inside_repo(self, tmp_path):
        """Read should fail when denied inside repo."""
        # Setup
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Execute & Assert
        with pytest.raises(ToolError, match="Permission denied: read inside repo"):
            tools.read("test.txt")
    
    def test_read_denied_outside_repo(self, tmp_path):
        """Read should fail when denied outside repo."""
        # Setup workspace and external file
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        external = tmp_path / "external"
        external.mkdir()
        external_file = external / "secret.txt"
        external_file.write_text("secret")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(workspace, permissions=permissions)
        
        # Execute & Assert
        with pytest.raises(ToolError, match="Permission denied: read outside repo"):
            tools.read(str(external_file))
    
    def test_read_allowed_outside_repo(self, tmp_path):
        """Read should work when allowed outside repo."""
        # Setup workspace and external file
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        external = tmp_path / "external"
        external.mkdir()
        external_file = external / "data.txt"
        external_file.write_text("external data")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="allow"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(workspace, permissions=permissions)
        
        # Execute
        result = tools.read(str(external_file))
        
        # Assert
        assert result == "external data"
    
    def test_read_ask_passes_tool_layer(self, tmp_path):
        """Read with 'ask' should pass in tool layer (harness enforces ask flow)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="ask", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )

        tools = MinimalToolset(tmp_path, permissions=permissions)
        assert tools.read("test.txt") == "content"


class TestHarnessReadPermissionFlow:
    """Test read permission ask/allow/deny through harness execution path."""

    def test_auto_deny_enforced_before_execution(self, tmp_path, monkeypatch):
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        read_tool = StubReadTool("content")
        harness = _build_harness_stub(tmp_path, read_tool)
        tool_call = {
            "id": "call_1",
            "function": {
                "name": "read",
                "arguments": json.dumps({"path": "test.txt"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        assert statuses == [chunks.ToolStatus.PERMISSION_REQUESTED, chunks.ToolStatus.DENIED]
        assert events[0].auto_decision is True
        assert events[1].denial_reason == "Auto-denied by security policy"
        assert read_tool.called is False
        # Check that denial message contains key information
        denial_content = messages[-1]["content"]
        assert "[TOOL DENIED]" in denial_content
        assert "Auto-denied by security policy" in denial_content
        assert "'read' tool call was not executed" in denial_content

    def test_user_deny_enforced_for_ask(self, tmp_path, monkeypatch):
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="ask", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        read_tool = StubReadTool("content")
        harness = _build_harness_stub(tmp_path, read_tool)
        harness.set_user_response("no")
        tool_call = {
            "id": "call_2",
            "function": {
                "name": "read",
                "arguments": json.dumps({"path": "test.txt"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        assert statuses == [chunks.ToolStatus.PERMISSION_REQUESTED, chunks.ToolStatus.DENIED]
        assert events[0].auto_decision is False
        assert events[1].denial_reason == "User denied"
        assert read_tool.called is False
        # Check that denial message contains key information
        denial_content = messages[-1]["content"]
        assert "[TOOL DENIED]" in denial_content
        assert "User denied" in denial_content
        assert "'read' tool call was not executed" in denial_content

    def test_allow_executes_tool(self, tmp_path, monkeypatch):
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        read_tool = StubReadTool("stubbed content")
        harness = _build_harness_stub(tmp_path, read_tool)
        tool_call = {
            "id": "call_3",
            "function": {
                "name": "read",
                "arguments": json.dumps({"path": "test.txt"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        assert statuses == [
            chunks.ToolStatus.PERMISSION_REQUESTED,
            chunks.ToolStatus.APPROVED,
            chunks.ToolStatus.EXECUTING,
            chunks.ToolStatus.COMPLETED,
        ]
        assert events[0].auto_decision is True
        assert read_tool.called is True
        assert events[-1].result == "stubbed content"
        assert messages[-1]["content"] == "stubbed content"


class TestWritePermissions:
    """Test write permission enforcement."""
    
    def test_write_allowed_inside_repo(self, tmp_path):
        """Write should work when allowed inside repo."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="allow", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Execute
        result = tools.write("output.txt", "data")
        
        # Assert
        assert "[OK]" in result
        assert (tmp_path / "output.txt").read_text() == "data"
    
    def test_write_denied_inside_repo(self, tmp_path):
        """Write should fail when denied inside repo."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Execute & Assert
        with pytest.raises(ToolError, match="Permission denied: write inside repo"):
            tools.write("output.txt", "data")
    
    def test_write_denied_outside_repo(self, tmp_path):
        """Write should fail when denied outside repo."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        external = tmp_path / "external"
        external.mkdir()
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="allow", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(workspace, permissions=permissions)
        
        # Execute & Assert
        with pytest.raises(ToolError, match="Permission denied: write outside repo"):
            tools.write(str(external / "file.txt"), "data")
    
    def test_write_allowed_outside_repo(self, tmp_path):
        """Write should work when allowed outside repo."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        external = tmp_path / "external"
        external.mkdir()
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="allow", outside_repo="allow"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(workspace, permissions=permissions)
        
        # Execute
        result = tools.write(str(external / "file.txt"), "external")
        
        # Assert
        assert "[OK]" in result
        assert (external / "file.txt").read_text() == "external"


class TestPatchPermissions:
    """Test patch permission enforcement."""
    
    def test_patch_allowed_inside_repo(self, tmp_path):
        """Patch should work when allowed inside repo."""
        # Setup
        test_file = tmp_path / "code.py"
        test_file.write_text("old = 1\n")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="allow", outside_repo="deny"),
            patch=FilePermissions(inside_repo="allow", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        patch_content = """code.py
<<<<<<< SEARCH
old = 1
=======
new = 2
>>>>>>> REPLACE
"""
        
        # Execute
        result = tools.patch(patch_content)
        
        # Assert
        assert "[OK]" in result
        assert test_file.read_text() == "new = 2\n"
    
    def test_patch_denied_inside_repo(self, tmp_path):
        """Patch should fail when denied inside repo."""
        test_file = tmp_path / "code.py"
        test_file.write_text("old = 1\n")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="allow", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        patch_content = """code.py
<<<<<<< SEARCH
old = 1
=======
new = 2
>>>>>>> REPLACE
"""
        
        # Execute & Assert
        with pytest.raises(ToolError, match="Permission denied: patch inside repo"):
            tools.patch(patch_content)
    
    def test_patch_denied_outside_repo(self, tmp_path):
        """Patch should fail when denied outside repo."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        external = tmp_path / "external"
        external.mkdir()
        external_file = external / "code.py"
        external_file.write_text("old = 1\n")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="allow"),
            write=FilePermissions(inside_repo="allow", outside_repo="allow"),
            patch=FilePermissions(inside_repo="allow", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(workspace, permissions=permissions)
        
        patch_content = f"""{external_file}
<<<<<<< SEARCH
old = 1
=======
new = 2
>>>>>>> REPLACE
"""
        
        # Execute & Assert
        with pytest.raises(ToolError, match="Permission denied: patch outside repo"):
            tools.patch(patch_content)


class TestRunPermissions:
    """Test run command permission enforcement."""
    
    def test_run_allowed(self, tmp_path):
        """Run should work when allowed."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="allow"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Execute
        result = tools.run("echo hello")
        
        # Assert
        assert "hello" in result
        assert "[exit:0]" in result
    
    def test_run_denied(self, tmp_path):
        """Run should fail when denied."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(allow=set(), deny=set(), ask=set(), others="deny"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Execute & Assert
        with pytest.raises(ToolError, match="not in allowlist"):
            tools.run("echo hello")


class TestAskPermissions:
    """Test 'ask' permission with stubbed user input."""
    
    def test_run_ask_with_user_approval(self, tmp_path):
        """Run with 'ask' should work when user approves."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="ask"),
        )
        
        # Mock confirmation callback that approves
        def approve_callback(command: str) -> bool:
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # Execute - use git (interactive command) that will trigger confirmation
        result = tools.run("git --version")
        
        # Assert
        assert "git" in result.lower()
        assert "[exit:0]" in result
    
    def test_run_ask_with_user_denial(self, tmp_path):
        """Run with 'ask' should fail when user denies."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="ask"),
        )
        
        # Mock confirmation callback that denies
        def deny_callback(command: str) -> bool:
            return False
        
        tools = MinimalToolset(tmp_path, confirmation_callback=deny_callback, permissions=permissions)
        
        # Execute & Assert - use git (interactive command) that will trigger confirmation
        with pytest.raises(ToolError, match="User denied"):
            tools.run("git status")


class TestPermissionProfiles:
    """Test different permission profiles."""
    
    def test_strict_profile_denies_outside_operations(self, tmp_path):
        """Strict profile should deny operations outside repo."""
        from pico_chat.harness.tool_permissions import strict
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        external = tmp_path / "external"
        external.mkdir()
        external_file = external / "file.txt"
        external_file.write_text("data")
        
        tools = MinimalToolset(workspace, permissions=strict)
        
        # All outside operations should be denied
        with pytest.raises(ToolError, match="Permission denied"):
            tools.read(str(external_file))
    
    def test_unrestricted_profile_allows_all(self, tmp_path):
        """Unrestricted profile should allow all operations."""
        from pico_chat.harness.tool_permissions import unrestricted
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        external = tmp_path / "external"
        external.mkdir()
        
        tools = MinimalToolset(workspace, permissions=unrestricted)
        
        # All operations should work
        result = tools.write(str(external / "test.txt"), "data")
        assert "[OK]" in result
        
        result = tools.read(str(external / "test.txt"))
        assert result == "data"
        
        result = tools.run("echo test")
        assert "test" in result
    
    def test_locked_profile_denies_all(self, tmp_path):
        """Locked profile should deny all operations."""
        from pico_chat.harness.tool_permissions import locked
        
        test_file = tmp_path / "test.txt"
        test_file.write_text("data")
        
        tools = MinimalToolset(tmp_path, permissions=locked)
        
        # All operations should be denied
        with pytest.raises(ToolError, match="Permission denied"):
            tools.read("test.txt")
        
        with pytest.raises(ToolError, match="Permission denied"):
            tools.write("output.txt", "data")
        
        with pytest.raises(ToolError, match="is blocked"):
            tools.run("echo test")


class TestPathResolution:
    """Test path resolution and inside/outside repo detection."""
    
    def test_relative_path_inside_repo(self, tmp_path):
        """Relative paths should be resolved inside repo."""
        test_file = tmp_path / "subdir" / "file.txt"
        test_file.parent.mkdir()
        test_file.write_text("content")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Execute with relative path
        result = tools.read("subdir/file.txt")
        
        # Assert
        assert result == "content"
    
    def test_absolute_path_outside_repo(self, tmp_path):
        """Absolute paths outside workspace should be detected."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        external = tmp_path / "external"
        external.mkdir()
        external_file = external / "file.txt"
        external_file.write_text("external")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(workspace, permissions=permissions)
        
        # Execute with absolute path
        with pytest.raises(ToolError, match="Permission denied: read outside repo"):
            tools.read(str(external_file))
    
    def test_parent_directory_traversal(self, tmp_path):
        """Parent directory traversal should be detected as outside repo."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        external_file = tmp_path / "secret.txt"
        external_file.write_text("secret")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="allow", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(others="deny"),
        )
        
        tools = MinimalToolset(workspace, permissions=permissions)
        
        # Try to access parent directory
        with pytest.raises(ToolError, match="Permission denied: read outside repo"):
            tools.read("../secret.txt")


class _StubRunTool:
    """Stub run tool for harness integration tests."""
    def __init__(self, result: str = "[exit:0]"):
        self.result = result
        self.called = False
        self.called_with = None

    def execute(self, **kwargs):
        self.called = True
        self.called_with = kwargs
        return self.result


class TestHarnessRunPermissionFlow:
    """Test run permission ask/allow/deny through harness execution path."""

    def test_auto_allow_benign_command(self, tmp_path, monkeypatch):
        """Benign commands in ALLOW list should auto-approve."""
        from pico_chat.harness.tool_permissions import CMD_DEFAULT_ALLOW
        
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=CMD_DEFAULT_ALLOW,
                ask=set(),
                deny=set(),
                others="deny",
            ),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        run_tool = _StubRunTool(".\n[exit:0]")
        harness = Harness.__new__(Harness)
        harness.debug_stream = NoopDebugStream()
        harness.state = AgentState.IDLE
        harness.history = []
        harness.workspace = str(tmp_path)
        harness.tools_map = {"run": run_tool}
        from pico_chat.harness.permission_gate import PermissionGate
        harness._permission_gate = PermissionGate(workspace=str(tmp_path), permissions=None)
        harness._tool_permissions = None
        
        tool_call = {
            "id": "call_1",
            "function": {
                "name": "run",
                "arguments": json.dumps({"command": "find . -maxdepth 1"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        # Should auto-approve and execute
        assert statuses == [
            chunks.ToolStatus.PERMISSION_REQUESTED,
            chunks.ToolStatus.APPROVED,
            chunks.ToolStatus.EXECUTING,
            chunks.ToolStatus.COMPLETED,
        ]
        assert events[0].auto_decision is True
        assert run_tool.called is True
        assert run_tool.called_with["command"] == "find . -maxdepth 1"

    def test_auto_ask_dangerous_pattern(self, tmp_path, monkeypatch):
        """Commands with dangerous patterns should require user confirmation."""
        from pico_chat.harness.tool_permissions import CMD_DEFAULT_ALLOW
        
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=CMD_DEFAULT_ALLOW,
                ask=set(),
                deny=set(),
                others="deny",
            ),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        run_tool = _StubRunTool("[exit:0]")
        harness = Harness.__new__(Harness)
        harness.debug_stream = NoopDebugStream()
        harness.state = AgentState.IDLE
        harness.history = []
        harness.workspace = str(tmp_path)
        harness.tools_map = {"run": run_tool}
        from pico_chat.harness.permission_gate import PermissionGate
        harness._permission_gate = PermissionGate(workspace=str(tmp_path), permissions=None)
        harness._tool_permissions = None
        harness.set_user_response("yes")
        
        tool_call = {
            "id": "call_2",
            "function": {
                "name": "run",
                "arguments": json.dumps({"command": "find . -exec rm {} +"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        # Should ask user (dangerous pattern detected)
        assert statuses == [
            chunks.ToolStatus.PERMISSION_REQUESTED,
            chunks.ToolStatus.APPROVED,
            chunks.ToolStatus.EXECUTING,
            chunks.ToolStatus.COMPLETED,
        ]
        assert events[0].auto_decision is False  # User must approve
        assert run_tool.called is True

    def test_auto_ask_command_in_ask_list(self, tmp_path, monkeypatch):
        """Commands in ASK list should require user confirmation."""
        from pico_chat.harness.tool_permissions import CMD_DEFAULT_ASK
        
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=set(),
                ask=CMD_DEFAULT_ASK,
                deny=set(),
                others="deny",
            ),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        run_tool = _StubRunTool("[exit:0]")
        harness = Harness.__new__(Harness)
        harness.debug_stream = NoopDebugStream()
        harness.state = AgentState.IDLE
        harness.history = []
        harness.workspace = str(tmp_path)
        harness.tools_map = {"run": run_tool}
        from pico_chat.harness.permission_gate import PermissionGate
        harness._permission_gate = PermissionGate(workspace=str(tmp_path), permissions=None)
        harness._tool_permissions = None
        harness.set_user_response("allow")
        
        tool_call = {
            "id": "call_3",
            "function": {
                "name": "run",
                "arguments": json.dumps({"command": "git status"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        # Should ask user (git in ASK list)
        assert statuses == [
            chunks.ToolStatus.PERMISSION_REQUESTED,
            chunks.ToolStatus.APPROVED,
            chunks.ToolStatus.EXECUTING,
            chunks.ToolStatus.COMPLETED,
        ]
        assert events[0].auto_decision is False
        assert run_tool.called is True

    def test_auto_deny_blocked_command(self, tmp_path, monkeypatch):
        """Commands in DENY list should auto-deny."""
        from pico_chat.harness.tool_permissions import CMD_DEFAULT_DENY
        
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=set(),
                ask=set(),
                deny=CMD_DEFAULT_DENY,
                others="deny",
            ),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        run_tool = _StubRunTool("[exit:0]")
        harness = Harness.__new__(Harness)
        harness.debug_stream = NoopDebugStream()
        harness.state = AgentState.IDLE
        harness.history = []
        harness.workspace = str(tmp_path)
        harness.tools_map = {"run": run_tool}
        from pico_chat.harness.permission_gate import PermissionGate
        harness._permission_gate = PermissionGate(workspace=str(tmp_path), permissions=None)
        harness._tool_permissions = None
        
        tool_call = {
            "id": "call_4",
            "function": {
                "name": "run",
                "arguments": json.dumps({"command": "sudo rm -rf /"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        # Should auto-deny
        assert statuses == [chunks.ToolStatus.PERMISSION_REQUESTED, chunks.ToolStatus.DENIED]
        assert events[0].auto_decision is True
        assert events[1].denial_reason == "Auto-denied by security policy"
        assert run_tool.called is False
        # Check that denial message contains key information
        denial_content = messages[-1]["content"]
        assert "[TOOL DENIED]" in denial_content
        assert "Auto-denied by security policy" in denial_content

    def test_user_deny_blocks_execution(self, tmp_path, monkeypatch):
        """User denying permission should block execution."""
        from pico_chat.harness.tool_permissions import CMD_DEFAULT_ASK
        
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=set(),
                ask=CMD_DEFAULT_ASK,
                deny=set(),
                others="deny",
            ),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        run_tool = _StubRunTool("[exit:0]")
        harness = Harness.__new__(Harness)
        harness.debug_stream = NoopDebugStream()
        harness.state = AgentState.IDLE
        harness.history = []
        harness.workspace = str(tmp_path)
        harness.tools_map = {"run": run_tool}
        from pico_chat.harness.permission_gate import PermissionGate
        harness._permission_gate = PermissionGate(workspace=str(tmp_path), permissions=None)
        harness._tool_permissions = None
        harness.set_user_response("no")
        
        tool_call = {
            "id": "call_5",
            "function": {
                "name": "run",
                "arguments": json.dumps({"command": "rm file.txt"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        # Should ask user, then deny
        assert statuses == [chunks.ToolStatus.PERMISSION_REQUESTED, chunks.ToolStatus.DENIED]
        assert events[0].auto_decision is False
        assert events[1].denial_reason == "User denied"
        assert run_tool.called is False
        # Check that denial message contains key information
        denial_content = messages[-1]["content"]
        assert "[TOOL DENIED]" in denial_content
        assert "User denied" in denial_content

    def test_chain_command_requires_ask(self, tmp_path, monkeypatch):
        """Command chains should require user confirmation."""
        from pico_chat.harness.tool_permissions import CMD_DEFAULT_ALLOW
        
        profile = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=CMD_DEFAULT_ALLOW,
                ask=set(),
                deny=set(),
                others="deny",
                chain_policy="ask",
            ),
        )
        monkeypatch.setattr(tool_permissions_module, "permissions", profile)

        run_tool = _StubRunTool("[exit:0]")
        harness = Harness.__new__(Harness)
        harness.debug_stream = NoopDebugStream()
        harness.state = AgentState.IDLE
        harness.history = []
        harness.workspace = str(tmp_path)
        harness.tools_map = {"run": run_tool}
        from pico_chat.harness.permission_gate import PermissionGate
        harness._permission_gate = PermissionGate(workspace=str(tmp_path), permissions=None)
        harness._tool_permissions = None
        harness.set_user_response("yes")
        
        tool_call = {
            "id": "call_6",
            "function": {
                "name": "run",
                "arguments": json.dumps({"command": "ls -la | grep test"}),
            },
        }

        events, messages = run_harness_tool_call(harness, tool_call)
        statuses = [e.status for e in events]

        # Should ask user (chain detected)
        assert statuses == [
            chunks.ToolStatus.PERMISSION_REQUESTED,
            chunks.ToolStatus.APPROVED,
            chunks.ToolStatus.EXECUTING,
            chunks.ToolStatus.COMPLETED,
        ]
        assert events[0].auto_decision is False  # Chain requires confirmation
        assert run_tool.called is True
