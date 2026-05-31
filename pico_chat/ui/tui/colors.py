
from dataclasses import dataclass

from pico_chat import pico_cfg

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
    
    def __str__(self):
        return self.ansi_fg()
    
    # concat support for ergonomics
    def __add__(self, other):
        if isinstance(other, str):
            return self.ansi_fg() + other
        else:
            return self.ansi_fg() + str(other)
    
    def ansi_fg(self): 
        """ coinvert to ANSI foreground color code """
        return f"\033[38;2;{self.r};{self.g};{self.b}m"

    def ansi_bg(self): 
        """ coinvert to ANSI background color code """
        return f"\033[48;2;{self.r};{self.g};{self.b}m"        


class ANSIColor:
    """Terminal-native color using standard 8/16 ANSI color codes.
    
    Uses the terminal's own palette instead of hardcoded RGB values,
    so the theme respects the user's terminal color scheme.
    
    fg_code: ANSI foreground code (30-37 standard, 90-97 bright, 39 = default)
    bg_code: ANSI background code (40-47 standard, 100-107 bright, 49 = default)
    """
    def __init__(self, fg: int = 39, bg: int = 49):
        self.fg = fg
        self.bg = bg

    def __str__(self):
        return self.ansi_fg()

    def __add__(self, other):
        if isinstance(other, str):
            return self.ansi_fg() + other
        else:
            return self.ansi_fg() + str(other)

    def ansi_fg(self) -> str:
        return f"\033[{self.fg}m"

    def ansi_bg(self) -> str:
        return f"\033[{self.bg}m"


@dataclass
class _theme:    
    name: str
    BACKGROUND: RGB
    DEFAULT: RGB
    
    MUTED: RGB
    ERROR: RGB
    WARNING: RGB
    SUCCESS: RGB
    
    USER: RGB
    PICO: RGB
    FOCUSED: RGB
    
    def reset(self) -> str:
        """reset to theme bg + fg colors"""
        
        if pico_cfg.config.ui_use_bg_color:
            return self.BACKGROUND.ansi_bg() + self.DEFAULT.ansi_fg()
        else:
            return "\033[0m" + self.DEFAULT.ansi_fg()
        
        # return self.BACKGROUND.ansi_bg() + self.DEFAULT.ansi_fg()
    
    def get_bg(self):
        """Get background color respecting ui_use_bg_color config setting."""
        from pico_chat import pico_cfg
        if pico_cfg.config.ui_use_bg_color:
            return self.BACKGROUND
        return None
    
default = _theme(
    name="default",
    BACKGROUND  = RGB("#1E1E1E"),   # Dark gray (VS Code dark background)
    DEFAULT     = RGB("#D4D4D4"),   # Light gray (readable text)
    
    MUTED       = RGB("#808080"),   # Medium gray
    ERROR       = RGB("#F48771"),   # Soft red
    WARNING     = RGB("#CCA700"),   # Amber/gold
    SUCCESS     = RGB("#89D185"),   # Soft green
    
    USER        = RGB("#4EC9B0"),   # Cyan/teal
    PICO        = RGB("#569CD6"),   # Blue
    FOCUSED     = RGB("#DCDCAA"),   # Yellow-beige
)

# Terminal-native theme — reuses the user's own terminal color palette.
# No hardcoded RGB: colors are the standard 8/16 ANSI slots so they
# automatically match whatever the user has configured in their terminal.
terminal = _theme(
    name="terminal",
    BACKGROUND  = ANSIColor(fg=39, bg=49),  # terminal default fg/bg
    DEFAULT     = ANSIColor(fg=39),         # default fg
    MUTED       = ANSIColor(fg=90),         # bright black (dark gray)
    ERROR       = ANSIColor(fg=91),         # bright red
    WARNING     = ANSIColor(fg=33),         # yellow  (maps to user's yellow)
    SUCCESS     = ANSIColor(fg=32),         # green   (maps to user's green)
    USER        = ANSIColor(fg=32),         # green
    PICO        = ANSIColor(fg=36),         # cyan    (maps to user's cyan)
    FOCUSED     = ANSIColor(fg=33),         # bright yellow
)

THEMES = {
    "default":  default,
    "terminal": terminal,
}

theme: _theme = terminal


def set_theme(name: str):
    """Switch the active theme by name. Unknown names fall back to 'default'."""
    global theme
    theme = THEMES.get(name, default)
