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
    
    tui = chatTUI(harness)
    asyncio.run(tui.run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
