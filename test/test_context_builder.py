"""
Tests for context_builder guardrails.

Verifies that:
- is_git_repo() correctly detects git repositories
- build_harness_context() skips the file tree when not in a git repo
- build_harness_context() builds the tree normally when inside a git repo
"""
import pytest
from pathlib import Path
from pico_chat.harness.context_builder import is_git_repo, build_harness_context


class TestIsGitRepo:
    def test_detects_git_repo(self, tmp_path):
        """Directory containing .git should be detected as a git repo."""
        (tmp_path / '.git').mkdir()
        assert is_git_repo(tmp_path) is True

    def test_detects_git_repo_in_parent(self, tmp_path):
        """Subdirectory of a git repo should also be detected."""
        (tmp_path / '.git').mkdir()
        subdir = tmp_path / 'src' / 'module'
        subdir.mkdir(parents=True)
        assert is_git_repo(subdir) is True

    def test_non_git_directory(self, tmp_path):
        """Plain directory with no .git anywhere should return False."""
        # tmp_path is under /tmp which should not be a git repo
        # Use a deeply nested path to avoid any accidental .git hits
        subdir = tmp_path / 'a' / 'b' / 'c'
        subdir.mkdir(parents=True)
        assert is_git_repo(subdir) is False


class TestBuildHarnessContext:
    def test_skips_tree_when_not_git_repo(self, tmp_path):
        """Should return early with a warning when not in a git repo."""
        (tmp_path / 'file.py').write_text("# hello")
        result = build_harness_context(str(tmp_path), format="flat")
        assert "[WARNING" in result
        assert "file.py" not in result

    def test_skips_tree_format_when_not_git_repo(self, tmp_path):
        """Should return early with a warning for tree format too."""
        (tmp_path / 'file.py').write_text("# hello")
        result = build_harness_context(str(tmp_path), format="tree")
        assert "[WARNING" in result
        assert "file.py" not in result

    def test_builds_tree_in_git_repo(self, tmp_path):
        """Should build file list normally when inside a git repo."""
        (tmp_path / '.git').mkdir()
        (tmp_path / 'hello.py').write_text("# hello")
        result = build_harness_context(str(tmp_path), format="flat")
        assert "[WARNING" not in result
        assert "hello.py" in result

    def test_builds_tree_format_in_git_repo(self, tmp_path):
        """Should build tree output normally when inside a git repo."""
        (tmp_path / '.git').mkdir()
        (tmp_path / 'hello.py').write_text("# hello")
        result = build_harness_context(str(tmp_path), format="tree")
        assert "[WARNING" not in result
        assert "hello.py" in result

    def test_result_includes_project_root(self, tmp_path):
        """Project Root line should always be present."""
        result = build_harness_context(str(tmp_path), format="flat")
        assert f"Project Root: {tmp_path}" in result
