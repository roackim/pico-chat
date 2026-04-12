"""
Tests for benign usage of commands that have dangerous pattern checking.

These tests verify that commands in CMD_DANGEROUS_PATTERNS (find, awk, sed)
work without confirmation when used safely (no dangerous patterns present).
"""
import pytest
from pathlib import Path

from pico_chat.harness.tools import MinimalToolset
from pico_chat.harness.tool_permissions import (
    ToolPermissionsProfile,
    FilePermissions,
    RunPermissions,
    CMD_DEFAULT_ALLOW,
)


class TestBenignDangerousCommands:
    """Test that benign usage of potentially dangerous commands works without asking."""
    
    def test_find_maxdepth_allowed(self, tmp_path):
        """find with -maxdepth should work without confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=CMD_DEFAULT_ALLOW,
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        
        # find with -maxdepth should work (no dangerous patterns)
        result = tools.run("find . -maxdepth 1")
        assert "[exit:0]" in result
    
    def test_find_type_allowed(self, tmp_path):
        """find with -type should work without confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=CMD_DEFAULT_ALLOW,
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # find with -type should work (no dangerous patterns)
        result = tools.run("find . -type f")
        assert "[exit:0]" in result
    
    def test_find_name_allowed(self, tmp_path):
        """find with -name should work without confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=CMD_DEFAULT_ALLOW,
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # find with -name should work (no dangerous patterns)
        result = tools.run("find . -name '*.txt'")
        assert "[exit:0]" in result
    
    def test_find_print_allowed(self, tmp_path):
        """find with -print should work without confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow=CMD_DEFAULT_ALLOW,
                deny=set(),
                ask=set(),
                others="deny",
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # find with -print should work (no dangerous patterns)
        result = tools.run("find . -print")
        assert "[exit:0]" in result
    
    def test_awk_basic_allowed(self, tmp_path):
        """Basic awk without system() should work without confirmation."""
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
                chain_policy="ask",  # Need for pipe
            ),
        )
        
        def approve_callback(cmd):
            # Only approve for the pipe, not for any command itself
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # awk without system() should work
        result = tools.run("echo 'hello world' | awk '{print $1}'")
        assert "hello" in result
        assert "[exit:0]" in result
    
    def test_awk_field_manipulation_allowed(self, tmp_path):
        """awk field manipulation should work without confirmation."""
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
                chain_policy="ask",
            ),
        )
        
        def approve_callback(cmd):
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # awk with field operations should work
        result = tools.run("echo '1 2 3' | awk '{print $1+$2+$3}'")
        assert "6" in result
        assert "[exit:0]" in result
    
    def test_sed_substitution_allowed(self, tmp_path):
        """Basic sed substitution should work without confirmation."""
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
                chain_policy="ask",
            ),
        )
        
        def approve_callback(cmd):
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # sed substitution without /e flag should work
        result = tools.run("echo 'hello world' | sed 's/world/universe/'")
        assert "universe" in result
        assert "[exit:0]" in result
    
    def test_sed_delete_allowed(self, tmp_path):
        """sed delete operation should work without confirmation."""
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
                chain_policy="ask",
            ),
        )
        
        def approve_callback(cmd):
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # sed with 'd' (delete) should work - it's not the dangerous /e flag
        result = tools.run("echo -e 'line1\\nline2\\nline3' | sed '2d'")
        assert "line1" in result
        assert "[exit:0]" in result
    
    def test_find_permissive_profile(self, tmp_path):
        """Test find with permissive profile specifically."""
        from pico_chat.harness.tool_permissions import permissive
        
        tools = MinimalToolset(tmp_path, permissions=permissive)
        
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        
        # find with -maxdepth should work without asking in permissive profile
        result = tools.run("find . -maxdepth 1")
        assert "[exit:0]" in result
        assert "test.txt" in result or "." in result
    
    def test_find_name_permissive_profile(self, tmp_path):
        """Test find with -name in permissive profile."""
        from pico_chat.harness.tool_permissions import permissive
        
        tools = MinimalToolset(tmp_path, permissions=permissive)
        
        # find with -name should work without asking
        result = tools.run("find . -name '*.py'")
        assert "[exit:0]" in result
    
    def test_awk_permissive_profile(self, tmp_path):
        """Test awk without system() in permissive profile."""
        from pico_chat.harness.tool_permissions import permissive
        
        def approve_callback(cmd):
            # Approve pipe chain
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissive)
        
        # awk without system() should only ask for the pipe, not the awk command
        result = tools.run("echo 'a b c' | awk '{print $2}'")
        assert "b" in result
        assert "[exit:0]" in result
    
    def test_sed_permissive_profile(self, tmp_path):
        """Test sed without /e flag in permissive profile."""
        from pico_chat.harness.tool_permissions import permissive
        
        def approve_callback(cmd):
            # Approve pipe chain
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissive)
        
        # sed without /e should work
        result = tools.run("echo 'test' | sed 's/test/success/'")
        assert "success" in result
        assert "[exit:0]" in result
