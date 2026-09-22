# Pico vs. mini-SWE-agent — design confrontation

A review of `pico-chat` against the design principles of
[`mini-swe-agent`](./tmp/mini-swe-agent) (v2.4.6), with concrete change
recommendations. The goal is not to copy mini, but to separate the principles
that transfer to an interactive daily-driver TUI from those that only apply to
a bash-only benchmark harness.

Mini's own caveat is the framing for everything below:

> Its strength is benchmark performance with a strong model in a bash-only
> setting. For interactive daily-driver use it's deliberately minimal — no
> persistent shell state, no fine-grained file tools, single-action-per-step.
> "Learn from it" works best if you adopt the architecture, rather than
> literally dropping to bash-only in a context that needs richer tooling.

---

## 1. Where pico already agrees with mini (leave alone)

| mini principle | pico today | Verdict |
|---|---|---|
| Stateless execution, no running shell session | `ShellTool.run_async` spawns a fresh `create_subprocess_shell` per call, `start_new_session=True`, whole process group killed on timeout (`pico_chat/harness/tools.py:401-461`) | **Already aligned.** Same insight, same process-group kill. |
| No project tree dumped into context | Context tree is deliberately disabled (`pico_chat/harness/system_prompt.py:53-58, 96-97`); the model explores itself | Aligned with mini, which also gives no tree. |
| OS/shell context injection | `get_context_string()` (`system_prompt.py:40-51`) | Aligned with mini's `{{system}} {{release}}` injection. |
| Centralized tool schemas | Single `@tool` registry (`tools.py:589-687`) | Clean; arguably better than mini's hardcoded `BASH_TOOL`. |
| Tools restricted / permissions | Roles + `PermissionGate` | Justified for interactive use; keep. |

---

## 2. Where pico diverges — and what to change

### 2.1 Control flow uses two parallel message lists (highest priority)

Mini keeps exactly one list: `self.messages`. The trajectory *is* the messages
passed to the model, and `serialize()` just dumps them.

Pico maintains `self.history` **and** a local `messages` list built by
`_build_messages`, appending every assistant/tool message to both
(`pico_chat/harness/harness.py:1118-1133`, `914-944`). History carries an extra
`"id"` key that the API copy must strip. This duplication is a latent bug class:
`tool_call_id` mismatches, compaction slicing (`_get_effective_history`), role
change notices, and the `tool_calls` normalization done differently in each copy.

**Change:** make `history` the single source of truth and derive the API payload
in one function (strip `id`, drop messages shadowed by a compaction marker).
One list, one serializer.

**Effort:** small. **Value:** high (eliminates a whole bug class).

### 2.2 Prompt engineering lives in Python, not config (highest leverage)

Mini's core advantage: system / instance / observation / format-error templates
are Jinja strings in YAML — tunable without touching code. Most benchmark
performance lives in those strings.

Pico hardcodes `BASE_PROMPT` in `system_prompt.py:4-26`, and tool
error/observation text in Python. Role prompts are config
(`roles/<name>.toml`), but only that small piece is data.

**Change:** move `BASE_PROMPT` and the context string into template files
(TOML or `.md`), rendered with a template engine, exposing per-role overrides.
This directly serves the `SIMPLIFICATION.md` north star ("config files are the
settings UI") which is currently violated for the single most important string
in the app.

**Effort:** small-medium. **Value:** high (enables A/B + role-level tuning).

### 2.3 The base prompt is long, behavioral, and partly self-contradictory

19 rules mixing identity, style, tool policy, and termination
(`system_prompt.py:4-26`). Rules such as "answer directly when simple",
"prefer reasoning and code generation over tool calls", and "break genuinely
complex tasks into steps" pull in opposite directions; rule 15 ("prefer
reasoning over code generation") is especially suspect for a coding agent.
Mini's evidence is that terse, task-anchored prompts outperform long rule lists,
which are mostly ignored and cost tokens on every turn.

**Change:** cut to a few lines of identity + policy; move workflow
("analyze → reproduce → edit → verify") into a per-task/instance message, as
mini does. Long behavioral rule lists should not be the system prompt of an
agentic loop.

**Effort:** small. **Value:** medium-high.

### 2.4 No limits, no format-error recovery, no output elision

Mini has `step_limit` / `cost_limit` / `wall_time_limit_seconds`, a bounded
`max_consecutive_format_errors`, and observation head/tail elision at 10k chars.
Pico has none of these:

- **No output cap.** `ShellTool.run` (`tools.py:334-385`) returns full
  stdout/stderr. A `find`, `cat`, or test run dumps straight into history and
  blows the context window; compaction is the only backstop.
- **No format-error repair.** Invalid tool JSON is appended as an error and the
  loop moves on (`harness.py:805-824`) — there is no re-prompt with format
  instructions and no consecutive-error circuit breaker.
- **No step / cost / wall-time cap.** Subagents have a timeout and a context
  cap (`tools.py:854-892`), but the top-level loop is unbounded and there is no
  cost accounting.

**Change:**

1. Elide tool output above a threshold (head + tail + "n narrow your command"),
   mirroring mini's `observation_template`. Near-trivial, high value.
2. Add a bounded format-error repair path (re-inject a format message, stop
   after N consecutive failures).
3. Add a step / wall-time cap, at minimum for subagents / unattended runs.

**Effort:** small (1), small (2), small-medium (3). **Value:** high.

### 2.5 Exception-driven flow vs. async-generator flow

Mini collapses terminal conditions into `InterruptAgentFlow` subclasses carrying
their own messages, so the loop is one `try/except` and extension is trivial.

Pico cannot fully adopt this (it streams to a UI), but the idea transfers:
termination (`Done`), user abort, and limits should be one typed signal rather
than scattered `break` / `return` / `yield Error` in `chat()`
(`harness.py:1147-1158`). Pico already has an event union in
`pico_chat/harness/events.py`; add a terminal control event and dispatch on it.

**Effort:** medium. **Value:** medium.

### 2.6 Bash-only is *not* the takeaway

Mini's own caveat applies directly. Pico is an interactive TUI needing
structured, permission-gated, diffable edits and a safe approval prompt. Do
**not** collapse `read` / `write` / `patch` into `run`. Keep permissions, roles,
subagents, and compaction — they are justified by pico's context, and
`SIMPLIFICATION.md` already removed the right things.

---

## 3. Priority order

| # | Change | Effort | Value |
|---|--------|--------|-------|
| 1 | Single source of truth for history (derive API payload) | S | High |
| 2 | Move system/observation/format prompts to config templates | S-M | High |
| 3 | Tool-output elision with head/tail + narrowing hint | S | High |
| 4 | Trim base prompt; move workflow to instance-level | S | M-H |
| 5 | Bounded format-error recovery + step/time cap (subagents first) | S-M | High |
| 6 | Typed termination signal in the event union | M | Medium |

## 4. Summary

Pico already got the **execution half** of mini right: stateless subprocesses,
process-group cleanup, no persistent shell. The gap is in the **agent-scaffold
half**:

- one message list instead of two,
- prompts as data instead of Python,
- bounded recovery and limits instead of an open loop.

Stop adding tools. Make the loop and the prompt minimal and data-driven.
