# test/ — Test Suite

All tests use pytest. See [notes/testing.md](../notes/testing.md) for run instructions and coverage details.

---

## Files

| File | Module Under Test | What It Covers |
|------|-------------------|----------------|
| `test_permissions.py` | `harness/tool_permissions.py`, `tools.py` | Read/write/patch/run policies inside and outside the repo root |
| `test_dangerous_patterns.py` | `harness/security.py` | Escalation from ALLOW→ASK for dangerous shell patterns |
| `test_benign_dangerous_commands.py` | `harness/security.py` | Safe usages that superficially match dangerous patterns |
| `test_permission_chain_policy.py` | `harness/security.py`, `tool_permissions.py` | Chain operator detection and `chain_policy` enforcement |
| `test_containerization.py` | `harness/tools.py` | bwrap sandboxing (skipped if bubblewrap not installed) |
| `test_buffer.py` | `ui/tui/buffer.py` | Cell operations, ANSI-aware text writing, SubBuffer clipping |
| `test_compaction.py` | `harness/harness.py` | Conversation history summarization (requires LLM backend) |
| `test_context_builder.py` | `harness/context_builder.py` | Git root detection, file tree building guardrails |
| `test_memory_visibility.py` | `harness/memory_tools.py`, `harness.py` | Memory isolation — old turn memories excluded from new context |
| `test_token_estimation.py` | `harness/token_estimation.py` | Heuristic token count accuracy (code ratio, prose vs. code) |
| `test_token_estimation_samples.py` | `harness/token_estimation.py` | Regression tests on real code/text samples |
| `test_ui_permission_submit.py` | `ui/app.py`, `ui/tui/components/input/` | Input blocked during active permission prompt |
| `test_subagents.py` | `harness/tool_wrappers.py`, `harness/harness.py`, `harness/tool_permissions.py` | Depth limit, timeout, context cap, scaffolder profile, background queuing, wait_for_subagents, harness abort |
