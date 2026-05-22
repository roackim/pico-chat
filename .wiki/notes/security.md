# Security

Pico runs shell commands and reads/writes files on behalf of an LLM agent. The security layer prevents accidental or malicious escalation.

---

## Threat Model

- The LLM may generate tool calls that modify or delete files outside the project root
- Shell commands may contain dangerous operators (pipes, `&&`, `;`) or escalation patterns (`find -exec`, `awk system()`, `sed /e`)
- Chained commands can smuggle privileged operations inside benign-looking calls

## SecurityChecker (`security.py`)

`SecurityChecker.check_command(cmd)` evaluates a shell command before execution:
1. Parses operator structure — detects `;`, `&&`, `||`, `|` chains
2. Matches against known dangerous pattern list (regex-based)
3. Returns a `CommandCheck` result: `ALLOW`, `ASK`, or `DENY`

Dangerous patterns include (non-exhaustive):
- `find -exec` / `find -execdir`
- `awk` with `system()` or `|` pipe
- `sed` with `/e` flag (execute)
- `eval`, `exec`, backtick substitution in specific contexts
- Commands writing outside the repo root

## ToolPermissionsProfile (`tool_permissions.py`)

Defines per-tool policies: `ALLOW` / `ASK` / `DENY`.

- `ASK` — the UI pauses and shows a permission prompt to the user before executing
- `ALLOW` — executes without prompting
- `DENY` — always blocked, no prompt

Dangerous pattern detection can **escalate** an `ALLOW` policy to `ASK` (never downgrades `DENY`).

## Chain Policy

`chain_policy` in the permissions profile controls how chained commands (`&&`, `||`, `;`, `|`) are handled. Behavior depends on the operators present and the policy for each segment.

## Sandboxing (`test_containerization.py`)

Commands can be sandboxed with `bwrap` (bubblewrap). Tests verify isolation behavior. This is optional and depends on bubblewrap being available on the system.

## Path Restrictions

File read/write tools validate paths against the repo root. Operations outside the working directory are blocked or escalated to `ASK` depending on policy.

## Tests

| Test | Coverage |
|------|----------|
| `test_permissions.py` | Read/write/patch/run policies inside/outside repo |
| `test_dangerous_patterns.py` | Escalation from ALLOW→ASK for dangerous patterns |
| `test_benign_dangerous_commands.py` | Safe usages of potentially dangerous commands |
| `test_permission_chain_policy.py` | Chain operator detection and chain_policy enforcement |
| `test_containerization.py` | bwrap sandboxing isolation |
