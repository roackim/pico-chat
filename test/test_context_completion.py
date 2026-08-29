"""Tests for ContextCompletion subdirectory drilling and Tab path building."""

from pico_chat.ui.tui.components.input.context_completion import ContextCompletion
from pico_chat.ui.tui.components.menu import SelectionMenu


def make_completion(items):
    menu = SelectionMenu()
    return ContextCompletion(menu, lambda: items)


def test_lists_top_level_by_default():
    comp = make_completion(["src/", "src/a.py", "README.md"])
    comp.update("./", 2)
    assert comp.is_active
    # Top-level listing shows the full relative paths.
    assert comp.menu.items == ["src/", "src/a.py", "README.md"]


def test_drills_into_directory_with_trailing_slash():
    comp = make_completion(["src/", "src/a.py", "src/sub/", "src/sub/b.py", "README.md"])
    comp.update("./src/", 6)
    assert comp.is_active
    # Only the immediate children of src/ are shown, prefix stripped.
    assert comp.menu.items == ["a.py", "sub/"]


def test_accept_selection_preserves_directory_prefix():
    comp = make_completion(["src/", "src/a.py", "src/sub/", "src/sub/b.py"])
    comp.update("./src/", 6)
    # Select "sub/" (index 1 in the drilled listing).
    comp.menu.selected_index = 1
    new_text, new_cursor = comp.accept_selection("./src/", 6)
    assert new_text == "./src/sub/"
    assert new_cursor == len("./src/sub/")


def test_accept_selection_top_level():
    comp = make_completion(["src/", "README.md"])
    comp.update("./", 2)
    comp.menu.selected_index = 1  # README.md
    new_text, new_cursor = comp.accept_selection("./", 2)
    assert new_text == "./README.md"
    assert new_cursor == len("./README.md")


def test_no_children_returns_top_level():
    comp = make_completion(["src/", "README.md"])
    # "nonexistent/" has no children under the listing.
    comp.update("./nonexistent/", 14)
    # Falls back to the top-level listing.
    assert comp.menu.items == ["src/", "README.md"]