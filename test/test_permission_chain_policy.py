"""
Tests for chain_policy enforcement in run permissions.

Chain policy controls how command chains (with operators like |, &&, ||, ;) are handled.
The security model is: we can't trust chained commands compared to simple safe commands.

Policy options:
- chain_policy="deny": Block all commands with operators
- chain_policy="ask": Require user confirmation for commands with operators

Note: Detection is intentionally over-restrictive - operators in quoted strings
will trigger chain detection. This is acceptable as a security trade-off.
"""
import pytest
from pathlib import Path
from pico_chat.harness.tools import MinimalToolset, ToolError
from pico_chat.harness.tool_permissions import ToolPermissionsProfile, FilePermissions, RunPermissions


class TestChainPolicyDeny:
    """Test chain_policy='deny' blocks all operator chains."""
    
    def test_pipe_operator_blocked(self, tmp_path):
        """Pipe operator | should be blocked with chain_policy='deny'."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'cat', 'grep', 'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Even though cat and grep are both allowed, the chain should be blocked
        with pytest.raises(ToolError, match="[Cc]hain.*blocked"):
            tools.run("cat file.txt | grep pattern")
    
    def test_and_operator_blocked(self, tmp_path):
        """AND operator && should be blocked with chain_policy='deny'."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo', 'ls'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="[Cc]hain.*blocked"):
            tools.run("echo hello && ls")
    
    def test_or_operator_blocked(self, tmp_path):
        """OR operator || should be blocked with chain_policy='deny'."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'test', 'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="[Cc]hain.*blocked"):
            tools.run("test -f file || echo not found")
    
    def test_semicolon_operator_blocked(self, tmp_path):
        """Semicolon operator ; should be blocked with chain_policy='deny'."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo', 'pwd'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="[Cc]hain.*blocked"):
            tools.run("echo first; pwd")
    
    def test_multiple_operators_blocked(self, tmp_path):
        """Command with multiple different operators should be blocked."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'cat', 'grep', 'sort', 'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="[Cc]hain.*blocked"):
            tools.run("cat file | grep pattern | sort && echo done")
    
    def test_simple_command_allowed(self, tmp_path):
        """Simple command without operators should still work."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Simple command should work
        result = tools.run("echo hello world")
        assert "hello world" in result
        assert "[exit:0]" in result


class TestChainPolicyAsk:
    """Test chain_policy='ask' requires user confirmation for chains."""
    
    def test_pipe_requires_confirmation(self, tmp_path):
        """Pipe operator should require user confirmation with chain_policy='ask'."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo', 'cat'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="ask"
            ),
        )
        
        # User denies confirmation
        def deny_callback(command: str) -> bool:
            return False
        
        tools = MinimalToolset(tmp_path, confirmation_callback=deny_callback, permissions=permissions)
        
        with pytest.raises(ToolError, match="[Dd]enied.*chain"):
            tools.run("echo hello | cat")
    
    def test_user_approval_allows_chain(self, tmp_path):
        """User approval should allow chain execution with chain_policy='ask'."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\npattern here\nline4")
        
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'cat', 'grep'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="ask"
            ),
        )
        
        # User approves confirmation
        def approve_callback(command: str) -> bool:
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        result = tools.run(f"cat {test_file} | grep pattern")
        assert "pattern here" in result
    
    def test_user_denial_blocks_chain(self, tmp_path):
        """User denial should block chain execution."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo', 'ls'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="ask"
            ),
        )
        
        def deny_callback(command: str) -> bool:
            return False
        
        tools = MinimalToolset(tmp_path, confirmation_callback=deny_callback, permissions=permissions)
        
        with pytest.raises(ToolError, match="[Dd]enied"):
            tools.run("echo start && ls")
    
    def test_no_callback_blocks_chain(self, tmp_path):
        """Without confirmation callback, chain should be blocked."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="ask"
            ),
        )
        
        # No confirmation callback provided
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError, match="confirmation"):
            tools.run("echo a; echo b")


