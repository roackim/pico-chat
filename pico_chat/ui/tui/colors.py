
from dataclasses import dataclass


class RGB:
    def __init__(self, r, g=None, b=None):
        self.r = r
        self.g = g
        self.b = b
        
        if type(r) == str:
            # Parse from hex string
            hex_str = r.lstrip('#')
            if len(hex_str) == 6:
                self.r = int(hex_str[0:2], 16)
                self.g = int(hex_str[2:4], 16)
                self.b = int(hex_str[4:6], 16)
            else:
                raise ValueError(f"Invalid hex color string: {r}")
    
    def ansi_fg(self): 
        """ coinvert to ANSI foreground color code """
        return f"\033[38;2;{self.r};{self.g};{self.b}m"

    def ansi_bg(self): 
        """ coinvert to ANSI background color code """
        return f"\033[48;2;{self.r};{self.g};{self.b}m"        

@dataclass
class _theme:    
    name: str
    BACKGROUND: RGB
    DEFAULT: RGB
    SKY: RGB
    MUTED: RGB
    ERROR: RGB
    WARNING: RGB
    USER: RGB
    PICO: RGB
    
    def reset(self) -> str:
        """reset to theme bg + fg colors"""
        return self.BACKGROUND.ansi_bg() + self.DEFAULT.ansi_fg()
    
    def get_bg(self):
        """Get background color respecting ui_use_bg_color config setting."""
        from pico_chat import pico_cfg
        if pico_cfg.config.ui_use_bg_color:
            return self.BACKGROUND
        return None
    
# TODO: refactor to load colors from theme instead of hardcoding in config
# NOTE: regex to find them: [\[\(]\s*\d+\s*,\s*\d+\s*,\s*\d+\s*[\]\)]   

default = _theme(
    name="default",
    BACKGROUND  = RGB("#B21ECF"),       # Black
    DEFAULT     = RGB("#F7F4EA"),   # White
    SKY         = RGB("#87CEEB"), # Color for the non UI elements
    MUTED       = RGB("#7D7D7D"), # Muted gray
    ERROR       = RGB("#FF6060"),   # Red
    WARNING     = RGB("#FFC760"),  # Orange
    USER        = RGB("#7ADA92"),  # Blue
    PICO        = RGB("#F4CE66"),  # Green
)

theme: _theme = default


