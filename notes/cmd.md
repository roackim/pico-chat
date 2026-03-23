Sandboxed Command Execution Design (bubblewrap-based)

Objective
Prevent any possibility of host OS compromise while allowing an LLM to execute shell commands on a user project directory. Project integrity is not guaranteed (assumed version-controlled and recoverable).

---

Architecture Overview

* All commands are executed inside a bubblewrap container
* Only the project directory is exposed to the container
* No access to host filesystem outside the project
* No network access
* No privilege inheritance
* Non-interactive execution model

Security boundary is the container, not the command allowlist.

---

Bubblewrap Configuration (Required)

Filesystem:

* --ro-bind /path/to/project /project
* No other host paths mounted
* Avoid binding /etc, /home, /proc unless strictly required

Isolation:

* --unshare-all (or at minimum: --unshare-user --unshare-pid --unshare-net --unshare-mount)

Privileges:

* --uid 65534
* --gid 65534

Environment:

* --clearenv

Temporary storage:

* --tmpfs /tmp

Networking:

* --unshare-net

---

Command Allowlist

Allowed commands:

File reading:

* cat
* head
* tail

File discovery:

* ls
* find
* tree
* file
* which

Text processing:

* grep
* awk
* sed
* cut
* sort
* uniq
* wc

Utilities:

* echo
* pwd
* basename
* dirname
* realpath
* date

File writing:

* cp
* mv
* mkdir
* touch
* ln

Removed:

* less
* more

---

Commands Requiring Special Checks

Even inside a container, certain flags or features should be explicitly restricted to reduce risk and avoid unintended behavior.

1. find

Block:

* -exec
* -ok

Optional restrictions (recommended):

* -printf (can leak structured data, low risk here)
* traversal outside /project (enforce working directory)

Rationale:

* -exec and -ok allow arbitrary command execution

---

2. awk

Block:

* system()

Block (recommended if parsing allows):

* pipe operator inside awk scripts: |
* getline from arbitrary absolute paths (optional)

Examples of risky constructs:

* system("sh")
* print "cmd" | "/bin/sh"
* getline < "/etc/passwd"

Rationale:

* awk is a full scripting language with process and file I/O

---

3. sed

Block:

* e flag (GNU sed command execution)

Example:

* sed 's/.*/id/e'

Rationale:

* enables arbitrary command execution

---

4. ln

Optional restriction:

* disallow symlinks or restrict to project-local targets

Rationale:

* symlink abuse can manipulate file access patterns

---

5. cp / mv

Optional restriction:

* prevent overwrite of critical project files (policy-dependent)

Rationale:

* project corruption (accepted risk in this model)

---

Global Input Restrictions

Flag or require confirmation for commands containing:

* |
* &
* &&
* >
* <
* ;

These indicate shell-level composition or redirection.

Note:

* These must be detected even inside quoted strings if parsing is shallow.

---

Residual Risks

1. Resource exhaustion

* Infinite loops (awk)
* Large directory traversal (find)
  Mitigation:
* execution timeout
* CPU/memory limits (cgroups or ulimit)

2. Project modification

* Files can be overwritten or deleted
  Mitigation:
* external (git, backups)

3. Sandbox misconfiguration

* Most critical failure mode
* Any unintended bind mount breaks isolation

---

Security Model Summary

* Host safety relies entirely on container isolation
* Command filtering reduces accidental misuse but is not the primary defense
* Arbitrary execution inside the container is acceptable
* No sensitive data must exist inside the container outside the project

---

Conclusion

This approach is sufficient to prevent host OS compromise under a user-driven LLM model.

Key requirement:

* Bubblewrap must be correctly and strictly configured

Command-level restrictions provide additional safety but are secondary to isolation.
