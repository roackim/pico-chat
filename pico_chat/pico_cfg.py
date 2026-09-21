"""Pico-Chat configuration.

R4 of the simplification plan: configuration is files, split into
hand-editable *intent* and disposable *state*.

- Intent lives in ``~/.config/pico-chat/pico.toml``; roles are one file each in
  ``~/.config/pico-chat/roles/<name>.toml``.
  It is validated; errors are collected and reported instead of being
  silently swallowed.
- Runtime state (last server, per-server model, discovery catalog) lives in
  ``~/.config/pico-chat/state.toml``. It is machine-written and disposable:
  deleting it only loses cached selections.

There are no project-local overrides. Reloading is explicit (``/reload``).
"""

from __future__ import annotations

import os
import toml
from pathlib import Path
from typing import Any, Dict, Literal, Optional

# Default markdown element styles.
# Each key is an element name; values are dicts with optional:
#   fg (hex string), bg (hex string), bold (bool), reverse (bool)
DEFAULT_MARKDOWN_STYLES: Dict[str, Dict[str, Any]] = {
    "header1":    {"fg": "#CCA700", "bold": True},
    "header2":    {"fg": "#CCA700", "bold": True},
    "header3":    {"fg": "#CCA700", "bold": True},
    "header4":    {"fg": "#CCA700", "bold": True},
    "header5":    {"fg": "#CCA700", "bold": True},
    "header6":    {"fg": "#CCA700", "bold": True},
    "bold":       {"bold": True},
    "italic":     {"reverse": True},
    "code":       {"fg": "#808080"},
    "code_block": {"fg": "#808080"},
    "quote":      {"fg": "#808080"},
    "list":       {},
    "link":       {"fg": "#569CD6"},
    "hr":         {"fg": "#808080"},
    "paragraph":  {},
}

# Default syntax highlight element styles.
# Each key is a highlight type; values are dicts with "fg" as a hex string.
DEFAULT_SYNTAX_HIGHLIGHT_STYLES: Dict[str, Dict[str, str]] = {
    "keyword":  {"fg": "#FF6464"},
    "function": {"fg": "#64DC78"},
    "string":   {"fg": "#DCC850"},
    "comment":  {"fg": "#808080"},
    "plain":    {"fg": "#DCDCDC"},
}

CONFIG_DIR_ENV = "PICO_CONFIG_DIR"
CONFIG_FILENAME = "pico.toml"
ROLES_DIRNAME = "roles"
ROLE_EXAMPLE_FILENAME = "_example.toml"
STATE_FILENAME = "state.toml"


def get_config_dir() -> Path:
    """Directory holding the hand-editable config and disposable state."""
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "pico-chat"


def get_config_path() -> Path:
    """Path to the hand-edited intent file."""
    return get_config_dir() / CONFIG_FILENAME


def get_roles_dir() -> Path:
    """Directory of one-file-per-role definitions."""
    return get_config_dir() / ROLES_DIRNAME


def get_role_path(name: str) -> Path:
    """Path to ``roles/<name>.toml``."""
    return get_roles_dir() / f"{name}.toml"


def get_state_path() -> Path:
    """Path to the disposable runtime state file."""
    return get_config_dir() / STATE_FILENAME


