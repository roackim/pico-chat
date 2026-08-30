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
    # Immediate children of src/ shown as full paths, "../" at the END so it
    # is never the default highlight.
    assert comp.menu.items == ["src/a.py", "src/sub/", "../"]
    assert comp.menu.get_selected() == "src/a.py"


def test_accept_selection_preserves_directory_prefix():
    comp = make_completion(["src/", "src/a.py", "src/sub/", "src/sub/b.py"])
    comp.update("./src/", 6)
    # Select "src/sub/" (index 1 in the drilled listing, before "../").
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


def test_partial_path_stays_inside_directory():
    comp = make_completion(["src/", "src/a.py", "src/sub/", "src/sub/b.py", "README.md"])
    # Typing "./src/a" (no trailing slash) should still filter within src/.
    comp.update("./src/a", 7)
    assert comp.menu.items == ["src/a.py", "../"]


def test_accept_directory_no_double_slash():
    comp = make_completion(["src/", "src/a.py", "src/sub/", "src/sub/b.py"])
    comp.update("./src/", 6)
    comp.menu.selected_index = 1  # src/sub/
    new_text, _ = comp.accept_selection("./src/", 6)
    # accept_selection inserts the full path — no double slash.
    assert new_text == "./src/sub/"
    assert "//" not in new_text


def test_accept_nested_file_no_double_prefix():
    # Regression: ./notes/ + TAB on notes/doc.md must not become
    # ./notes/notes/doc.md.
    comp = make_completion(["notes/", "notes/doc.md", "README.md"])
    comp.update("./notes/doc", 11)
    comp.menu.selected_index = 0  # notes/doc.md
    new_text, _ = comp.accept_selection("./notes/doc", 11)
    assert new_text == "./notes/doc.md"


def test_accept_parent_navigates_up_from_single_level():
    comp = make_completion(["src/", "src/a.py", "src/sub/", "src/sub/b.py"])
    comp.update("./src/", 6)
    comp.menu.selected_index = 2  # ../ (last)
    new_text, _ = comp.accept_selection("./src/", 6)
    assert new_text == "./"


def test_accept_parent_navigates_up_from_nested():
    comp = make_completion(["src/", "src/sub/", "src/sub/b.py"])
    comp.update("./src/sub/", 10)
    comp.menu.selected_index = 1  # ../ (last)
    new_text, _ = comp.accept_selection("./src/sub/", 10)
    assert new_text == "./src/"