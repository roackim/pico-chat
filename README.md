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
/server use my-local
```

**OpenRouter (cloud models):**
```bash
export OPENROUTER_API_KEY=sk-or-...
```
```
/server add openrouter anthropic/claude-3.5-sonnet my-claude
/server use my-claude
```

Server configurations are saved to `~/.config/pico-chat/config.toml` and persist between sessions.

---

## Commands

| Command | Description |
|---------|-------------|
| `/help` | List all available commands |
| `/status` | Show server, model, context usage, and memory |
| `/server` | Manage server configurations (see below) |
| `/model` | Discover or select a model on the active endpoint |
| `/tools` | Show available agent tools and their permission levels |
| `/permissions` | Show full permission configuration |
| `/compact` | Summarize conversation history to free context space |
| `/clear` | Clear the conversation history |
| `/stop` | Stop the current generation |
| `/set` | Set runtime parameters (e.g. `/set fps 60`) |
| `/get` | Get current runtime parameters |
| `/debug` | Debug utilities (toggle panel, copy context, show system prompt) |
| `/exit` | Quit the application |

### Server Management

```
/server add openrouter <model-id> [name] [provider]
/server add llamacpp <url> [name]
/server list
/server use <name>
/server remove <name>
/model list
/model use <model>
```

Examples:
```
/server add openrouter deepseek/deepseek-v4-flash
/server add llamacpp http://localhost:8080 local
/server list
/server use deepseek-v4-flash
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
  - **`e`** — edit the message (user messages only; removes everything after it)
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

Use `/tools` to see the current permission level for each tool, and `/permissions` for the full breakdown including per-command allow/ask/deny lists.

### Sandboxing

Shell commands can be run inside a [Bubblewrap](https://github.com/containers/bubblewrap) sandbox for extra isolation. This is configurable via the permission profile.

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

## Configuration File

Settings are stored at `~/.config/pico-chat/config.toml`. It is managed automatically by the `/server` commands, but you can edit it manually if needed. The file includes server definitions and UI/behavior settings.
