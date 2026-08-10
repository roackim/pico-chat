import toml
from pathlib import Path
from typing import Dict, Any, Literal, Optional

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


def get_config_path() -> Path:
    """Get the path to the user's config file."""
    config_dir = Path.home() / ".config" / "pico-chat"
    return config_dir / "config.toml"


class Config:
    """Configuration for Pico-Chat."""

    def __init__(self, config_path: str | None = None):
        """Initialize configuration, optionally loading from TOML."""
        # LLM settings
        self.servers: Dict[str, Dict[str, Any]] = {}
        self.active_server: str = "llamacpp_default"
        # Model selection is separate from the endpoint definition. The
        # legacy per-server ``model`` key remains a default for compatibility.
        self.active_model: Optional[str] = None

        
        # UI settings
        self.ui_debug_console_height: int = 10 # Height of the debug console in lines
        
        self.ui_use_bg_color: bool = False  # Whether to use theme background color (False uses terminal default)
        self.ui_theme: str = "terminal"  # Color theme: "terminal" or "pastel"
        self.ui_app_global_padding: int = 0  # Global padding inside the entire app (in characters)
        self.ui_msg_h_padding: int = 1 # Horizontal padding for text in UI components 
        self.ui_msg_v_margin: int = 0 # Vertical padding between messages in ChatHistoryPanel
        
        self.ui_box_style: str = "square" # Box border style: ("square", "double", "rounded", ascii)
        self.ui_box_style_focused: str = "square" # NOTE: currently unplugged; Box border style when focused: ("square", "double", "rounded")
        
        # Scrolling settings
        self.ui_scroll_lines_per_notch: int = 3  # Base lines scrolled per wheel notch
        self.ui_scroll_touchpad_speed: float = 0.1  # Multiplier applied to touchpad bursts (slower)
        self.ui_scroll_touchpad_event_threshold: int = 2  # Events per frame above which a burst is treated as touchpad
        self.ui_scroll_alt_multiplier: float = 3.0  # Multiplier applied when Alt is held during scroll
        
        # Generation metrics display
        self.ui_show_metrics: bool = True  # Show generation metrics
        self.ui_metrics_show_tokens: bool = False
        self.ui_metrics_show_speed: bool = True
        self.ui_metrics_show_ttft: bool = False
        self.ui_metrics_refresh_interval: float = 0.1  # Seconds between metric updates
        self.ui_status_bar_fields: list[str] = ["endpoint_model", "role", "context"]
        
        self.target_fps: int = 60
        
        # Debug settings
        self.debug_log_enabled: bool = False  # Write debug_stream.log to disk

        # Reasoning / thinking trace settings
        self.preserve_reasoning_traces: bool = True  # Preserve <think> blocks in history for multi-turn reasoning

        # Context building settings
        self.context_format: Literal["tree", "flat"] = "tree"  # Tree format saves tokens by avoiding path repetition

        # Subagent settings
        self.subagent_max_depth: int = 1        # Maximum subagent recursion depth
        self.subagent_server: str | None = None  # Server name for subagents (None = inherit active_server)
        self.subagent_timeout: int = 120         # Seconds before a subagent is auto-aborted
        self.subagent_max_context: int | None = None  # Max tokens per subagent (None = unlimited)

        # Markdown element styles (element_name -> {fg, bg, bold, reverse})
        self.markdown_styles: Dict[str, Dict[str, Any]] = {}
        for _k, _v in DEFAULT_MARKDOWN_STYLES.items():
            self.markdown_styles[_k] = dict(_v)

        # Syntax highlight element styles (type_name -> {fg})
        self.syntax_highlight_styles: Dict[str, Dict[str, str]] = {}
        for _k, _v in DEFAULT_SYNTAX_HIGHLIGHT_STYLES.items():
            self.syntax_highlight_styles[_k] = dict(_v)

        # Load config from file if path provided or default exists
        if config_path:
            self._load_from_file(Path(config_path))
        else:
            default_path = get_config_path()
            if default_path.exists():
                self._load_from_file(default_path)

    def _load_from_file(self, path: Path):
        """Load configuration from TOML file."""
        try:
            data = toml.load(path)
            
            # Load server configurations
            # ``servers`` is the legacy spelling. ``endpoints`` is preferred
            # but both normalize to the same runtime mapping.
            if "endpoints" in data:
                self.servers = data["endpoints"]
            elif "servers" in data:
                self.servers = data["servers"]
            
            # Load active server
            if "settings" in data and "active_server" in data["settings"]:
                self.active_server = data["settings"]["active_server"]
            if "settings" in data and "active_endpoint" in data["settings"]:
                self.active_server = data["settings"]["active_endpoint"]
            if "settings" in data and "active_model" in data["settings"]:
                self.active_model = data["settings"]["active_model"]
            
            # Load UI settings
            if "ui" in data:
                ui_data = data["ui"]
                for key, value in ui_data.items():
                    attr_name = f"ui_{key}"
                    if hasattr(self, attr_name):
                        setattr(self, attr_name, value)
            
            # Load markdown styles
            if "markdown_styles" in data:
                for element, style_dict in data["markdown_styles"].items():
                    if element in self.markdown_styles:
                        self.markdown_styles[element].update(style_dict)

            # Load syntax highlight styles
            if "syntax_highlight" in data:
                for element, style_dict in data["syntax_highlight"].items():
                    if element in self.syntax_highlight_styles:
                        self.syntax_highlight_styles[element].update(style_dict)

            # Load other settings
            if "settings" in data:
                settings = data["settings"]
                for key in ["max_file_size", "max_search_results",
                           "command_timeout", "target_fps", "context_format",
                           "active_model",
                           "debug_log_enabled",
                           "preserve_reasoning_traces",
                           "subagent_max_depth", "subagent_server",
                           "subagent_timeout", "subagent_max_context"]:
                    if key in settings:
                        setattr(self, key, settings[key])
                        
        except Exception as e:
            # Silently fail if config doesn't exist or is invalid
            # This allows the app to run with defaults
            pass

    def save_server(self, name: str, server_config: Dict[str, Any], set_active: bool = True):
        """
        Save a server configuration to the config file.
        
        Args:
            name: Server name/identifier
            server_config: Server configuration dict
            set_active: Whether to set this as the active server
        """
        config_path = get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing config or create new
        if config_path.exists():
            data = toml.load(config_path)
        else:
            data = {"servers": {}, "settings": {}}
        
        # Update server config
        endpoint_table = "endpoints" if "endpoints" in data else "servers"
        if endpoint_table not in data:
            data[endpoint_table] = {}
        data[endpoint_table][name] = server_config
        
        # Update active server if requested
        if set_active:
            if "settings" not in data:
                data["settings"] = {}
            data["settings"]["active_server"] = name
            data["settings"]["active_endpoint"] = name
        
        # Save back to file
        with open(config_path, "w") as f:
            toml.dump(data, f)
        
        # Update runtime config
        self.servers[name] = server_config
        if set_active:
            self.active_server = name

    def save_active_model(self, model: Optional[str]) -> None:
        """Persist the selected model independently from endpoint definitions."""
        config_path = get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = toml.load(config_path) if config_path.exists() else {"servers": {}, "settings": {}}
        data.setdefault("settings", {})
        if model:
            data["settings"]["active_model"] = model
            self.active_model = model
        else:
            data["settings"].pop("active_model", None)
            self.active_model = None
        with open(config_path, "w") as f:
            toml.dump(data, f)

    def get_active_server_config(self) -> Optional[Dict[str, Any]]:
        """Get the configuration for the currently active server."""
        if self.active_server in self.servers:
            return self.servers[self.active_server]
        return None


# Global config instance
global config
config: Config = Config(config_path=None)