# Template written when no pico.toml exists. Everything is commented out so the
# built-in defaults apply until the user uncomments what they need.
DEFAULT_PICO_TOML = """\
# Pico-Chat configuration (hand-edited intent).
#
# Runtime state (last server/model, discovery cache) lives in state.toml and is
# safe to delete. Apply changes with /reload, or /config (which reloads when the
# editor exits). Unknown keys and wrong types are reported on reload.

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
# [ui]
# theme = "terminal"                  # "terminal" | "pastel"
# use_bg_color = false                # paint the theme background
# app_global_padding = 0
# msg_h_padding = 1
# msg_v_margin = 0
# debug_console_height = 10
# box_style = "square"                # "square" | "double" | "rounded" | "ascii"
# box_style_focused = "square"
# scroll_lines_per_notch = 3
# scroll_touchpad_speed = 0.1
# scroll_touchpad_event_threshold = 2
# scroll_alt_multiplier = 3.0
# show_metrics = true
# metrics_show_tokens = false
# metrics_show_speed = true
# metrics_show_ttft = false
# metrics_refresh_interval = 0.1
# status_bar_fields = ["endpoint_model", "role", "context"]
# target_fps = 60

# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------
# [context]
# format = "tree"                     # "tree" (token-saving) | "flat"
# max_files = 500
# max_depth = 4
# ignore_gitignore = false
# preserve_reasoning_traces = false

# ---------------------------------------------------------------------------
# Subagents
# ---------------------------------------------------------------------------
# [subagents]
# max_depth = 1
# server = "local"                    # server subagents run on (default: active)
# timeout = 120
# max_context = 32000                 # omit for unlimited

# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------
# [debug]
# log_enabled = false                 # write debug_stream.log

# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------
# A server is referenced by its table name (e.g. [servers.local]) and selected
# with /server use <name>. Available types: llamacpp, ollama, openrouter, openai.
# Common keys: base_url, api_key (or api_key_env), model, max_context, timeout,
# retry_attempts, retry_delay.

# llama.cpp -------------------------------------------------------------
# [servers.local]
# type = "llamacpp"
# base_url = "http://localhost:8080/v1"
# api_key = "EMPTY"
# model = "qwen"                      # optional; llama.cpp serves one model
# timeout = 30.0
# retry_attempts = 3
# retry_delay = 2.0

# Ollama ----------------------------------------------------------------
# [servers.ollama]
# type = "ollama"
# base_url = "http://localhost:11434/v1"
# api_key = "ollama"
# model = "llama3.1:8b"               # optional; discover with /model
# timeout = 30.0

# OpenRouter ------------------------------------------------------------
# [servers.openrouter]
# type = "openrouter"
# base_url = "https://openrouter.ai/api/v1"
# api_key_env = "OPENROUTER_API_KEY"  # read the key from the environment
# enabled_models = ["anthropic/claude-3.5-sonnet"]
# provider = "Anthropic"              # optional default routing
#
# Per-model provider routing (whitelist = only these; blacklist = all but):
# [servers.openrouter.model_providers."anthropic/claude-3.5-sonnet"]
# mode = "whitelist"
# providers = ["Anthropic"]

# OpenAI-compatible -----------------------------------------------------
# [servers.openai]
# type = "openai"
# base_url = "https://api.openai.com/v1"
# api_key_env = "OPENAI_API_KEY"
# model = "gpt-4o"

# ---------------------------------------------------------------------------
# Markdown / syntax styling (optional overrides)
# ---------------------------------------------------------------------------
# [markdown_styles.header1]
# fg = "#CCA700"
# bold = true
#
# [syntax_highlight.keyword]
# fg = "#FF6464"
"""


# Example role file, written as ``roles/_example.toml`` on first use. Copy it
# to ``roles/<name>.toml`` (the file name is the role name) and edit. A file
# overrides a built-in role of the same name. ``disabled = true`` keeps this
# example out of /role list.
DEFAULT_ROLE_TOML = """\
# Pico-Chat role: copy this file to <name>.toml (e.g. architect.toml) and edit.
# The file name is the role name. Defining a role that matches a built-in
# (default, reviewer, researcher, scaffolder) overrides it. Select a role with
# /role use <name>.
#
# Tools: read, write, patch, run_command, search_web, search_wiki, subagent,
# wait_for_subagents. `permission` is the fallback decision:
# "allow" | "ask" | "deny".
#
# `disabled = true` hides this role; remove the line to enable it.
disabled = true
description = "Example role (copy me)"
prompt = ""

[tools.read]
enabled = true
permission = "allow"
[tools.read.settings]
inside_repo = "allow"
outside_repo = "ask"

[tools.write]
enabled = true
permission = "ask"
[tools.write.settings]
inside_repo = "allow"
outside_repo = "deny"

[tools.patch]
enabled = true
permission = "ask"
[tools.patch.settings]
inside_repo = "allow"
outside_repo = "deny"

[tools.run_command]
enabled = true
permission = "ask"
[tools.run_command.settings]
allow = ["ls", "cat", "grep"]
ask = ["git", "python3"]
deny = ["sudo", "rm"]
others = "deny"        # fallback for commands not listed
chain_policy = "ask"   # decision for chained commands (a && b)
use_container = true
container_network = false
"""


