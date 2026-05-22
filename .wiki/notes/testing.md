# Testing

Tests live in `test/`. Run with pytest from the project root.

---

## Running Tests

```bash
pytest test/
# or a specific file:
pytest test/test_permissions.py
```

## Test Coverage

| File | What It Tests |
|------|--------------|
| `test_permissions.py` | Read/write/patch/run permission enforcement (inside/outside repo) |
| `test_dangerous_patterns.py` | Escalation from ALLOW→ASK for dangerous shell patterns |
| `test_benign_dangerous_commands.py` | Safe usages of commands that superficially match dangerous patterns |
| `test_permission_chain_policy.py` | Chain operator detection (`;`, `&&`, `\|\|`, `\|`) and chain_policy enforcement |
| `test_containerization.py` | bwrap (bubblewrap) sandboxing and command isolation |
| `test_security.py` | General security checker behavior |
| `test_buffer.py` | `Buffer`/`SubBuffer` rendering (cell operations, ANSI clipping, text writing) |
| `test_compaction.py` | Conversation history compaction (summarization via LLM) |
| `test_context_builder.py` | Git repo detection, file tree building guardrails |
| `test_memory_visibility.py` | Memory isolation — old turn memories not visible to new context |
| `test_token_estimation.py` | Heuristic token counting (code ratio, language vs. prose) |
| `test_token_estimation_samples.py` | Regression tests on real code/text samples |
| `test_ui_permission_submit.py` | Input blocked while awaiting permission prompt |

## Notes on `test_containerization.py`

Requires `bwrap` (bubblewrap) to be installed. Tests are skipped if not available.

## Notes on `test_compaction.py`

Requires a running LLM server (or a mock). May be skipped in CI without a backend.

## Adding Tests

- Place new test files in `test/`
- Mirror the module being tested: `harness/security.py` → `test/test_security.py` (use existing naming convention)
- Use pytest fixtures; avoid global state
