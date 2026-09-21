# pico

**A terminal AI assistant for local and cloud LLMs** — interactive TUI chat with tool use, file access, and sandboxed command execution.

---

## Requirements

- Python ≥ 3.10
- A running LLM endpoint: [llama.cpp](https://github.com/ggerganov/llama.cpp), [Ollama](https://ollama.com) locally, or an [OpenRouter](https://openrouter.ai) API key for cloud models

---

## Installation

```bash
pipx install git+https://github.com/yourusername/pico-chat.git
```

Or from a local clone:

```bash
pipx install .
```

Then run:

```bash
pico
```

---

## Getting Started

On first launch, pico starts with no server configured. Add one using the `/server` command:

**Local llama.cpp server:**
```
/server add llamacpp http://localhost:8080 my-local
/model list
/model <model>
```

**Ollama (local models):**
```
/server add ollama http://localhost:11434 my-ollama
/model list
/model llama3.1:8b
```

**OpenRouter (cloud models):**
```bash
export OPENROUTER_API_KEY=sk-or-...
```
```
/server add openrouter anthropic/claude-3.5-sonnet my-claude
/model anthropic/claude-3.5-sonnet
```

Server definitions are saved to `~/.config/pico-chat/servers.toml` and persist between sessions. Selecting a model with `/model` automatically switches to the server that serves it.

---

## Commands

| Command | Description |
|---------|-------------|
| `/help` | List all available commands |
| `/config [section]` | Edit a config section (`ui`, `context`, `subagents`, `debug`, `styles`, `servers`) and reload |
| `/edit <file>` | Open a file in `$EDITOR` |
| `/reload` | Reload config files and `roles/` from disk |
| `/status` | Show server, model, context usage, and memory |
| `/server` | Manage servers (list/use/edit/info/remove/diagnose) |
| `/model` | Open a modal model picker (also `/model list`, `/model <id>`) |
| `/tools` | Show available agent tools and their permission levels |
| `/roles` | Select and inspect roles (`roles/<name>.toml`) |
| `/compact` | Summarize conversation history to free context space |
| `/clear` | Clear the conversation history |
| `/stop` | Stop the current generation |
| `/set` | Set runtime parameters (e.g. `/set fps 60`) |
| `/get` | Get current runtime parameters |
| `/debug` | Debug utilities (toggle panel, copy context, show system prompt) |
| `/exit` | Quit the application |

### Server Management

Servers are defined in `servers.toml`; edit them with `/config servers` (or
`/server edit`) and the config is reloaded when the editor exits.

```
/server list
/server use <name>
/server edit          # opens servers.toml in $EDITOR
/server info <name>
/server remove <name>
/server diagnose <name>
/model list
/model <model>
/model <server>:<model>
```

Examples (`servers.toml`):
```toml
[servers.local]
type = "llamacpp"
base_url = "http://localhost:8080/v1"

[servers.ds]
type = "openrouter"
api_key_env = "OPENROUTER_API_KEY"
enabled_models = ["deepseek/deepseek-v4-flash"]
```
Then:
```
/server use local
/model list
/model llama3.1:8b
```

---

## Using the Interface

### Sending messages

- **Enter** — send message
- **Alt+Enter** or **Ctrl+Enter** — insert a newline (multi-line input)
- **Ctrl+W** / **Ctrl+Backspace** — delete word backward
- **Ctrl+Left / Right** — move cursor by word

### Completions

- Type `@` to open a fuzzy file picker — inserts a file path into your message
- Type `/` to autocomplete commands

### Navigating history

- **↑ / ↓** arrow keys — focus messages in the history
- **Mouse click** — focus a message directly
- When a message is focused, a footer appears with available actions:
  - **`c`** — copy message content to clipboard
  - **`r`** — retry the response (assistant messages only)

---

## Tool Use & Permissions

The agent has access to tools for reading/writing files, applying patches, and running shell commands. Each tool has a configurable permission level:

- **`allow`** — runs automatically without asking
- **`ask`** — prompts you before executing
- **`deny`** — never allowed

When the agent requests a tool that requires your approval, a prompt appears:

```
> run
cmd: pytest tests/
[allow] [deny]
```

You can approve or deny with mouse click or keyboard.

Use `/tools` to see the current permission level for each tool. The full policy — per-tool settings and per-command allow/ask/deny lists — lives in the active role file (`roles/<name>.toml`); edit it with `/roles edit <name>`.

---

## Agent Memory

The agent can remember things across conversation turns using `memorize` and `forget` tools. Memories are stored in-session and shown in `/status`. They are used to keep track of context that would otherwise fall out of the context window (e.g. project conventions, user preferences, task progress).

---

## Live Metrics

During generation, pico displays:
- **Speed** (tokens/s)
- **Context usage** (tokens used vs. context window size, color-coded by pressure)

Use `/status` at any time to see the full picture.

---

## Configuration Files

Hand-edited configuration lives in `~/.config/pico-chat/`, split into small
single-concern files:

- `ui.toml` — theme, padding, metrics, fps (flat keys).
- `context.toml` — context building (flat keys).
- `subagents.toml` — subagent limits (flat keys).
- `debug.toml` — debug logging (flat keys).
- `styles.toml` — `[markdown_styles.*]` / `[syntax_highlight.*]` overrides.
- `servers.toml` — one `[servers.<name>]` table per server.
- `roles/<name>.toml` — one file per conversation role (tools, permissions,
  prompts). The file name is the role name; `_example.toml` is a commented
  starting point.
- `state.toml` — disposable runtime state (last server/model, discovery
  catalog). Safe to delete.

Missing files are created from fully commented templates (the `servers.toml`
template includes example `llamacpp`, `ollama`, `openrouter` and `openai`
blocks). Edit them with `/config <section>` or `/edit <path>`, and roles with
`/roles edit <name>`. Configuration is read at startup and only re-applied when
you run `/reload` or restart. The loader validates each file and reports unknown
keys, wrong types, and unparsable TOML (`<file>: ...`); invalid entries fall
back to defaults while the rest of the file still applies.

```toml
# ui.toml
theme = "terminal"

# context.toml
format = "tree"
max_files = 500

# subagents.toml
max_depth = 1

# servers.toml
[servers.local]
type = "llamacpp"
base_url = "http://localhost:8080/v1"
```

```toml
# roles/architect.toml
description = "Design and review with minimal edits"
prompt = "Focus on architecture; prefer small, reversible changes."

[tools.read]
enabled = true
permission = "allow"

[tools.write]
enabled = true
permission = "ask"
```