# --- pico.toml schema -------------------------------------------------------
# Each spec maps a TOML key to (runtime attribute, kind). Kinds drive both
# validation and coercion so a malformed value yields a reported error rather
# than a silently ignored setting.

_UI_SPEC: Dict[str, tuple[str, str]] = {
    "theme": ("ui_theme", "str"),
    "use_bg_color": ("ui_use_bg_color", "bool"),
    "app_global_padding": ("ui_app_global_padding", "int"),
    "msg_h_padding": ("ui_msg_h_padding", "int"),
    "msg_v_margin": ("ui_msg_v_margin", "int"),
    "debug_console_height": ("ui_debug_console_height", "int"),
    "box_style": ("ui_box_style", "str"),
    "box_style_focused": ("ui_box_style_focused", "str"),
    "scroll_lines_per_notch": ("ui_scroll_lines_per_notch", "int"),
    "scroll_touchpad_speed": ("ui_scroll_touchpad_speed", "float"),
    "scroll_touchpad_event_threshold": ("ui_scroll_touchpad_event_threshold", "int"),
    "scroll_alt_multiplier": ("ui_scroll_alt_multiplier", "float"),
    "show_metrics": ("ui_show_metrics", "bool"),
    "metrics_show_tokens": ("ui_metrics_show_tokens", "bool"),
    "metrics_show_speed": ("ui_metrics_show_speed", "bool"),
    "metrics_show_ttft": ("ui_metrics_show_ttft", "bool"),
    "metrics_refresh_interval": ("ui_metrics_refresh_interval", "float"),
    "status_bar_fields": ("ui_status_bar_fields", "str_list"),
    "target_fps": ("target_fps", "int"),
}

_CONTEXT_SPEC: Dict[str, tuple[str, str]] = {
    "format": ("context_format", "context_format"),
    "max_files": ("context_max_files", "int"),
    "max_depth": ("context_max_depth", "int"),
    "ignore_gitignore": ("context_ignore_gitignore", "bool"),
    "preserve_reasoning_traces": ("preserve_reasoning_traces", "bool"),
}

_SUBAGENT_SPEC: Dict[str, tuple[str, str]] = {
    "max_depth": ("subagent_max_depth", "int"),
    "server": ("subagent_server", "str_or_none"),
    "timeout": ("subagent_timeout", "int_or_float"),
    "max_context": ("subagent_max_context", "int_or_none"),
}

_DEBUG_SPEC: Dict[str, tuple[str, str]] = {
    "log_enabled": ("debug_log_enabled", "bool"),
}

_TOP_LEVEL_SECTIONS = {
    "ui", "servers", "context", "subagents", "debug",
    "markdown_styles", "syntax_highlight",
}

_SERVER_KEYS = {
    "type", "base_url", "api_key", "api_key_env", "model", "max_context",
    "timeout", "retry_attempts", "retry_delay", "provider", "enabled_models",
    "model_providers",
}
_SERVER_TYPES = {"llamacpp", "ollama", "openrouter", "openai"}
_SERVER_STR_KEYS = {"type", "base_url", "api_key", "api_key_env", "model", "provider"}
_SERVER_INT_KEYS = {"max_context", "retry_attempts"}
_SERVER_FLOAT_KEYS = {"timeout", "retry_delay"}

_STATE_SECTIONS = {"last_server", "active_model", "last_model", "model_catalog"}


def _coerce(kind: str, value: Any) -> tuple[Any, Optional[str]]:
    """Return ``(coerced, None)`` or ``(None, error)`` for one config value."""
    if kind == "str":
        return (value, None) if isinstance(value, str) else (None, "must be a string")
    if kind == "bool":
        return (value, None) if isinstance(value, bool) else (None, "must be a boolean")
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "must be an integer"
        return value, None
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, "must be a number"
        return float(value), None
    if kind == "int_or_float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, "must be a number"
        return value, None
    if kind == "str_list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return None, "must be a list of strings"
        return list(value), None
    if kind == "str_or_none":
        if value is None or isinstance(value, str):
            return value, None
        return None, "must be a string or absent"
    if kind == "int_or_none":
        if value is None:
            return None, None
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "must be an integer or absent"
        return value, None
    if kind == "context_format":
        if value not in ("tree", "flat"):
            return None, "must be 'tree' or 'flat'"
        return value, None
    return value, None


