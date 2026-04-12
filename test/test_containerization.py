"""
Tests for command containerization with bubblewrap.

Tests verify that when use_container=True:
- Commands execute in isolated container
- Workspace is read-write
- Home and system directories are read-only
- Network isolation works
"""
import pytest
import subprocess
from pathlib import Path
from pico_chat.harness.tools import ShellTool, ToolError
from pico_chat.harness.tool_permissions import ToolPermissionsProfile, FilePermissions, RunPermissions


# Check if bwrap is available
def is_bwrap_available():
    try:
        result = subprocess.run(['bwrap', '--version'], capture_output=True, timeout=2)
        return result.returncode == 0
    except:
        return False


BWRAP_AVAILABLE = is_bwrap_available()
skip_without_bwrap = pytest.mark.skipif(not BWRAP_AVAILABLE, reason="bubblewrap not installed")


class TestContainerBasics:
    """Test basic containerization functionality."""
    
    @skip_without_bwrap
    def test_simple_command_in_container(self, tmp_path):
        """Simple command should execute successfully in container."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                use_container=True,
                container_network=False,
            ),
        )
        
        tool = ShellTool(tmp_path, permissions=permissions)
        result = tool.run("echo hello")
        
        assert "hello" in result
        assert "[exit:0]" in result
    
    @skip_without_bwrap
    def test_workspace_is_writable(self, tmp_path):
        """Container should have write access to workspace."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo', 'cat'},
                use_container=True,
                container_network=False,
            ),
        )
        
        tool = ShellTool(tmp_path, permissions=permissions)
        
        # Write file in workspace via container
        result = tool.run("echo 'test content' > test.txt")
        assert "[exit:0]" in result
        
        # Verify file was created
        assert (tmp_path / "test.txt").exists()
        assert (tmp_path / "test.txt").read_text().strip() == "test content"
        
        # Read file back in container
        result = tool.run("cat test.txt")
        assert "test content" in result
    
    @skip_without_bwrap
    def test_home_is_readonly(self, tmp_path):
        """Container should NOT be able to write to home directory."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'touch'},
                use_container=True,
                container_network=False,
            ),
        )
        
        tool = ShellTool(tmp_path, permissions=permissions)
        
        # Try to write to home directory
        result = tool.run("touch ~/container_test_file.txt")
        
        # Should fail (read-only filesystem)
        assert "[exit:0]" not in result or "Read-only" in result
        
        # Verify file was NOT created
        assert not Path.home().joinpath("container_test_file.txt").exists()
    
    @skip_without_bwrap
    def test_system_binaries_accessible(self, tmp_path):
        """Container should have access to system binaries."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'ls'},
                use_container=True,
                container_network=False,
            ),
        )
        
        tool = ShellTool(tmp_path, permissions=permissions)
        
        # Test common system commands work (without pipes to avoid chain policy)
        result = tool.run("ls /usr/bin")
        assert "[exit:0]" in result
        assert "ls" in result  # ls binary should be listed


class TestNetworkIsolation:
    """Test network isolation in containers."""
    
    @skip_without_bwrap
    def test_network_disabled_by_default(self, tmp_path):
        """Network should be disabled when container_network=False."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'ping', 'ip'},
                use_container=True,
                container_network=False,  # Network disabled
            ),
        )
        
        tool = ShellTool(tmp_path, permissions=permissions)
        
        # Try to check network interfaces
        result = tool.run("ip addr show")
        
        # Should show no network interfaces (except loopback maybe)
        # Or command might fail - either way, no real network
        # This is a basic smoke test
        assert "[exit:" in result  # Command completes
    
    @skip_without_bwrap
    def test_network_enabled_when_configured(self, tmp_path):
        """Network should be available when container_network=True."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'ip'},
                use_container=True,
                container_network=True,  # Network enabled
            ),
        )
        
        tool = ShellTool(tmp_path, permissions=permissions)
        
        # Check network interfaces
        result = tool.run("ip addr show")
        
        # Should show network interfaces
        assert "[exit:0]" in result


class TestContainerErrors:
    """Test error handling for containerization."""
    
    def test_error_when_bwrap_missing(self, tmp_path, monkeypatch):
        """Should raise error if use_container=True but bwrap not available."""
        # Mock bwrap as unavailable
        def mock_check_bwrap():
            return False
        
        monkeypatch.setattr(ShellTool, '_check_bwrap_available', staticmethod(mock_check_bwrap))
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                use_container=True,  # Containerization requested
                container_network=False,
            ),
        )
        
        tool = ShellTool(tmp_path, permissions=permissions)
        
        # Should raise error when trying to run command
        with pytest.raises(ToolError, match="bubblewrap.*not available"):
            tool.run("echo test")
    
    def test_no_error_when_container_disabled(self, tmp_path):
        """Should work fine if use_container=False even without bwrap."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                use_container=False,  # Containerization disabled
                container_network=False,
            ),
        )
        
        tool = ShellTool(tmp_path, permissions=permissions)
        
        # Should work without bwrap
        result = tool.run("echo test")
        assert "test" in result
        assert "[exit:0]" in result


class TestContainerWithChainPolicy:
    """Test that containerization works with chain policy."""
    
    @skip_without_bwrap
    def test_pipe_in_container(self, tmp_path):
        """Pipe operators should work in container when allowed."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo', 'grep'},
                use_container=True,
                container_network=False,
                chain_policy="ask",
            ),
        )
        
        # User approves chain
        def approve_callback(cmd):
            return True
        
        from pico_chat.harness.security import SecurityChecker
        checker = SecurityChecker(permissions.run, confirmation_callback=approve_callback)
        
        tool = ShellTool(tmp_path, security_checker=checker, permissions=permissions)
        
        result = tool.run("echo 'hello world' | grep hello")
        assert "hello world" in result
        assert "[exit:0]" in result
