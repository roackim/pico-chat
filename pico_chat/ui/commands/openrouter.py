"""OpenRouter account commands."""

from __future__ import annotations

from typing import List

from pico_chat.ui.tui.msg_types import SysMsgError

from .base import ChatUIProtocol, Command


class OpenRouterBalanceCommand(Command):
    def __init__(self):
        super().__init__("balance", "Show OpenRouter account credit balance")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.server_service import ServerService

        # Balance is transient account information, so keep it in a modal
        # rather than adding a permanent chat-history message.
        ui.show_popup("OpenRouter balance", "Fetching balance...")

        svc = ServerService()
        ok, message, balance = await svc.get_openrouter_balance()

        if not ok:
            ui.show_popup("OpenRouter balance", message)
            return

        if balance.remaining > 5:
            status = "healthy"
        elif balance.remaining > 1:
            status = "low"
        else:
            status = "critical"

        content = (
            f"Status           : {status}\n"
            f"Remaining        : ${balance.remaining:.4f}\n"
            f"Total credits    : ${balance.total_credits:.4f}\n"
            f"Total usage      : ${balance.total_usage:.4f}"
        )
        ui.show_popup("OpenRouter balance", content)


class OpenRouterCommand(Command):
    def __init__(self):
        subcommands = {
            "balance": OpenRouterBalanceCommand(),
        }
        super().__init__("openrouter", "OpenRouter account utilities", subcommands=subcommands)

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


__all__ = ["OpenRouterCommand", "OpenRouterBalanceCommand"]
