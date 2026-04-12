"""
Tests for dangerous pattern detection in allowed commands.

Even if a command is in the ALLOW list, dangerous patterns should escalate it to ASK.
This prevents accidental execution of dangerous operations like:
- find -exec
- awk system()
- sed /e flag
"""
import pytest
from pico_chat.harness.tools import MinimalToolset, ToolError
from pico_chat.harness.tool_permissions import ToolPermissionsProfile, FilePermissions, RunPermissions


class TestFindDangerousPatterns:
    """Test dangerous pattern detection in find command."""
    
    def test_find_safe_usage_allowed(self, tmp_path):
        """Safe find usage should work without confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'find'},
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Create test file
        (tmp_path / "test.txt").write_text("content")
        
        # Safe find usage should work
        result = tools.run("find . -name '*.txt'")
        assert "test.txt" in result
        assert "[exit:0]" in result
    
    def test_find_exec_requires_confirmation(self, tmp_path):
        """find with -exec should require confirmation due to dangerous pattern."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'find', 'rm'},
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        # No confirmation callback - should fail
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Use + terminator instead of \; to avoid chain detection
        with pytest.raises(ToolError, match="dangerous pattern.*-exec"):
            tools.run("find . -name *.txt -exec rm {} +")
    
    def test_find_exec_with_user_approval(self, tmp_path):
        """find -exec should work when user approves."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'find', 'echo'},
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        # User approves
        def approve_callback(cmd):
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # Use + terminator to avoid chain detection
        result = tools.run("find . -name *.txt -exec echo {} +")
        assert "[exit:0]" in result
    
    def test_find_delete_requires_confirmation(self, tmp_path):
        """find with -delete should require confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'find'},
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="dangerous pattern.*-delete.*requires confirmation"):
            tools.run("find . -name '*.tmp' -delete")
    
    def test_find_execdir_requires_confirmation(self, tmp_path):
        """find with -execdir should require confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'find', 'cat'},  # Allow cat too
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="dangerous pattern.*-exec"):
            tools.run("find . -execdir cat {} +")


class TestAwkDangerousPatterns:
    """Test dangerous pattern detection in awk command."""
    
    def test_awk_safe_usage_allowed(self, tmp_path):
        """Safe awk usage should work without confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'awk', 'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="ask",  # Need callback for pipe
            ),
        )
        
        def approve_callback(cmd):
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # Safe awk usage should work
        result = tools.run("echo 'hello world' | awk '{print $1}'")
        assert "hello" in result
        assert "[exit:0]" in result
    
    def test_awk_system_requires_confirmation(self, tmp_path):
        """awk with system() should require confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'awk'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny",  # Disable chain to focus on pattern detection
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="dangerous pattern.*system\\(.*requires confirmation"):
            tools.run("awk 'BEGIN {system(\"whoami\")}'")


class TestSedDangerousPatterns:
    """Test dangerous pattern detection in sed command."""
    
    def test_sed_safe_usage_allowed(self, tmp_path):
        """Safe sed usage should work without confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'sed', 'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="ask",  # Need callback for pipe
            ),
        )
        
        def approve_callback(cmd):
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # Safe sed usage should work
        result = tools.run("echo 'hello world' | sed 's/world/universe/'")
        assert "universe" in result
        assert "[exit:0]" in result
    
    def test_sed_e_flag_requires_confirmation(self, tmp_path):
        """sed with /e flag should require confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'sed'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="dangerous pattern.*/e.*requires confirmation"):
            tools.run("sed 's/test/whoami/e' file.txt")
    
    def test_sed_false_positive_acceptable(self, tmp_path):
        """False positives with /e in text are acceptable (safe default)."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'sed'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # This might be a false positive (searching for "/e" text)
        # But it's acceptable to require confirmation for safety
        with pytest.raises(ToolError, match="dangerous pattern.*/e.*requires confirmation"):
            tools.run("sed '/error/d' file.txt")  # Contains '/e'


class TestMultipleDangerousPatterns:
    """Test commands with multiple dangerous patterns."""
    
    def test_find_multiple_dangerous_flags(self, tmp_path):
        """Command with multiple dangerous patterns should be caught."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'find'},
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Command with -ok (another dangerous flag)
        with pytest.raises(ToolError, match="dangerous pattern.*-ok"):
            tools.run("find . -name *.txt -ok cat {} +")
