from typing import Any, Dict, List, Optional, Protocol
import asyncio
import json
import subprocess

from pico_chat.ui.tui.colors import RGB, theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError
from pico_chat import pico_cfg

import logging

class ChatUIProtocol(Protocol):
    agent: Any
    chat_history_panel: Any
    input_panel: Any
    compositor: Any

class Command:
    def __init__(self, name: str, description: str, subcommands: Optional[Dict[str, 'Command']] = None):
        self.name = name
        self.description = description
        self.subcommands = subcommands or {}

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        raise NotImplementedError
    
    def has_subcommands(self) -> bool:
        return len(self.subcommands) > 0

class HelpCommand(Command):
    def __init__(self):
        super().__init__("help", "Show available commands")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        help_text = ""
        
        for cmd in sorted(COMMANDS.values(), key=lambda x: x.name):
            if cmd.name.startswith("_"):
                continue
            help_text += f"/{cmd.name.ljust(8)} - {cmd.description}\n"
        
        ui.chat_history_panel.add_message(
            help_text.rstrip(), msg_type=SysMsg(), title="help"
        )

class ClearCommand(Command):
    def __init__(self):
        super().__init__("clear", "Clear chat history")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        ui.chat_history_panel.clear()
        if hasattr(ui.agent, 'clear_history'):
            ui.agent.clear_history()
        ui.chat_history_panel.add_message("Conversation cleared.", msg_type=SysMsg())

class ExitCommand(Command):
    def __init__(self):
        super().__init__("exit", "Close the application")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if ui.compositor:
            ui.compositor.running = False

class StopCommand(Command):
    def __init__(self):
        super().__init__("stop", "Stop current generation")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        # Check if stop_generation method exists (runtime check)
        if hasattr(ui, 'stop_generation'):
            if ui.stop_generation():
                # Message is already appended by the cancelled task handler
                pass
            else:
                ui.chat_history_panel.add_message("No active generation to stop.", msg_type=SysMsg())
        else:
            ui.chat_history_panel.add_message("Stop command not supported by this UI.", msg_type=SysMsg())

class StatusCommand(Command):
    def __init__(self):
        super().__init__("status", "Show system and connection status")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        status = await ui.agent.get_status()
 
        ui.chat_history_panel.add_message(
            self.format_status(status),
            msg_type=SysMsg(),
            title="status",
        )
        logger = logging.getLogger("tui")
        logger.info(f"Server status online: {status['online']}")
        
    
    @staticmethod
    def format_status(status: Dict[str, Any]) -> str:
        status_color = "\x1b[32m" if status["online"] else "\x1b[31m"
        status_text = "online" if status["online"] else "offline"
        
        color = str(theme.WARNING)
        reset = theme.reset()
        msg  = color + f"Server           : {reset}{status['server_name']} ({status['server_type']})\n"
        msg += color + f"URL              : {reset}{status['base_url']}\n"
        msg += color + f"Status           : {reset}{status_color}{status_text}\033[0m\n"
        
        if status_text == "online":
            msg += color + f"Model            : {reset}{status['model']}\n"
            msg += color + f"Context Window   : {reset}{status['context_window']}\n"
        
        return msg

class DebugPanelCommand(Command):
    def __init__(self):
        super().__init__("panel", "Toggle debug console visibility")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if hasattr(ui, 'toggle_debug_console'):
            ui.toggle_debug_console()
        else:
            ui.chat_history_panel.add_message("Debug console not supported.", msg_type=SysMsg())

