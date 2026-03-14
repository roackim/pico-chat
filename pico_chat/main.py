"""Main entry point for Open-Clank.

A TUI chat app for self-hosted LLM agents.
"""

import sys
import asyncio

from pico_chat.harness.harness import get_harness
from pico_chat.ui.chat import chatTUI


def main():
    """
    Main entry point for Open-Clank.
    Wrapps the clankTUI in an async event loop and handles keyboard interrupts gracefully.
    """
    # Initialize harness first
    print("Initializing Open-Clank Harness...")
    harness = get_harness()
    print() 
    
    try:
        tui = ClankTUI(harness)
        asyncio.run(tui.run())
    except KeyboardInterrupt:
        pass
    finally:
        harness.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
