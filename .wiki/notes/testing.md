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
| `test_permissions.py` | Gate decisions, prompt text, ask/deny/allow harness flow |
| `test_roles.py` | Role model, files, seeding, validation |
| `test_buffer.py` | Buffer/SubBuffer rendering (cell operations, ANSI clipping, text writing) |
| `test_compaction.py` | Conversation history compaction (summarization via LLM) |
| `test_context_builder.py` | Git repo detection, file tree building guardrails |
| `test_patch_parser.py` | `parse_patch` format validation, `apply_patch` 3-mode cascade (exact, whitespace, indentation) |
| `test_ui_permission_submit.py` | Input blocked while awaiting permission prompt |
| `test_ollama_server.py` | Ollama backend adapter: `/api/tags` model discovery, context-window parsing, native chat response adaptation |

## Notes on `test_compaction.py`

Requires a running LLM server (or the `FakeServer` fixture from `conftest.py`). May be skipped in CI without a backend.

## Adding Tests

- Place new test files in `test/`
- Mirror the module being tested: `harness/permissions.py` → `test/test_permissions.py` (use existing naming convention)
- Use pytest fixtures from `conftest.py` where possible; avoid global state
- Prefer shared stubs (`NoopDebugStream`, `StubReadTool`) over inline duplicates