class DebugGetContextCommand(Command):
    def __init__(self):
        super().__init__("get_context", "Copy current LLM context to clipboard")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        logger = logging.getLogger("tui")
        
        try:
            # Get the exact context that would be sent to the LLM
            context = await ui.agent.get_current_context()
            
            # Format as pretty JSON
            context_json = json.dumps(context, indent=2, ensure_ascii=False)
            
            # Try to copy to clipboard using various methods
            copied = False
            
            # Method 1: Try xclip (X11)
            try:
                subprocess.run(['xclip', '-selection', 'clipboard'], 
                             input=context_json.encode(), 
                             check=True, 
                             stderr=subprocess.DEVNULL)
                copied = True
                logger.info("Context copied to clipboard (xclip)")
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
            
            # Method 2: Try xsel (X11 alternative)
            if not copied:
                try:
                    subprocess.run(['xsel', '--clipboard', '--input'], 
                                 input=context_json.encode(), 
                                 check=True,
                                 stderr=subprocess.DEVNULL)
                    copied = True
                    logger.info("Context copied to clipboard (xsel)")
                except (FileNotFoundError, subprocess.CalledProcessError):
                    pass
            
            # Method 3: Try wl-copy (Wayland)
            if not copied:
                try:
                    subprocess.run(['wl-copy'], 
                                 input=context_json.encode(), 
                                 check=True,
                                 stderr=subprocess.DEVNULL)
                    copied = True
                    logger.info("Context copied to clipboard (wl-copy)")
                except (FileNotFoundError, subprocess.CalledProcessError):
                    pass
            
            if copied:
                msg_count = len(context)
                char_count = len(context_json)
                ui.chat_history_panel.add_message(
                    f"Copied {msg_count} messages ({char_count:,} characters) to clipboard",
                    msg_type=SysMsg()
                )
            else:
                logger.warning("No clipboard utility found")
                ui.chat_history_panel.add_message(
                    "Could not copy: no clipboard utility found\nInstall xclip, xsel, or wl-copy",
                    msg_type=SysMsgError()
                )
                
        except Exception as e:
            logger.error(f"Error getting context: {e}", exc_info=True)
            ui.chat_history_panel.add_message(f"Failed to get context: {e}", msg_type=SysMsgError())

class DebugCommand(Command):
    def __init__(self):
        subcommands = {
            "panel": DebugPanelCommand(),
            "get_context": DebugGetContextCommand(),
        }
        super().__init__("debug", "Debug utilities", subcommands=subcommands)

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            # Show error - missing subcommand
            help_text = "Missing subcommand. Available subcommands:\n"
            for name, cmd in sorted(self.subcommands.items()):
                help_text += f"  {name.ljust(15)} - {cmd.description}\n"
            ui.chat_history_panel.add_message(help_text.rstrip(), msg_type=SysMsgError())
        else:
            subcmd_name = args[0].lower()
            if subcmd_name in self.subcommands:
                await self.subcommands[subcmd_name].execute(ui, args[1:])
            else:
                ui.chat_history_panel.add_message(
                    f"Unknown subcommand: {subcmd_name}",
                    msg_type=SysMsgError()
                )

# Command Registry
COMMANDS: Dict[str, Command] = {
    "help":     HelpCommand(),
    "clear":    ClearCommand(),
    "exit":     ExitCommand(),
    "stop":     StopCommand(),
    "status":   StatusCommand(),
    "debug":    DebugCommand(),
}

async def handle_command(ui: ChatUIProtocol, text: str):
    parts = text.strip().split()
    if not parts:
        return
    
    cmd_name = parts[0][1:].lower() # Remove '/'
    args = parts[1:]
    
    if cmd_name in COMMANDS:
        await COMMANDS[cmd_name].execute(ui, args)
    else:
        ui.chat_history_panel.add_message(
            f"Unknown command: /{cmd_name}",
            msg_type=SysMsgError()
        )
        

def get_command_list() -> List[str]:
    """Get list of top-level commands."""
    return [cmd for cmd in COMMANDS.keys()]

def get_subcommand_list(command: str) -> List[str]:
    """Get list of subcommands for a given command."""
    if command in COMMANDS:
        cmd = COMMANDS[command]
        if cmd.has_subcommands():
            return list(cmd.subcommands.keys())
    return []
