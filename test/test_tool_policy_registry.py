from pico_chat.harness import tools as tool_wrappers
from pico_chat.harness.permissions import PermissionGate
from pico_chat.harness.roles import default_role


def test_registered_tool_metadata_covers_role_policy_entries():
    specs = tool_wrappers.registered_tool_specs()
    role = default_role()

    assert set(role.tools) == set(specs)
    assert specs["read"].profile_kind == "file"
    assert specs["run_command"].profile_kind == "run"


def test_new_registered_tool_gets_default_role_policy(monkeypatch):
    specs = tool_wrappers.registered_tool_specs()
    specs["future_tool"] = tool_wrappers.ToolPolicySpec(
        "simple", "deny", {"scope": "workspace"}
    )
    monkeypatch.setattr(tool_wrappers, "registered_tool_specs", lambda: specs)

    role = default_role()

    assert role.tools["future_tool"].enabled is False
    assert role.tools["future_tool"].permission == "deny"
    assert role.tools["future_tool"].settings == {"scope": "workspace"}


def test_permission_gate_reads_enabled_and_simple_policies_from_role(tmp_path):
    role = default_role()
    role.tools["search_wiki"].enabled = False
    gate = PermissionGate(
        str(tmp_path),
        enabled_tools=role.enabled_tool_names(),
        role=role,
    )

    assert gate.check("search_web", {"query": "test"}) == "allow"
    assert gate.check("search_wiki", {"query": "test"}) == "deny"
    assert gate.check("subagent", {"task": "test"}) == "ask"


def test_permission_gate_reads_file_settings_from_role(tmp_path):
    role = default_role()
    role.tools["read"].settings["inside_repo"] = "deny"
    role.tools["read"].settings["outside_repo"] = "allow"
    gate = PermissionGate(
        str(tmp_path),
        enabled_tools=role.enabled_tool_names(),
        role=role,
    )

    assert gate.check("read", {"path": "inside.txt"}) == "deny"
    assert gate.check("read", {"path": str(tmp_path.parent / "outside.txt")}) == "allow"


def test_permission_gate_reads_run_settings_from_role(tmp_path):
    role = default_role()
    role.tools["run_command"].settings.update(
        {"allow": ["echo"], "ask": [], "deny": [], "others": "deny"}
    )
    gate = PermissionGate(
        str(tmp_path),
        enabled_tools=role.enabled_tool_names(),
        role=role,
    )

    assert gate.check("run_command", {"command": "echo ok"}) == "allow"
    assert gate.check("run_command", {"command": "python -V"}) == "deny"
