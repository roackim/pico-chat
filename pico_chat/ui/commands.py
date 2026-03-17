from typing import Any, Dict, List, Optional, Protocol
import asyncio

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
        # help_text = "\033[1mAvailable commands:\033[0m\n"
        help_text = "\033[0m"
        
        for cmd in sorted(COMMANDS.values(), key=lambda x: x.name):
            help_text += f"/{cmd.name.ljust(8)} - {cmd.description}\n"
        
        ui.chat_history_panel.add_system_message(help_text.rstrip(), title="help")
        ui.chat_history_panel.finalize_last_message()

class ClearCommand(Command):
    def __init__(self):
        super().__init__("clear", "Clear chat history")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        ui.chat_history_panel.clear()
        if hasattr(ui.agent, 'clear_history'):
            ui.agent.clear_history()
        ui.chat_history_panel.add_system_message("Conversation cleared.")
        ui.chat_history_panel.finalize_last_message()

class ExitCommand(Command):
    def __init__(self):
        super().__init__("exit", "Close the application")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if ui.compositor:
            ui.compositor.running = False

class StatusCommand(Command):
    def __init__(self):
        super().__init__("status", "Show system and connection status")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        is_online = await ui.agent.check_connection()
        status_text = "online" if is_online else "offline"
        color_code = "\x1b[32m" if is_online else "\x1b[31m"
        
        cur, max_ctx, perc = ui.agent.check_context() if hasattr(ui.agent, 'check_context') else ui.agent.estimate_context_usage()
        
        # Query the model name dynamically if possible, fall back to config
        if hasattr(ui.agent, 'get_model_name'):
            model_name = await ui.agent.get_model_name()
        else:
            model_name = getattr(ui.agent.config, 'model', 'unknown')
        
        report = (
            f"LLM Connectivity : {color_code}{status_text}\x1b[0m\n"
            f"Active Model     : {model_name}\n"
            f"Context Pressure : {perc:.1f}% | {cur/1024:.1f}k / {max_ctx/1024:.1f}k"
        )
        ui.chat_history_panel.add_system_message(report, title="status")
        ui.chat_history_panel.finalize_last_message()

# Command Registry
COMMANDS: Dict[str, Command] = {
    "help": HelpCommand(),
    "clear": ClearCommand(),
    "exit": ExitCommand(),
    "status": StatusCommand(),
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
        ui.chat_history_panel.add_system_message(f"Unknown command: /{cmd_name}", color=(255, 96, 96))
        ui.chat_history_panel.finalize_last_message()

def get_command_list() -> List[str]:
    return list(COMMANDS.keys())
