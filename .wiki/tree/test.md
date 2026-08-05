# test/ — Test Suite

All tests use pytest. See [notes/testing.md](../notes/testing.md) for run instructions and coverage details.

---

## Common Fixtures

`conftest.py` — shared test infrastructure:
- `NoopDebugStream`, `FakeServer`, `StubReadTool`, `StubAgent` — reusable stubs
- `harness_stub` / `harness_stub_compaction` — pre-built fixture harnesses (skip full __init__)
- `run_harness_tool_call()`, `make_chunk_stream()` — async test helpers

## Test Files

| File | Module Under Test | What It Covers |
|------|-------------------|----------------|
| `test_permissions.py` | `tool_permissions.py`, `tools.py`, `harness.py` | Read/write/patch/run permission enforcement |
| `test_dangerous_patterns.py` | `security.py` | Escalation from ALLOW→ASK for dangerous shell patterns |
| `test_benign_dangerous_commands.py` | `security.py` | Safe usages that match dangerous patterns on the surface |
| `test_permission_chain_policy.py` | `security.py`, `tool_permissions.py` | Quote-aware chain operator detection and chain_policy |
| `test_containerization.py` | `tools.py` | bwrap sandboxing (skipped if bubblewrap not installed) |
| `test_buffer.py` | `ui/tui/buffer.py` | Cell operations, ANSI-aware text writing, SubBuffer |
| `test_forms.py` | `ui/tui/components/form.py` | Form fields, dynamic profile-list composition, layout, and input routing |
| `test_tui_form_actions.py` | `ui/tui/components/form_popup.py`, `ui/tui/components/form.py` | Shared keyboard/mouse actions, modal submit/cancel, focus, and typed events |
| `test_profile_editor_model.py` | `ui/profile_editor_model.py` | Profile selection, immediate persistence, lifecycle operations, and isolated drafts |
| `test_basic_inputs.py` | `ui/tui/components/input/` | Line/box editors and typed keyboard metadata |
| `test_chat_message.py` | `ui/chat_message.py` | Focused compact-message layout invalidation |
| `test_compaction.py` | `harness.py` | Conversation history summarization (uses FakeServer fixture) |
| `test_context_builder.py` | `context_builder.py` | Git repo detection, file tree building guardrails |
| `test_patch_parser.py` | `patch_parser.py` | `parse_patch` format validation, `apply_patch` 3-mode cascade |
| `test_token_estimation.py` | `token_estimation.py` | Heuristic token count accuracy |
| `test_token_estimation_samples.py` | `token_estimation.py` | Regression tests on real code/text samples |
| `test_ui_permission_submit.py` | `ui/app.py` | Input blocked during active permission prompt |
| `test_layout_primitives.py` | `ui/tui/container.py` | Layout, clipping, scrolling, and typed ScrollView navigation |
| `test_tui_interactions.py` | `ui/app.py`, `ui/tui/components/` | Focus routing, tab lifecycle, debug/workspace replacement, and per-conversation state isolation |
| `test_tui_navigation.py` | `ui/tui/navigation.py`, `ui/tui/compositor.py` | Screen navigation, modal lifecycle, and compositor shutdown handling |
| `test_subagents.py` | `tool_wrappers.py`, `harness.py` | Depth limit, timeout, scaffolder profile, abort |
| `test_search.py` | `tools.py`, `tool_wrappers.py` | DuckDuckGo/Wikipedia search, rate limiting, errors |
