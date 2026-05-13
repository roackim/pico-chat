import os
import toml
from pathlib import Path
from typing import Literal, Dict, Any, Optional

Permission = Literal["allow", "ask", "deny"]


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

        # Other settings
        self.render_thinking: bool = False
        self.log_file: str = "pico_chat.log" # TODO PLUG not currently used
        self.max_file_size: int = 1_000_000
        self.max_search_results: int = 50
        self.command_timeout: int = 30
        
        # UI settings
        self.ui_cursor_frequency: float = 1.0  # Hz (flashes per second)
        self.ui_cursor_pulse_delay: float = 0.75  # Seconds before pulsating starts
        
        self.ui_max_input_height: int = 10  # Maximum height of input field in lines
        self.ui_debug_console_height: int = 10 # Height of the debug console in lines
        
        self.ui_use_bg_color: bool = False  # Whether to use theme background color (False uses terminal default)
        self.ui_theme: str = "default"  # Color theme: "default" or "terminal"
        self.ui_app_global_padding: int = 0  # Global padding inside the entire app (in characters)
        self.ui_msg_h_padding: int = 1 # Horizontal padding for text in UI components 
        self.ui_msg_v_margin: int = 0 # Vertical padding between messages in ChatHistoryPanel
        
        self.ui_box_style: str = "square" # Box border style: ("square", "double", "rounded", ascii)
        self.ui_box_style_focused: str = "square" # NOTE: currently unplugged; Box border style when focused: ("square", "double", "rounded")
        
        # Generation metrics display
        self.ui_show_metrics: bool = True  # Show generation metrics
        self.ui_metrics_show_tokens: bool = False
        self.ui_metrics_show_speed: bool = True
        self.ui_metrics_show_ttft: bool = False
        self.ui_metrics_refresh_interval: float = 0.1  # Seconds between metric updates
        
        self.target_fps: int = 60
        
        # Context building settings
        self.context_format: Literal["tree", "flat"] = "tree"  # Tree format saves tokens by avoiding path repetition

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
            if "servers" in data:
                self.servers = data["servers"]
            
            # Load active server
            if "settings" in data and "active_server" in data["settings"]:
                self.active_server = data["settings"]["active_server"]
            
            # Load UI settings
            if "ui" in data:
                ui_data = data["ui"]
                for key, value in ui_data.items():
                    attr_name = f"ui_{key}"
                    if hasattr(self, attr_name):
                        setattr(self, attr_name, value)
            
            # Load other settings
            if "settings" in data:
                settings = data["settings"]
                for key in ["render_thinking", "max_file_size", "max_search_results", 
                           "command_timeout", "target_fps", "context_format"]:
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
        if "servers" not in data:
            data["servers"] = {}
        data["servers"][name] = server_config
        
        # Update active server if requested
        if set_active:
            if "settings" not in data:
                data["settings"] = {}
            data["settings"]["active_server"] = name
        
        # Save back to file
        with open(config_path, "w") as f:
            toml.dump(data, f)
        
        # Update runtime config
        self.servers[name] = server_config
        if set_active:
            self.active_server = name

    def get_active_server_config(self) -> Optional[Dict[str, Any]]:
        """Get the configuration for the currently active server."""
        if self.active_server in self.servers:
            return self.servers[self.active_server]
        return None


    def get_permission(self, tool: str, is_inside_repo: bool = True) -> Permission:
        """
        Get permission for a tool.
        
        Args:
            tool: Tool name ('read', 'write', 'patch', 'run')
            is_inside_repo: Whether the operation is inside repo (for file ops)
        
        Returns:
            Permission level ('allow', 'ask', 'deny')
        
        Note:
            This imports tool_permissions dynamically to avoid circular imports.
            The actual permissions are configured in pico_chat.harness.tool_permissions
        """
        from pico_chat.harness.tool_permissions import permissions
        
        if tool == 'read':
            return permissions.get_read_permission(is_inside_repo)
        elif tool == 'write':
            return permissions.get_write_permission(is_inside_repo)
        elif tool == 'patch':
            return permissions.get_patch_permission(is_inside_repo)
        elif tool == 'run':
            return permissions.get_run_permission()
        else:
            return "deny"


# Global config instance
global config
config: Config = Config(config_path=None)
