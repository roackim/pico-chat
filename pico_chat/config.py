import os
import toml
from pathlib import Path
from typing import Literal

Permission = Literal["allow", "ask", "deny"]


class Config:
    """Configuration for Pico-Chat."""

    def __init__(self, config_path: str | None = None):
        """Initialize configuration, optionally loading from TOML."""
        # LLM settings
        self.base_url: str = "http://gpu4.hygeos.com:8080/v1"
        self.model: str = "GLM-4.7-Flash-Q8_0.gguf"
        self.api_key: str = "EMPTY"

        # Tool permissions: allow, ask, deny
        self.permissions: dict[str, Permission] = {
            "read": "allow",
            "search": "allow",
            "edit": "ask",
            "run": "ask",
            "create": "ask",
            "write": "ask",
            "tree": "allow",
        }

        # Tool enable/disable
        self.enabled_tools: dict[str, bool] = {
            "read": True,
            "search": True,
            "edit": True,
            "run": True,
            "create": True,
            "tree": False,
            "write": False,
        }

        # Other settings
        self.render_thinking: bool = False
        self.log_file: str = "pico_chat.log"
        self.max_file_size: int = 1_000_000
        self.max_search_results: int = 50
        self.command_timeout: int = 30
        self.tree_max_depth: int = 4
        self.exclude_patterns: list[str] = [
            "node_modules", "__pycache__", ".git", "target", "dist", "build", "*.pyc", ".venv", "venv",
        ]
        
        # UI colors (RGB tuples)
        self.ui_user_color: tuple[int, int, int] = (150, 255, 150)  # Green
        self.ui_assistant_color: tuple[int, int, int] = (242, 207, 101)  # Orange

        # Cursor settings
        self.ui_cursor_char: str = "█"
        self.ui_cursor_frequency: float = 1.0  # Hz (flashes per second)
        self.ui_cursor_color: tuple[int, int, int] = (200, 200, 200)
        self.ui_cursor_pulse_delay: float = 0.5  # Seconds before pulsating starts

        # Load from file if exists
        path = Path(config_path) if config_path else Path("pico_chat.toml")
        if not path.exists():
            path = Path.home() / ".pico_chat.toml"
        
        if path.exists():
            try:
                data = toml.load(path)
                self._load_from_dict(data)
            except Exception as e:
                print(f"Warning: Failed to load config from {path}: {e}")

    def _load_from_dict(self, data: dict):
        """Load values from dict."""
        if "llm" in data:
            llm = data["llm"]
            self.base_url = llm.get("base_url", self.base_url)
            self.model = llm.get("model", self.model)
            self.api_key = llm.get("api_key", self.api_key)
        
        if "permissions" in data:
            self.permissions.update(data["permissions"])
        
        if "thinking" in data:
            thinking = data["thinking"]
            self.render_thinking = thinking.get("render", self.render_thinking)
            self.log_file = thinking.get("log_file", self.log_file)
            
        if "tools" in data:
            tools = data["tools"]
            self.max_file_size = tools.get("max_file_size", self.max_file_size)
            self.max_search_results = tools.get("max_search_results", self.max_search_results)
            self.command_timeout = tools.get("command_timeout", self.command_timeout)
            
            # Update enabled tools
            for tool in self.enabled_tools:
                key = f"enable_{tool}"
                if key in tools:
                    self.enabled_tools[tool] = tools[key]
        
        if "ui" in data:
            ui = data["ui"]
            if "user_color" in ui:
                self.ui_user_color = tuple(ui["user_color"])
            if "assistant_color" in ui:
                self.ui_assistant_color = tuple(ui["assistant_color"])            
            # Cursor settings in UI section
            if "cursor" in ui:
                cursor = ui["cursor"]
                self.ui_cursor_char = cursor.get("char", self.ui_cursor_char)
                self.ui_cursor_frequency = cursor.get("frequency", self.ui_cursor_frequency)
                self.ui_cursor_pulse_delay = cursor.get("pulse_delay", self.ui_cursor_pulse_delay)
                if "color" in cursor:
                    self.ui_cursor_color = tuple(cursor["color"])
    def get_permission(self, tool: str) -> Permission:
        """Get permission for a tool."""
        return self.permissions.get(tool, "deny")
    
    def is_tool_enabled(self, tool: str) -> bool:
        """Check if a tool is enabled."""
        return self.enabled_tools.get(tool, False)


# Global config instance
_config: Config | None = None


def get_config(config_path: str | None = None) -> Config:
    """Get global configuration instance."""
    global _config
    if _config is None or config_path is not None:
        _config = Config(config_path)
    return _config
