# pico_chat

**Local AI assistant in the command line** – A terminal-based agent for self-hosted LLMs with tool execution, memory management, and project context awareness.

---

## Overview

`pico_chat` provides an interactive TUI (terminal user interface) for running a local LLM agent that can:
- Execute code and shell commands in your workspace
- Read/write/patch files with permission controls
- Manage conversation memory across sessions
- Display project context (file tree respecting .gitignore)
- Stream answers and reasoning content from models
- Show live generation metrics (tokens/s, TTFT, duration)

---

## Installation

```bash
# Using Pixi (recommended)
pixi install
pixi run app

# Or with pip
pip install -e .
python pico_chat/main.py
```

**Requirements:**
- Python ≥3.10
- A compatible LLM server (llama.cpp, OpenRouter, or OpenAI-compatible API)

---

## Configuration

### Server Setup

Configure your LLM server in `pico_chat/harness/llm_server_config.py`:

```python
LLMServerConfig(
    type="llamacpp",  # or "openrouter", "openai"
    base_url="http://localhost:8080/v1",
    api_key="your-key-here",
    model="your-model-name",
    max_context=32768,
    retry_attempts=3,
    timeout=5.0
)
```

**Server types:**
- `llamacpp`: llama.cpp server with `/props` endpoint for context window detection
- `openrouter`: OpenRouter API with model metadata lookup
- `openai`: OpenAI-compatible APIs

### Tool Permissions

Configure tool access in `pico_chat/harness/tool_permissions.py`:

```python
permissions.set_read_permission("ask")    # Ask before reading files
permissions.set_write_permission("deny")  # Deny writes by default
permissions.set_patch_permission("allow") # Allow patches inside repo
permissions.set_run_permission("ask")     # Ask before running commands
```

Permissions can be `allow`, `ask` (prompt user), or `deny`.

---

## Usage

### Starting the Application

```bash
pixi run app
# or
python pico_chat/main.py
```

### Commands

| Command | Description |
|---------|-------------|
| `/help` | List available commands |
| `/clear` | Clear conversation history |
| `/exit` | Quit the application |
| `/status` | Show server status, model, context usage |
| `/stop` | Stop current generation |
| `/debug panel` | Toggle debug console visibility |
| `/debug get_context` | Copy LLM context to clipboard |
| `/debug get_memory` | Copy memory state to clipboard |

### Input Features

- **@file completion**: Type `@` followed by filename prefix for fuzzy file search
- **Command completion**: Type `/` followed by command prefix
- **Multi-line input**: Press Enter to add lines, Ctrl+Enter to submit
- **Message focus**: Navigate history with arrow keys, select messages with mouse or up/down arrows
- **Edit messages**: Focus a message and press `e` to edit (deletes subsequent messages)
- **Copy messages**: Focus a message and press `c` to copy content

### Tool Execution Flow

When the agent wants to use a tool:
1. Permission check (auto-allow, auto-deny, or prompt user)
2. User approval/denial (if prompted)
3. Tool execution in workspace context
4. Results sent back to LLM for continuation

Permission prompts show:
```
> run
cmd: ls -la /tmp
[allow] [deny]  (or auto-approved/denied if configured)
```

---

## Features

### Memory System

The agent can use `memorize` and `forget` tools to persist important information:

```python
# Memorize a fact
memorize(key="user_preference", content="User prefers German responses")

# Recall later (via memory tool access)
# Forget obsolete info
forget(key="temp_session_data")
```

Memory items include metadata: token size, last updated timestamp.

### Context Building

The agent receives a project context showing your file structure:

```
Project Root: /home/user/project
Files (tree format, filtered by .gitignore):
├── src/
│   ├── main.py
│   └── utils.py
├── tests/
│   └── test_main.py
└── README.md
```

Context builder respects `.gitignore` and can use tree (token-efficient) or flat format.

### Thinking Tag Support

Supports multiple reasoning tag formats:
- `<think>` / `</think>` (DeepSeek R1 style)
- `<thinking>` / `</thinking>` (RAG-based models)

Thinking content is displayed separately from regular responses.

### Generation Metrics

Live metrics displayed in the UI:
- **Tokens/s**: Current generation speed
- **TTFT**: Time to first token (ms)
- **Duration**: Total generation time
- **Context usage**: Token consumption vs. context window

---

## Architecture

```
pico_chat/
├── harness/           # Core agent logic
│   ├── harness.py    # Main Harness class (chat loop, tools, memory)
│   ├── tools.py      # Minimal toolset (read, write, patch, run)
│   ├── llm_server.py # Server abstraction (llamacpp, OpenRouter, OpenAI)
│   ├── security.py   # Command permission checker
│   ├── tool_permissions.py  # Permission profiles
│   ├── context_builder.py # Project context generation
│   ├── chunks.py     # Stream chunk types for UI communication
│   └── memory_tools.py # Memory management tools
├── ui/               # Terminal user interface
│   ├── app.py        # Main TUI application (chatTUI class)
│   ├── commands.py   # Command definitions and handlers
│   ├── chat_message.py # Message component with focus actions
│   ├── chat_history_panel.py  # Scrollable history display
│   └── tui/          # Low-level TUI components
├── pico_cfg.py       # Configuration management
└── main.py           # Entry point
```

### Key Components

**Harness**: Manages the agent's state machine:
- User input → LLM → [tool calls → execution → LLM]* → response
- Tracks conversation history, memory, and active tool operations
- Provides context estimation and message management

**TUI Application**: Renders the interface using a compositor pattern:
- Chat history panel with focused message support
- Dynamic input field with command/fuzzy completion
- Debug console for low-level logging
- Keyboard and mouse interaction handling

---

## Security

### Permission System

All tool operations go through permission checks:
- File operations check if path is inside workspace (`.gitignore` respected)
- Shell commands are validated against allowed patterns
- "Ask" permissions trigger UI prompts with allow/deny buttons

### Workspace Isolation

Tools operate relative to the current working directory. Cross-workspace operations require explicit permission grants.

---

## Development

### Running Tests

```bash
pixi run tests
# or
pytest tests/
```

### Adding Tools

1. Implement tool logic in `pico_chat/harness/tools.py`
2. Add schema to `get_schema()` method (from `tool_wrappers.py`)
3. Register in `create_minimal_tools()` function
4. Configure permissions in `tool_permissions.py`

Example tool:

```python
def my_tool(args: dict) -> str:
    """Description of what this tool does."""
    # Implementation here
    return "Result string"

# Schema
{
    "name": "my_tool",
    "description": "My custom tool",
    "parameters": {
        "type": "object",
        "properties": {
            "arg1": {"type": "string", "description": "First argument"}
        },
        "required": ["arg1"]
    }
}
```

### Debugging

Enable debug console: `/debug panel`

View raw logs in `pico_chat.log` (configurable via `pico_cfg.py`).

---

## Known Issues & Roadmap

See `TODO.todo` for the complete list of pending features and bugs.

**Upcoming:**
- Git integration for session management
- Containerization (Bubblewrap/Docker) for tool security
- Markdown rendering improvements
- Multiple conversation threads
- Plugin system for custom tools/prompts

**Current limitations:**
- No persistent config file support (uses defaults)
- Clipboard operations require `xclip`, `xsel`, or `wl-copy`
- Context window detection depends on server support

---

## License

MIT License

---

*For questions, issues, or contributions, open a GitHub issue or consult the source code directly.*
