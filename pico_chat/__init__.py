"""Pico-chat: Self-Hosted AI Code Agent.

A CLI chat app for self-hosted LLM agents with native tool calling support.
"""

__version__ = "0.2.0"

from pico_chat import pico_cfg
from pico_chat.harness.harness import Harness, get_harness

__all__ = [
    "pico_cfg",
    "Harness",
    "get_harness",
]