class Config:
    """Validated view of ``pico.toml`` plus disposable ``state.toml``."""

    def __init__(self, config_path: str | Path | None = None,
                 state_path: str | Path | None = None):
        self._config_path = Path(config_path) if config_path else None
        self._state_path = Path(state_path) if state_path else None
        self.load_errors: list[str] = []
        self._apply_defaults()
        self.reload()

    # -- defaults ------------------------------------------------------------

    def _apply_defaults(self) -> None:
        """Reset every runtime attribute to its built-in default."""
        # LLM servers (intent) and selection (state).
        self.servers: Dict[str, Dict[str, Any]] = {}
        self.active_server: str = "llamacpp_default"
        self.active_model: Optional[str] = None
        self.model_selection: Dict[str, str] = {}
        self.models_by_server: Dict[str, list] = {}

        # UI settings.
        self.ui_debug_console_height: int = 10
        self.ui_use_bg_color: bool = False
        self.ui_theme: str = "terminal"
        self.ui_app_global_padding: int = 0
        self.ui_msg_h_padding: int = 1
        self.ui_msg_v_margin: int = 0
        self.ui_box_style: str = "square"
        self.ui_box_style_focused: str = "square"
        self.ui_scroll_lines_per_notch: int = 3
        self.ui_scroll_touchpad_speed: float = 0.1
        self.ui_scroll_touchpad_event_threshold: int = 2
        self.ui_scroll_alt_multiplier: float = 3.0
        self.ui_show_metrics: bool = True
        self.ui_metrics_show_tokens: bool = False
        self.ui_metrics_show_speed: bool = True
        self.ui_metrics_show_ttft: bool = False
        self.ui_metrics_refresh_interval: float = 0.1
        self.ui_status_bar_fields: list[str] = ["endpoint_model", "role", "context"]
        self.target_fps: int = 60

        # Debug / reasoning.
        self.debug_log_enabled: bool = False
        self.preserve_reasoning_traces: bool = False

        # Context building.
        self.context_format: Literal["tree", "flat"] = "tree"
        self.context_max_files: int = 500
        self.context_max_depth: int = 4
        self.context_ignore_gitignore: bool = False

        # Subagents.
        self.subagent_max_depth: int = 1
        self.subagent_server: Optional[str] = None
        self.subagent_timeout: int = 120
        self.subagent_max_context: Optional[int] = None

        # Style tables.
        self.markdown_styles: Dict[str, Dict[str, Any]] = {
            k: dict(v) for k, v in DEFAULT_MARKDOWN_STYLES.items()
        }
        self.syntax_highlight_styles: Dict[str, Dict[str, str]] = {
            k: dict(v) for k, v in DEFAULT_SYNTAX_HIGHLIGHT_STYLES.items()
        }

    # -- loading -------------------------------------------------------------

    def _config_file(self) -> Path:
        return self._config_path or get_config_path()

    def _state_file(self) -> Path:
        return self._state_path or get_state_path()

    def reload(self) -> list[str]:
        """Reload intent and state from disk, returning any validation errors.

        Any value that fails validation keeps its default; the rest of the
        file is still applied.
        """
        self._apply_defaults()
        self.load_errors = []
        _load_pico_file(self._config_file(), self, self.load_errors)
        _load_state_file(self._state_file(), self, self.load_errors)
        return self.load_errors

    # -- intent mutations ----------------------------------------------------

    def save_server(self, name: str, server_config: Dict[str, Any],
                    set_active: bool = True) -> None:
        """Write a server definition to ``pico.toml`` (intent)."""
        path = self._config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = toml.load(path) if path.exists() else {}
        data.setdefault("servers", {})[name] = dict(server_config)
        path.write_text(toml.dumps(data), encoding="utf-8")

        self.servers[name] = dict(server_config)
        if set_active:
            self.active_server = name
            self._save_state()

    # -- state mutations -----------------------------------------------------

    def save_active_model(self, model: Optional[str]) -> None:
        """Persist the selected model independently from endpoint definitions."""
        self.active_model = model
        self._save_state()

    def save_model_selection(self, server: str, model: Optional[str]) -> None:
        """Persist the selected model for a specific server."""
        if model:
            self.model_selection[server] = model
        else:
            self.model_selection.pop(server, None)
        self._save_state()

    def save_model_catalog(self) -> None:
        """Persist the discovery catalog so /model completion works on restart."""
        self._save_state()

    def _save_state(self) -> None:
        path = self._state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: Dict[str, Any] = {}
        if self.active_server:
            data["last_server"] = self.active_server
        if self.active_model:
            data["active_model"] = self.active_model
        if self.model_selection:
            data["last_model"] = dict(self.model_selection)
        if self.models_by_server:
            data["model_catalog"] = {
                server: [dict(m) for m in models]
                for server, models in self.models_by_server.items()
            }
        path.write_text(toml.dumps(data), encoding="utf-8")

    def set_active_server(self, name: str) -> None:
        """Make ``name`` the active server and restore its last model."""
        if name not in self.servers:
            raise KeyError(name)
        self.active_server = name
        self.active_model = self.get_model_for_server(name)
        self._save_state()

    def remove_server(self, name: str) -> bool:
        """Delete a server from ``pico.toml``; returns False if unknown."""
        if name not in self.servers:
            return False
        path = self._config_file()
        data = toml.load(path) if path.exists() else {}
        data.get("servers", {}).pop(name, None)
        path.write_text(toml.dumps(data), encoding="utf-8")

        self.servers.pop(name, None)
        self.models_by_server.pop(name, None)
        self.model_selection.pop(name, None)
        if self.active_server == name:
            self.active_server = next(iter(self.servers), "llamacpp_default")
            self.active_model = None
        self._save_state()
        return True

    def ensure_config_file(self) -> Path:
        """Create ``pico.toml`` from the commented template if it is missing."""
        path = self._config_file()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_PICO_TOML, encoding="utf-8")
        return path

    # -- read helpers --------------------------------------------------------

    def get_model_for_server(self, server: str) -> Optional[str]:
        """Effective model for a server: per-server selection, then its default."""
        if server in self.model_selection:
            return self.model_selection[server]
        server_cfg = self.servers.get(server)
        if server_cfg:
            return server_cfg.get("model")
        return None

    def get_active_server_config(self) -> Optional[Dict[str, Any]]:
        """Get the configuration for the currently active server."""
        return self.servers.get(self.active_server)


