from typing import Any, Dict, List, Optional, Protocol
import asyncio

from pico_chat.ui.tui.colors import RGB, theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError
from pico_chat import pico_cfg

class ChatUIProtocol(Protocol):
    agent: Any
    chat_history_panel: Any
    input_panel: Any
    compositor: Any

class Command:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        raise NotImplementedError

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
        is_online = await ui.agent.check_connection()
        status_text = "online" if is_online else "offline"
        color_code = "\x1b[32m" if is_online else "\x1b[31m"
        
        cur, max_ctx, perc = ui.agent.check_context() if hasattr(ui.agent, 'check_context') else ui.agent.estimate_context_usage()
        
        # Query the model name dynamically if possible
        if hasattr(ui.agent, 'get_model_name'):
            try:
                model_name = await ui.agent.get_model_name()
            except Exception:
                model_name = 'unknown'
        else:
            model_name = 'unknown'
        
        # Get server info from agent's server object
        server_url = ui.agent.server.config.base_url if hasattr(ui.agent, 'server') else 'unknown'
        server_name = ui.agent.server.config.name if hasattr(ui.agent, 'server') else 'unknown'
        
        report = (
            f"Server           : {server_name}\n"
            f"URL              : {server_url}\n"
            f"LLM Connectivity : {color_code}{status_text}\u001b[0m\n"
            f"Active Model     : {model_name}\n"
            f"Context Pressure : {perc:.1f}% | {cur/1024:.1f}k / {max_ctx/1024:.1f}k"
        )
        ui.chat_history_panel.add_message(
            report,
            msg_type=SysMsg(),
            title="status",
            content_color=theme.DEFAULT
        )

class DebugCommand(Command):
    def __init__(self):
        super().__init__("_debug", "Toggle debug console")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if hasattr(ui, 'toggle_debug_console'):
            ui.toggle_debug_console()
        else:
            ui.chat_history_panel.add_message("Debug console not supported.", msg_type=SysMsg())

# Command Registry
COMMANDS: Dict[str, Command] = {
    "help":     HelpCommand(),
    "clear":    ClearCommand(),
    "exit":     ExitCommand(),
    "stop":     StopCommand(),
    "status":   StatusCommand(),
    "_debug":   DebugCommand(),
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
    return [cmd for cmd in COMMANDS.keys()] # if not cmd.startswith("_")]
