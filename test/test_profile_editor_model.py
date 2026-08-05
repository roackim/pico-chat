"""Unit tests for permissions profile editor state and persistence."""

from copy import deepcopy

import pytest

from pico_chat.harness import tool_permissions
from pico_chat.ui.profile_editor_model import ProfileEditorModel


@pytest.fixture
def profile_store(tmp_path, monkeypatch):
    original = deepcopy(tool_permissions.permissions)
    monkeypatch.setattr(tool_permissions, "_PROFILE_PATH", tmp_path / "profiles.toml")
    yield
    tool_permissions.apply_profile(original)


def test_create_persists_and_selects_default_profile(profile_store):
    model = ProfileEditorModel()

    created = model.create()

    assert created.name == "new-profile"
    assert model.selected_name == "new-profile"
    assert tool_permissions.load_profile("new-profile").read.inside_repo == "ask"
    assert tool_permissions.permissions.name == "new-profile"


def test_select_loads_and_applies_saved_profile(profile_store):
    model = ProfileEditorModel()
    created = model.create()
    created.read.inside_repo = "allow"
    model.update_permissions(created)

    model.select("new-profile")

    assert model.draft.read.inside_repo == "allow"
    assert tool_permissions.permissions.read.inside_repo == "allow"


def test_builtin_permissive_can_be_reselected_after_switching_profiles(profile_store):
    model = ProfileEditorModel()
    model.create()

    selected = model.select("permissive")

    assert selected.name == "permissive"
    assert selected.read.inside_repo == "allow"
    assert tool_permissions.permissions.name == "permissive"


def test_update_persists_selected_profile_immediately(profile_store):
    model = ProfileEditorModel()
    draft = model.create()
    draft.run.use_container = True

    model.update_permissions(draft)

    assert tool_permissions.load_profile("new-profile").run.use_container is True
    assert tool_permissions.permissions.run.use_container is True


def test_duplicate_uses_unique_name_and_selects_copy(profile_store):
    model = ProfileEditorModel()
    model.create()

    copy = model.duplicate()

    assert copy.name == "new-profile-copy"
    assert model.selected_name == "new-profile-copy"
    assert "new-profile-copy" in tool_permissions.list_profiles()


def test_rename_unsaved_active_profile_saves_under_new_name(profile_store):
    model = ProfileEditorModel()
    original_name = model.selected_name

    renamed = model.rename("custom")

    assert renamed.name == "custom"
    assert model.selected_name == "custom"
    assert tool_permissions.load_profile("custom").name == "custom"
    if original_name != "custom":
        assert original_name not in tool_permissions.list_profiles()


def test_remove_selected_profile_selects_remaining_profile(profile_store):
    model = ProfileEditorModel()
    model.create()
    model.duplicate()

    model.remove("new-profile-copy")

    assert model.selected_name == "new-profile"
    assert tool_permissions.list_profiles() == ["new-profile"]


def test_editing_active_permissions_does_not_mutate_permissive_template(profile_store):
    original_inside = tool_permissions.permissive.read.inside_repo
    model = ProfileEditorModel()
    draft = model.draft
    draft.read.inside_repo = "deny"

    model.update_permissions(draft)

    assert tool_permissions.permissive.read.inside_repo == original_inside == "allow"