def _load_pico_file(path: Path, config: Config, errors: list[str]) -> None:
    if not path.exists():
        return
    try:
        data = toml.load(path)
    except (toml.TomlDecodeError, OSError) as exc:
        errors.append(f"{path.name}: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{path.name}: top level must be a table")
        return

    for section in data:
        if section not in _TOP_LEVEL_SECTIONS:
            errors.append(f"{path.name}: unknown section [{section}]")

    _apply_spec_table(config, data, path.name, "ui", _UI_SPEC, errors)
    _apply_spec_table(config, data, path.name, "context", _CONTEXT_SPEC, errors)
    _apply_spec_table(config, data, path.name, "subagents", _SUBAGENT_SPEC, errors)
    _apply_spec_table(config, data, path.name, "debug", _DEBUG_SPEC, errors)
    _load_servers(config, data, path.name, errors)
    _merge_style_table(config, data, path.name, "markdown_styles",
                       config.markdown_styles, errors)
    _merge_style_table(config, data, path.name, "syntax_highlight",
                       config.syntax_highlight_styles, errors)


def _apply_spec_table(config: Config, data: dict, filename: str, section: str,
                      spec: Dict[str, tuple[str, str]], errors: list[str]) -> None:
    table = data.get(section)
    if table is None:
        return
    if not isinstance(table, dict):
        errors.append(f"{filename}: [{section}] must be a table")
        return
    for key, value in table.items():
        entry = spec.get(key)
        if entry is None:
            errors.append(f"{filename}: [{section}] unknown key '{key}'")
            continue
        attr, kind = entry
        coerced, error = _coerce(kind, value)
        if error:
            errors.append(f"{filename}: [{section}].{key} {error}")
            continue
        setattr(config, attr, coerced)


