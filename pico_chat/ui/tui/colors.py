
from dataclasses import dataclass


class RGB:
    def __init__(self, r, g, b):
        self.r = r
        self.g = g
        self.b = b
    
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
    WARN: RGB
    USER: RGB
    PICO: RGB
    
    def reset(self) -> str:
        """reset to theme bg + fg colors"""
        return self.BACKGROUND.ansi_bg() + self.DEFAULT.ansi_fg()
    
# TODO: refactor to load colors from theme instead of hardcoding in config
# NOTE: regex to find them: [\[\(]\s*\d+\s*,\s*\d+\s*,\s*\d+\s*[\]\)]   

default = _theme(
    name="default",
    BACKGROUND  = RGB(0, 0, 0),       # Black
    DEFAULT     = RGB(255, 255, 255), # White
    SKY         = RGB(135, 206, 235), # Color for the non UI elements
    MUTED       = RGB(125, 125, 125), # Muted gray
    ERROR       = RGB(255, 96, 96),   # Red
    WARN        = RGB(255, 160, 96),  # Orange
    USER        = RGB(96, 160, 255),  # Blue
    PICO        = RGB(96, 255, 160),  # Green
)

theme: _theme = default