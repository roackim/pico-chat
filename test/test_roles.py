"""Tests for conversation roles and their permission integration."""

from pico_chat.harness.permission_gate import PermissionGate
from pico_chat.harness.roles import (
    Role,
    ToolPolicy,
    builtin_roles,
    delete_role,
    duplicate_role,
    load_role,
    list_roles,
    rename_role,
    save_role,
)
import pico_chat.harness.roles as roles_module
from pico_chat.ui.role_editor_model import RoleEditorModel


def test_reviewer_role_combines_tools_permissions_and_prompt():
    reviewer = builtin_roles()["reviewer"]

    assert reviewer.enabled_tool_names() == {
        "read", "search_web", "search_wiki", "subagent", "wait_for_subagents",
    }
    assert reviewer.prompt
    assert reviewer.to_permission_profile().write.inside_repo == "deny"


def test_disabled_tool_is_denied_before_permission_prompt():
    role = Role(
        name="read-only",
        tools={"read": ToolPolicy(enabled=True, permission="allow")},
    )
    gate = PermissionGate(
        ".",
        permissions=role.to_permission_profile(),
        enabled_tools=role.enabled_tool_names(),
    )

    assert gate.check("read", {"path": "README.md"}) == "allow"
    assert gate.check("write", {"path": "README.md"}) == "deny"


def test_saved_role_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(roles_module, "_ROLE_PATH", tmp_path / "roles.toml")
    role = Role(
        name="custom",
        description="A focused role",
        prompt="Only inspect the workspace.",
        tools={"read": ToolPolicy(True, "allow", {"inside_repo": "allow"})},
    )

    save_role(role)
    loaded = load_role("custom")

    assert loaded.description == role.description
    assert loaded.prompt == role.prompt
    assert loaded.tools["read"].settings["inside_repo"] == "allow"


def test_role_lifecycle_keeps_builtin_rename_protection(tmp_path, monkeypatch):
    monkeypatch.setattr(roles_module, "_ROLE_PATH", tmp_path / "roles.toml")

    copy = duplicate_role("reviewer", "reviewer-custom")
    assert copy.name == "reviewer-custom"
    assert load_role("reviewer-custom").prompt == builtin_roles()["reviewer"].prompt

    rename_role("reviewer-custom", "reviewer-renamed")
    assert load_role("reviewer-renamed").name == "reviewer-renamed"
    delete_role("reviewer-renamed")

    try:
        rename_role("reviewer", "other")
    except ValueError as exc:
        assert "Built-in" in str(exc)
    else:
        raise AssertionError("built-in role was renamed")

    delete_role("reviewer")
    assert "reviewer" not in list_roles()


def test_role_lifecycle_keeps_one_role(tmp_path, monkeypatch):
    monkeypatch.setattr(roles_module, "_ROLE_PATH", tmp_path / "roles.toml")

    delete_role("reviewer")
    delete_role("researcher")
    try:
        delete_role("default")
    except ValueError as exc:
        assert "At least one role" in str(exc)
    else:
        raise AssertionError("last role was deleted")


def test_editing_builtin_role_saves_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(roles_module, "_ROLE_PATH", tmp_path / "roles.toml")
    editor = RoleEditorModel("reviewer")
    edited = editor.draft
    edited.description = "Custom review policy"

    updated = editor.update(edited)

    assert updated.name == "reviewer"
    assert load_role("reviewer").description == "Custom review policy"
