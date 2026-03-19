import sys
import os
import tty
import termios
import shutil
import signal
import fcntl
import time
from dataclasses import dataclass
from typing import Optional, Callable

class ANSI:
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"
    ENABLE_MOUSE = "\033[?1000h\033[?1002h\033[?1015h\033[?1006h"
    DISABLE_MOUSE = "\033[?1006l\033[?1015l\033[?1002l\033[?1000l"
    ENABLE_BRACKETED_PASTE = "\033[?2004h"
    DISABLE_BRACKETED_PASTE = "\033[?2004l"
    CLEAR_SCREEN = "\033[2J"
    MOVE_HOME = "\033[H"
    RESET = "\033[0m"

    @staticmethod
    def move_to(row: int, col: int) -> str:
        return f"\033[{row};{col}H"

    @staticmethod
    def color_rgb_fg(r: int, g: int, b: int) -> str:
        return f"\033[38;2;{r};{g};{b}m"

    @staticmethod
    def color_rgb_bg(r: int, g: int, b: int) -> str:
        return f"\033[48;2;{r};{g};{b}m"

@dataclass
class MouseEvent:
    x: int
    y: int
    button: int  # 0=left, 1=middle, 2=right, 64=scroll_up, 65=scroll_down
    pressed: bool
    drag: bool = False

@dataclass
class PasteEvent:
    text: str

class Terminal:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.old_settings = None
        self.resized = False

    def __enter__(self):
        self.old_settings = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        sys.stdout.write(ANSI.HIDE_CURSOR + ANSI.ENABLE_MOUSE + ANSI.ENABLE_BRACKETED_PASTE)
        sys.stdout.flush()
        signal.signal(signal.SIGWINCH, self._handle_resize)
        return self

    def cleanup(self, clear_screen: bool = True):
        """Cleanup terminal state. Safe to call multiple times.
        
        Args:
            clear_screen: If False, skip clearing screen (useful for preserving error messages)
        """
        # 1. Reset colors, show cursor, disable mouse/paste
        # But conditionally clear the screen
        if clear_screen:
            sys.stdout.write(ANSI.RESET + ANSI.SHOW_CURSOR + ANSI.DISABLE_MOUSE + ANSI.DISABLE_BRACKETED_PASTE + ANSI.MOVE_HOME + ANSI.CLEAR_SCREEN)
        else:
            # Don't clear screen - preserve any error messages
            sys.stdout.write("\n" + ANSI.RESET + ANSI.SHOW_CURSOR + ANSI.DISABLE_MOUSE + ANSI.DISABLE_BRACKETED_PASTE)
        sys.stdout.flush()
        
        # 2. Restore signal handlers
        try:
            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        except Exception:
            pass
        
        # 3. Restore serial TTY settings (this effectively exits raw mode)
        if self.old_settings:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
                self.old_settings = None  # Mark as cleaned up
            except Exception:
                pass
        
        # 4. Final flush
        sys.stdout.write(ANSI.SHOW_CURSOR)
        sys.stdout.flush()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore terminal state and ensure cursor visibility."""
        # Only clear screen if exiting normally (no exception)
        self.cleanup(clear_screen=(exc_type is None))

    def _handle_resize(self, signum, frame):
        self.resized = True

    def get_size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size()
        return size.columns, size.lines

    def get_input(self) -> Optional[str | MouseEvent | PasteEvent]:
        # Non-blocking read
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        try:
            char = sys.stdin.read(1)
            if not char:
                return None
            
            if char == '\x1b':
                # Potential escape sequence
                seq = char
                start_time = time.time()
                while time.time() - start_time < 0.1:  # Increased timeout for paste detection
                    try:
                        c = sys.stdin.read(1)
                        if c:
                            seq += c
                            # Stop reading if we see common terminators
                            if seq.endswith(('m', 'M', 'A', 'B', 'C', 'D', 'H', 'F')):
                                break
                            # Specific check for Alt+Enter (\x1b\r or \x1b\n)
                            if seq in ('\x1b\r', '\x1b\n'):
                                break
                            if seq.endswith('~'):
                                # Check for bracketed paste start immediately
                                if seq == '\x1b[200~':
                                    return self._read_bracketed_paste()
                                break
                        else:
                            time.sleep(0.001)
                    except EOFError:
                        break
                    except:
                        break
                
                if seq.startswith('\x1b[<'):
                    return self._parse_mouse(seq)
                return seq
            return char
        except:
            return None
        finally:
            fcntl.fcntl(self.fd, fcntl.F_SETFL, flags)

    def _read_bracketed_paste(self) -> PasteEvent:
        """Read paste content until end marker. Temporarily uses blocking mode."""
        # Switch to blocking mode for reliable paste reading
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
        
        try:
            content = ""
            end_marker = '\x1b[201~'
            
            # Read character by character - simple and works for any size
            while True:
                char = sys.stdin.read(1)
                content += char
                
                # Check for end marker (only check last 6 chars for efficiency)
                if len(content) >= 6 and content[-6:] == end_marker:
                    return PasteEvent(content[:-6])
                
                # Safety limit
                if len(content) > 1_000_000:
                    return PasteEvent(content)
                    
        finally:
            # Restore non-blocking mode
            fcntl.fcntl(self.fd, fcntl.F_SETFL, flags)

    def _parse_mouse(self, seq: str) -> Optional[MouseEvent]:
        # \033[<Cb;Cx;CyM/m
        try:
            pressed = seq[-1] == 'M'
            parts = seq[3:-1].split(';')
            button = int(parts[0])
            x = int(parts[1])
            y = int(parts[2])
            drag = (button & 32) != 0
            if drag:
                button -= 32
            return MouseEvent(x, y, button, pressed, drag)
        except:
            return None