def _load_servers(config: Config, data: dict, filename: str,
                  errors: list[str]) -> None:
    table = data.get("servers")
    if table is None:
        return
    if not isinstance(table, dict):
        errors.append(f"{filename}: [servers] must be a table")
        return
    for name, server in table.items():
        where = f"{filename}: [servers.{name}]"
        if not isinstance(server, dict):
            errors.append(f"{where} must be a table")
            continue
        for key in server:
            if key not in _SERVER_KEYS:
                errors.append(f"{where} unknown key '{key}'")
        server_type = server.get("type")
        if server_type is not None and server_type not in _SERVER_TYPES:
            errors.append(f"{where}.type unknown server type '{server_type}'")
        for key in _SERVER_STR_KEYS:
            if key in server and not isinstance(server[key], str):
                errors.append(f"{where}.{key} must be a string")
        for key in _SERVER_INT_KEYS:
            if key in server and (isinstance(server[key], bool)
                                  or not isinstance(server[key], int)):
                errors.append(f"{where}.{key} must be an integer")
        for key in _SERVER_FLOAT_KEYS:
            if key in server and (isinstance(server[key], bool)
                                  or not isinstance(server[key], (int, float))):
                errors.append(f"{where}.{key} must be a number")
        if "enabled_models" in server:
            enabled = server["enabled_models"]
            if not isinstance(enabled, list) or not all(isinstance(m, str) for m in enabled):
                errors.append(f"{where}.enabled_models must be a list of strings")
        if "model_providers" in server and not isinstance(server["model_providers"], dict):
            errors.append(f"{where}.model_providers must be a table")
        config.servers[name] = dict(server)


def _merge_style_table(config: Config, data: dict, filename: str, section: str,
                       target: Dict[str, Dict[str, Any]], errors: list[str]) -> None:
    table = data.get(section)
    if table is None:
        return
    if not isinstance(table, dict):
        errors.append(f"{filename}: [{section}] must be a table")
        return
    for element, style in table.items():
        if element not in target:
            errors.append(f"{filename}: [{section}] unknown element '{element}'")
            continue
        if not isinstance(style, dict):
            errors.append(f"{filename}: [{section}].{element} must be a table")
            continue
        target[element].update(style)


def _load_state_file(path: Path, config: Config, errors: list[str]) -> None:
    if not path.exists():
        return
    try:
        data = toml.load(path)
    except (toml.TomlDecodeError, OSError) as exc:
        errors.append(f"{path.name}: {exc}")
        return
    if not isinstance(data, dict):
        errors.append(f"{path.name}: top level must be a table")
        return

    for section in data:
        if section not in _STATE_SECTIONS:
            errors.append(f"{path.name}: unknown key '{section}'")

    last_server = data.get("last_server")
    if last_server is not None:
        if isinstance(last_server, str):
            config.active_server = last_server
        else:
            errors.append(f"{path.name}: last_server must be a string")

    active_model = data.get("active_model")
    if active_model is not None:
        if isinstance(active_model, str):
            config.active_model = active_model
        else:
            errors.append(f"{path.name}: active_model must be a string")

    last_model = data.get("last_model")
    if last_model is not None:
        if isinstance(last_model, dict) and all(
                isinstance(v, str) for v in last_model.values()):
            config.model_selection = dict(last_model)
        else:
            errors.append(f"{path.name}: last_model must map server names to model ids")

    catalog = data.get("model_catalog")
    if catalog is not None:
        if isinstance(catalog, dict) and all(
                isinstance(models, list) for models in catalog.values()):
            config.models_by_server = {
                server: [dict(m) for m in models]
                for server, models in catalog.items()
            }
        else:
            errors.append(f"{path.name}: model_catalog must be a table of model lists")


# Global config instance, reloadable via reload_config().
config: Config = Config()


def ensure_roles_dir() -> Path:
    """Create the roles directory with the example file if it is missing."""
    directory = get_roles_dir()
    directory.mkdir(parents=True, exist_ok=True)
    example = directory / ROLE_EXAMPLE_FILENAME
    if not example.exists():
        example.write_text(DEFAULT_ROLE_TOML, encoding="utf-8")
    return directory


def reload_config() -> list[str]:
    """Reload the global config from disk; return validation errors."""
    return config.reload()
