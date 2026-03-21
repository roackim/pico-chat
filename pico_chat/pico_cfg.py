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
        self.ui_debug_console_height: int = 10 # Height of the debug console in lines
        self.ui_global_padding: int = 0  # Global padding around the entire app (in characters)
        self.ui_use_bg_color: bool = False  # Whether to use theme background color (False uses terminal default)
        
        
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

        # Tool permissions (initialized at module level, can be imported and modified)
        # from pico_chat.harness import tool_permissions
        # tool_permissions.permissions = tool_permissions.strict  # Change profile

        # TODO: Load config from file if exists


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