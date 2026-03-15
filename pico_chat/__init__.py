"""Pico-chat: Self-Hosted AI Code Agent.

A CLI chat app for self-hosted LLM agents with native tool calling support.
"""

__version__ = "0.2.0"

from pico_chat.config import Config, get_config
from pico_chat.harness.harness import Harness, get_harness

__all__ = [
    "Config",
    "get_config",
    "Harness",
    "get_harness",
]
