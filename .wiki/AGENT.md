# Pico-Chat Wiki — Agent Guide

This document tells AI agents and humans how to operate and maintain this wiki.

---

## Wiki Structure

```
.wiki/
  AGENT.md                  ← This file. Maintenance contract.
  notes/
    architecture.md         ← High-level system design and data flow
    config.md               ← Configuration reference (config.toml)
    reasoning-traces.md     ← Reasoning trace handling (thinking tags, reasoning_content)
    security.md             ← Security model, dangerous patterns, sandboxing
    subagents.md            ← Subagent lifecycle, permissions, depth/timeout/context limits
    testing.md              ← Test suite overview and how to run tests
    tools-and-permissions.md← Tool system, permission policies, wrappers
    ui.md                   ← TUI architecture and component model
  tree/
    README.md               ← Root package overview
    harness.md              ← pico_chat/harness/ — LLM agent core
    ui.md                   ← pico_chat/ui/ — Chat UI layer
    ui-tui.md               ← pico_chat/ui/tui/ — Rendering engine
    ui-tui-components.md    ← pico_chat/ui/tui/components/ — UI widgets
    test.md                 ← test/ — Test suite
```

### `notes/`
Conceptual documentation. Each file covers a cross-cutting concern.
**Update when**: an architectural decision changes, a new subsystem is added, or security/permission logic is modified.

### `tree/`
File-by-file reference, mirroring the source tree. Each `.md` corresponds to a directory.
Each entry contains: purpose, key classes/functions, dependencies.
**Update when**: files are added, removed, renamed, or their public API changes.

---

## Staleness Warning

This wiki is maintained opportunistically — it is updated when code changes, not on a fixed schedule. **Treat all content as potentially outdated.** When in doubt, read the source file directly and verify against what's here.

Signs a page may be stale:
- A class or function name in the wiki doesn't exist in the source
- A file listed in a tree page has been renamed or removed
- A workflow described in `notes/` doesn't match actual code behaviour

If you find stale content, correct it, and warn the user rather than working around it.

---

## Maintenance Rules

1. **Keep it factual** — no aspirational "will be" statements. Document what exists now.
2. **One responsibility per note** — if a note is growing to cover two concerns, split it.
3. **Tree entries are stubs by default** — a one-liner is fine. Detail only what's non-obvious.
4. **Don't duplicate** — if notes/architecture.md covers a flow, tree entries should link to it instead of repeating it.
5. **Update atomically** — when renaming a file, update both the tree entry and any notes that reference it in the same operation.

---

## How to Update the Wiki

When source files change, update the wiki as follows:
1. Identify which source files changed
2. Locate the corresponding `.wiki/tree/` page(s) using the structure above
3. Update the page content to reflect current reality
4. Check whether any `notes/` page is affected and update it if so

Checklist:
- Does the changed file have a corresponding `.wiki/tree/` entry?
- Did any class/function names, signatures, or responsibilities change?
- Did the change affect a cross-cutting concern covered in `notes/`?
- Are all internal wiki links still valid?

---

## Skill Reference

The `wiki` skill is defined at `.github/skills/wiki/SKILL.md`. Load it for the full update procedure and general rules.
