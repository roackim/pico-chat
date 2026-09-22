"""OpenRouter account commands."""

from __future__ import annotations

import os
from typing import List, Tuple

from pico_chat.ui.tui.msg_types import SysMsgError

from .base import ChatUIProtocol, Command


async def fetch_openrouter_balance() -> Tuple[bool, str, dict]:
    """Return ``(ok, error_message, balance_dict)`` for the account."""
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return False, (
            "OpenRouter API key not found.\n"
            "Set environment variable: export OPENROUTER_API_KEY=sk-or-..."
        ), {}

    import httpx

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
        if response.status_code != 200:
            return False, f"OpenRouter API error: HTTP {response.status_code}", {}
        data = response.json().get("data", {})
        total_credits = data.get("total_credits", 0.0)
        total_usage = data.get("total_usage", 0.0)
        return True, "", {
            "total_credits": total_credits,
            "total_usage": total_usage,
            "remaining": total_credits - total_usage,
        }
    except Exception as e:
        return False, f"Failed to fetch balance: {e}", {}


async def openrouter_balance(ui: ChatUIProtocol, args: List[str]):
    # Balance is transient account information, so keep it in a modal
    # rather than adding a permanent chat-history message.
    ui.show_popup("OpenRouter balance", "Fetching balance...")

    ok, message, balance = await fetch_openrouter_balance()
    if not ok:
        ui.show_popup("OpenRouter balance", message)
        return

    remaining = balance["remaining"]
    if remaining > 5:
        status = "healthy"
    elif remaining > 1:
        status = "low"
    else:
        status = "critical"

    content = (
        f"Status           : {status}\n"
        f"Remaining        : ${remaining:.4f}\n"
        f"Total credits    : ${balance['total_credits']:.4f}\n"
        f"Total usage      : ${balance['total_usage']:.4f}"
    )
    ui.show_popup("OpenRouter balance", content)


class OpenRouterCommand(Command):
    def __init__(self):
        super().__init__(
            "openrouter", "OpenRouter account utilities",
            subcommands={
                "balance": Command("balance", "Show OpenRouter account credit balance",
                                   handler=openrouter_balance),
            },
        )

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            help_text = "Usage: /openrouter <subcommand>\n\nSubcommands:\n"
            for name, cmd in sorted(self.subcommands.items()):
                help_text += f"  {name.ljust(10)} - {cmd.description}\n"
            ui.chat_history_panel.add_message(help_text.rstrip(), msg_type=SysMsgError())
        else:
            subcmd_name = args[0].lower()
            if subcmd_name in self.subcommands:
                await self.subcommands[subcmd_name].execute(ui, args[1:])
            else:
                ui.chat_history_panel.add_message(
                    f"Unknown subcommand: {subcmd_name}\n"
                    f"Available: {', '.join(sorted(self.subcommands.keys()))}",
                    msg_type=SysMsgError(),
                )


__all__ = ["OpenRouterCommand", "openrouter_balance", "fetch_openrouter_balance"]