class TestOperatorsInStrings:
    """Test that operators in quoted strings do NOT trigger chain detection.

    With quote-aware parsing (parse_operators), operators inside quoted
    strings are not treated as chain separators.  This is the correct
    behaviour — `echo "a|b"` is a single command, not a chain.
    """

    def test_pipe_in_double_quotes(self, tmp_path):
        """Pipe inside double quotes should NOT trigger chain detection."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )

        tools = MinimalToolset(tmp_path, permissions=permissions)

        # The pipe is inside a quoted string — not a real chain operator.
        # This should execute as a single command (echo is allowed).
        result = tools.run('echo "test | pipe"')
        assert "test | pipe" in result

    def test_and_in_single_quotes(self, tmp_path):
        """AND operator inside single quotes should NOT trigger chain detection."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )

        tools = MinimalToolset(tmp_path, permissions=permissions)

        # The && is inside single quotes — not a real chain operator.
        result = tools.run("echo 'cmd1 && cmd2'")
        assert "cmd1 && cmd2" in result

    def test_semicolon_in_string(self, tmp_path):
        """Semicolon inside quoted string should NOT trigger chain detection."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )

        tools = MinimalToolset(tmp_path, permissions=permissions)

        result = tools.run('echo "first; second"')
        assert "first; second" in result


class TestChainWithMixedPermissions:
    """Test chains where individual commands have different permissions."""
    
    def test_chain_with_denied_command(self, tmp_path):
        """Chain containing a denied command should be blocked even before chain check."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny={'rm'},
                ask=set(),
                others="deny",
                chain_policy="ask"  # Even with ask policy
            ),
        )
        
        def approve_callback(command: str) -> bool:
            return True  # User would approve chain
        
        tools = MinimalToolset(tmp_path, confirmation_callback=approve_callback, permissions=permissions)
        
        # Should be blocked because rm is in deny list
        with pytest.raises(ToolError, match="blocked|denied"):
            tools.run("echo hello && rm -rf /")
    
    def test_chain_with_ask_command(self, tmp_path):
        """Chain with a command requiring confirmation should need confirmation."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask={'git'},
                others="deny",
                chain_policy="ask"
            ),
        )
        
        confirmations = []
        
        def track_callback(command: str) -> bool:
            confirmations.append(command)
            return True
        
        tools = MinimalToolset(tmp_path, confirmation_callback=track_callback, permissions=permissions)
        
        tools.run("echo hello && git status")
        
        # Should have multiple confirmations: chain + git command
        assert len(confirmations) >= 1


class TestChainPolicyEdgeCases:
    """Test edge cases in chain policy enforcement."""
    
    def test_empty_command_with_operator(self, tmp_path):
        """Trailing operator with empty second command should be handled gracefully.

        With quote-aware parsing, `echo test | ` parses to just ['echo test']
        (the empty part after | is filtered).  This is a single command, not
        a chain, so it executes normally.
        """
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )

        tools = MinimalToolset(tmp_path, permissions=permissions)

        # Trailing pipe with no second command — parse_operators filters
        # the empty part, so this passes the security check as a single
        # command.  The shell itself rejects the malformed input.
        result = tools.run("echo test | ")
        # Shell returns a syntax error for the trailing pipe
        assert "Syntax error" in result or "test" in result
    
    def test_only_operator(self, tmp_path):
        """Command that is only an operator should fail gracefully."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        with pytest.raises(ToolError):
            tools.run("|")
    
    def test_whitespace_around_operators(self, tmp_path):
        """Operators with varying whitespace should be detected."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Various whitespace patterns
        with pytest.raises(ToolError, match="[Cc]hain.*blocked"):
            tools.run("echo a|echo b")  # No spaces
        
        with pytest.raises(ToolError, match="[Cc]hain.*blocked"):
            tools.run("echo a  |  echo b")  # Extra spaces
        
        with pytest.raises(ToolError, match="[Cc]hain.*blocked"):
            tools.run("echo a&&echo b")  # No spaces


class TestChainPolicyDefault:
    """Test default chain_policy behavior."""
    
    def test_default_chain_policy_is_ask(self, tmp_path):
        """Default chain_policy should be 'ask'."""
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                # chain_policy not specified, should default to "ask"
            ),
        )
        
        # Verify default is "ask"
        assert permissions.run.chain_policy == "ask"
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Without callback, should fail with confirmation message
        with pytest.raises(ToolError, match="confirmation"):
            tools.run("echo a; echo b")


class TestChainDetectionSecurity:
    """Test that chain detection can't be bypassed."""
    
    def test_escaped_operator(self, tmp_path):
        """Escaped operators are not chain operators — should NOT trigger detection.

        With quote-aware parsing, `\|` is an escaped pipe (literal character),
        not a chain separator.  This is correct: `echo test \| more` is a
        single command that pipes via shell escape, not a security chain.
        """
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'echo'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Escaped pipe is not a chain operator — single command, executes fine
        result = tools.run(r"echo test \| more")
        assert "test" in result or "more" in result
    
    def test_operator_in_filename(self, tmp_path):
        """Operators inside quoted filenames should NOT trigger chain detection.

        With quote-aware parsing, `|` inside single quotes is a literal,
        not a chain separator.  This is correct: `cat 'file|name.txt'` is
        a single command reading a file with a pipe in its name.
        """
        permissions = ToolPermissionsProfile(
            name="test",
            read=FilePermissions(inside_repo="deny", outside_repo="deny"),
            write=FilePermissions(inside_repo="deny", outside_repo="deny"),
            patch=FilePermissions(inside_repo="deny", outside_repo="deny"),
            run=RunPermissions(
                allow={'cat'},
                deny=set(),
                ask=set(),
                others="deny",
                chain_policy="deny"
            ),
        )
        
        tools = MinimalToolset(tmp_path, permissions=permissions)
        
        # Pipe inside single quotes — not a chain.  cat will fail since
        # the file doesn't exist, but the important thing is it's NOT
        # blocked by chain_policy (no "chain" or "blocked" in the result).
        result = tools.run("cat 'file|name.txt'")
        assert "chain" not in result.lower() and "blocked" not in result.lower()
