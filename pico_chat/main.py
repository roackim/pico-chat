"""Main entry point for Pico-Chat

A TUI chat app for self-hosted LLM agents.
"""

import sys
import asyncio

from pico_chat.harness.harness import get_harness
from pico_chat.ui.app import chatTUI


def main():
    """
    Main entry point for Pico-Chat.
    Wrapps the chatTUI in an async event loop and handles keyboard interrupts gracefully.
    """
    # Initialize harness first
    print("Initializing Pico-Chat Harness...")
    harness = get_harness()
    print() 

    # Apply theme from config
    from pico_chat.ui.tui.colors import set_theme
    from pico_chat import pico_cfg
    set_theme(pico_cfg.config.ui_theme)

    tui = chatTUI(harness)
    try:
        asyncio.run(tui.run())
    except BaseExceptionGroup as group:
        # asyncio.TaskGroup wraps failures in an ExceptionGroup whose box-drawing
        # traceback format is noisy. Unwrap to the first real exception so the
        # terminal shows a clean, standard traceback.
        raise group.exceptions[0] from None
    return 0


if __name__ == "__main__":
    sys.exit(main())
