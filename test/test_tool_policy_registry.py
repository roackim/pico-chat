from pico_chat.harness import tool_wrappers
from pico_chat.harness.permission_gate import PermissionGate
from pico_chat.harness.roles import Role
from pico_chat.harness.tool_permissions import permissive


def test_registered_tool_metadata_covers_role_policy_entries():
    specs = tool_wrappers.registered_tool_specs()
    role = Role.from_permission_profile(permissive)

    assert set(role.tools) == set(specs)
    assert specs["read"].profile_kind == "file"
    assert specs["run_command"].profile_kind == "run"


def test_new_registered_tool_gets_default_role_policy(monkeypatch):
    specs = tool_wrappers.registered_tool_specs()
    specs["future_tool"] = tool_wrappers.ToolPolicySpec(
        "simple", "deny", {"scope": "workspace"}
    )
    monkeypatch.setattr(tool_wrappers, "registered_tool_specs", lambda: specs)

    role = Role.from_permission_profile(permissive, enabled_tools=set())

    assert role.tools["future_tool"].enabled is False
    assert role.tools["future_tool"].permission == "deny"
    assert role.tools["future_tool"].settings == {"scope": "workspace"}


def test_permission_gate_reads_enabled_and_simple_policies_from_role(tmp_path):
    role = Role.from_permission_profile(
        permissive,
        enabled_tools={"search_web", "subagent"},
    )
    gate = PermissionGate(
        str(tmp_path),
        permissions=role.to_permission_profile(),
        enabled_tools=role.enabled_tool_names(),
        role=role,
    )

    assert gate.check("search_web", {"query": "test"}) == "allow"
    assert gate.check("search_wiki", {"query": "test"}) == "deny"
    assert gate.check("subagent", {"task": "test"}) == "ask"


def test_permission_gate_reads_file_settings_from_role(tmp_path):
    role = Role.from_permission_profile(permissive)
    role.tools["read"].settings["inside_repo"] = "deny"
    role.tools["read"].settings["outside_repo"] = "allow"
    gate = PermissionGate(
        str(tmp_path),
        permissions=None,
        enabled_tools=role.enabled_tool_names(),
        role=role,
    )

    assert gate.check("read", {"path": "inside.txt"}) == "deny"
    assert gate.check("read", {"path": str(tmp_path.parent / "outside.txt")}) == "allow"


def test_permission_gate_reads_run_settings_from_role(tmp_path):
    role = Role.from_permission_profile(permissive)
    role.tools["run_command"].settings.update(
        {"allow": ["echo"], "ask": [], "deny": [], "others": "deny"}
    )
    gate = PermissionGate(
        str(tmp_path),
        permissions=None,
        enabled_tools=role.enabled_tool_names(),
        role=role,
    )

    assert gate.check("run_command", {"command": "echo ok"}) == "allow"
    assert gate.check("run_command", {"command": "python -V"}) == "deny"
