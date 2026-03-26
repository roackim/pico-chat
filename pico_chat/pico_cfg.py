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
        
        self.target_fps: int = 1
        
        # Context building settings
        self.context_format: Literal["tree", "flat"] = "tree"  # Tree format saves tokens by avoiding path repetition

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