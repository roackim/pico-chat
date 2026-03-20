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
        self.base_url: str = "http://clank:3344/v1"
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
        
        # UI settings
        self.ui_cursor_frequency: float = 1.0  # Hz (flashes per second)
        self.ui_cursor_pulse_delay: float = 0.75  # Seconds before pulsating starts
        self.ui_max_input_height: int = 10  # Maximum height of input field in lines
        
        
        # TODO investigate deadcode around these padding settings and remove if not used
        # -------------------------------------------------------------------------------
        # NOTE: box.py @ 26
        # >         self.child.set_layout(x + 1, y + 1, width - 2, height - 2)
        # probably the way to go
        self.ui_msg_h_padding = 1 # Horizontal padding for text in UI components 
        
        self.ui_box_style = "single" # Box border style (e.g. "single", "double", "rounded")
        
        # NOTE: works as expected even with scroll
        self.ui_v_padding = 0 # Vertical padding between messages in ChatHistoryPanel
        
        # TODO: plug this value (currently a stub)
        self.ui_h_padding = 1 # Horizontal padding between messages and term borders in ChatHistoryPanel

        self.target_fps: int = 60

        # TODO: Load config from file if exists


    def get_permission(self, tool: str) -> Permission:
        """Get permission for a tool."""
        return self.permissions.get(tool, "deny")
    
    def is_tool_enabled(self, tool: str) -> bool:
        """Check if a tool is enabled."""
        return self.enabled_tools.get(tool, False)


# Global config instance
global config
config: Config = Config(config_path=None)