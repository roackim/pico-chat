# Testing

Tests live in `test/`. Run with pytest from the project root.

---

## Running Tests

```bash
pytest test/
# or a specific file:
pytest test/test_permissions.py
```

## Shared Fixtures

`test/conftest.py` provides reusable test infrastructure:
- `NoopDebugStream`, `FakeServer`, `StubReadTool`, `StubAgent` — stub classes
- `harness_stub(tmp_path, stub_read_tool)` — fixture for tool-execution tests (bypasses `Harness.__init__`)
- `harness_stub_compaction()` — fixture with `FakeServer` for compaction tests
- `run_harness_tool_call(harness, tool_call)` — runs a tool call through `_execute_tool_calls`
- `make_chunk_stream(*chunks)` — async generator yielding given chunks

## Test Coverage

| File | What It Tests |
|------|--------------|
| `test_permissions.py` | Read/write/patch/run permission enforcement (inside/outside repo) |
| `test_dangerous_patterns.py` | Escalation from ALLOW→ASK for dangerous shell patterns |
| `test_benign_dangerous_commands.py` | Safe usages of commands that superficially match dangerous patterns |
| `test_permission_chain_policy.py` | Quote-aware chain operator detection and chain_policy enforcement |
| `test_containerization.py` | bwrap (bubblewrap) sandboxing and command isolation |
| `test_buffer.py` | Buffer/SubBuffer rendering (cell operations, ANSI clipping, text writing) |
| `test_compaction.py` | Conversation history compaction (summarization via LLM) |
| `test_context_builder.py` | Git repo detection, file tree building guardrails |
| `test_patch_parser.py` | `parse_patch` format validation, `apply_patch` 3-mode cascade (exact, whitespace, indentation) |
| `test_token_estimation.py` | Heuristic token counting (code ratio, language vs. prose) |
| `test_token_estimation_samples.py` | Regression tests on real code/text samples |
| `test_ui_permission_submit.py` | Input blocked while awaiting permission prompt |

## Notes on `test_containerization.py`

Requires `bwrap` (bubblewrap) to be installed. Tests are skipped if not available.

## Notes on `test_compaction.py`

Requires a running LLM server (or the `FakeServer` fixture from `conftest.py`). May be skipped in CI without a backend.

## Adding Tests

- Place new test files in `test/`
- Mirror the module being tested: `harness/security.py` → `test/test_security.py` (use existing naming convention)
- Use pytest fixtures from `conftest.py` where possible; avoid global state
- Prefer shared stubs (`NoopDebugStream`, `StubReadTool`) over inline duplicates
