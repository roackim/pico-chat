from typing import Any, Dict, List, Optional, Protocol
import asyncio
import json
import subprocess
import os

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

class CompactCommand(Command):
    def __init__(self):
        super().__init__("compact", "Compact context with an LLM summary marker")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if args:
            ui.chat_history_panel.add_message(
                "Usage: /compact",
                msg_type=SysMsgError()
            )
            return

        if not hasattr(ui.agent, 'compact_history'):
            ui.chat_history_panel.add_message(
                "Compaction is not supported by this agent.",
                msg_type=SysMsgError()
            )
            return

        placeholder = ui.chat_history_panel.add_message(
            "Compacting history...",
            msg_type=SysMsg(),
            title="compact",
        )

        try:
            result = await ui.agent.compact_history()

            if not result.get("ok"):
                compact_msg = ui.chat_history_panel.new_message(
                    result.get("message", "Compaction skipped."),
                    msg_type=SysMsg(),
                    title="compact",
                )
                ui.chat_history_panel.replace_message(placeholder, compact_msg)
                return

            compact_msg = ui.chat_history_panel.new_message(
                (
                    f"Compaction complete: {result['compacted_messages']} messages summarized\n"
                    f"Inserted marker: {result['message_id']}\n"
                    f"Summary size: {result['summary_chars']:,} chars"
                ),
                msg_type=SysMsg(),
                title="compact",
            )
            ui.chat_history_panel.replace_message(placeholder, compact_msg)

        except Exception as e:
            error_msg = ui.chat_history_panel.new_message(
                f"Compaction failed: {e}",
                msg_type=SysMsgError(),
                title="compact",
            )
            ui.chat_history_panel.replace_message(placeholder, error_msg)

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


class ResumeCommand(Command):
    def __init__(self):
        super().__init__("resume", "Resume a paused generation")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if hasattr(ui, 'handle_resume_action'):
            ui.handle_resume_action(None)
        else:
            ui.chat_history_panel.add_message("Resume not supported.", msg_type=SysMsg())


class PrefillCommand(Command):
    def __init__(self):
        super().__init__("prefill", "Submit a message and pause for thinking prefill editing")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        user_text = " ".join(args).strip()
        if not user_text:
            ui.chat_history_panel.add_message(
                "Usage: /prefill <message>  — submits the message and pauses so you can edit the thinking prefill before generation starts.",
                msg_type=SysMsg()
            )
            return
        if hasattr(ui, 'handle_prefill_command'):
            ui.handle_prefill_command(user_text)
        else:
            ui.chat_history_panel.add_message("Prefill not supported.", msg_type=SysMsg())

class StatusCommand(Command):
    def __init__(self):
        super().__init__("status", "Show system and connection status")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        # Show placeholder while checking status
        placeholder = ui.chat_history_panel.add_message(
            "Checking server status...",
            msg_type=SysMsg(),
            title="status",
        )
        
        # Get actual status (may take time if server is unreachable)
        status = await ui.agent.get_status()
        
        # Replace placeholder with actual status
        status_msg = ui.chat_history_panel.new_message(
            self.format_status(status),
            msg_type=SysMsg(),
            title="status",
        )
        ui.chat_history_panel.replace_message(placeholder, status_msg)
        
        logger = logging.getLogger("tui")
        logger.info(f"Server status online: {status['online']}")
        
    
    @staticmethod
    def format_status(status: Dict[str, Any]) -> str:
        status_color = theme.SUCCESS if status["online"] else theme.ERROR
        status_text = "online" if status["online"] else "offline"
        
        color = str(theme.WARNING)
        reset = theme.reset()
        msg  = color + f"Server           : {reset}{status['server_name']} ({status['server_type']})\n"
        msg += color + f"URL              : {reset}{status['base_url']}\n"
        msg += color + f"Status           : {reset}{status_color}{status_text}{reset}\n"
        
        if status_text == "online":
            msg += color + f"Model            : {reset}{status['model']}\n"
            msg += color + f"Context Window   : {reset}{status['context_window']}\n"

            memory_items = status.get("memory_items", 0)
            memory_tokens = status.get("memory_tokens", 0)
            if memory_items == 0:
                msg += color + f"Memory           : {reset}empty\n"
            else:
                msg += color + f"Memory           : {reset}{memory_items} items ({memory_tokens} tokens)\n"
            
            # Add context pressure info if available
            if status.get('context_used') is not None and status.get('context_max') is not None:
                used = status['context_used']
                max_tokens = status['context_max']
                percentage = status.get('context_percentage', 0.0)
                
                # Color code the percentage based on pressure
                if percentage < 50:
                    pressure_color = theme.SUCCESS
                elif percentage < 75:
                    pressure_color = theme.WARNING
                else:
                    pressure_color = theme.ERROR
                
                msg += color + f"Context Usage    : {reset}{used:,} / {max_tokens:,} tokens "
                msg += f"({pressure_color}{percentage:.1f}%{reset})\n"
        
        return msg


class ServerAddCommand(Command):
    def __init__(self):
        super().__init__("add", "Add a named LLM server configuration")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        """
        Add a named server configuration.
        Usage: /server add <name> <type> <model/url> [provider]
        Examples:
          /server add my-claude openrouter anthropic/claude-3.5-sonnet
          /server add my-claude openrouter anthropic/claude-3.5-sonnet Anthropic
          /server add local llamacpp http://localhost:8080/v1
        """
        if len(args) < 3:
            command_text = "/server add " + " ".join(args) if args else "/server add"
            ui.chat_history_panel.add_message(
                "Usage: /server add <name> <type> <model/url> [provider]\n\n"
                "Examples:\n"
                "  /server add my-claude openrouter anthropic/claude-3.5-sonnet\n"
                "  /server add my-claude openrouter anthropic/claude-3.5-sonnet Anthropic\n"
                "  /server add local llamacpp http://localhost:8080/v1\n\n"
                "For OpenRouter, optional provider routes to a specific inference provider.\n"
                "Common providers: Anthropic, OpenAI, DeepInfra, Together, Fireworks",
                msg_type=SysMsgError(),
                command_text=command_text
            )
            return

        server_name = args[0]
        server_type = args[1].lower()
        model_or_url = args[2]
        provider = args[3] if len(args) > 3 else None

        if server_type == "openrouter":
            await self._add_openrouter(ui, model_or_url, server_name, provider, args)
        elif server_type == "llamacpp":
            await self._add_llamacpp(ui, model_or_url, server_name, args)
        else:
            command_text = "/server add " + " ".join(args)
            ui.chat_history_panel.add_message(
                f"Unknown server type: {server_type}\n"
                "Supported types: openrouter, llamacpp",
                msg_type=SysMsgError(),
                command_text=command_text
            )
    
    async def _add_openrouter(self, ui: ChatUIProtocol, model_id: str, server_name: str, provider: str = None, args: list = None):
        """Add an OpenRouter server configuration.
        
        Args:
            model_id: Model ID like "anthropic/claude-3.5-sonnet"
            server_name: Custom name for this server config
            provider: Optional routing preference (e.g., "Anthropic", "DeepInfra")
            args: Original command args for error context
        """
        import httpx
        logger = logging.getLogger("tui")
        
        # Reconstruct command for error context
        command_text = "/server add " + " ".join(args) if args else "/server add"
        
        # Check for API key
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            ui.chat_history_panel.add_message(
                "OpenRouter API key not found.\n"
                "Set environment variable: export OPENROUTER_API_KEY=sk-or-...\n"
                "Get your key at: https://openrouter.ai/keys",
                msg_type=SysMsgError(),
                command_text=command_text
            )
            return
        
        placeholder = ui.chat_history_panel.add_message(
            f"Validating OpenRouter model {model_id}...",
            msg_type=SysMsg(),
            title="server"
        )
        
        try:
            from pico_chat.harness.llm_server_config import LLMServerConfig
            from pico_chat.harness.llm_server import create_server
            from pico_chat import pico_cfg
            import httpx
            
            # First, validate that the model exists in OpenRouter's catalog
            # and check provider if specified
            model_info = None
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://openrouter.ai/api/v1/models",
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        data = response.json()
                        models = data.get("data", [])
                        
                        # Find the specific model
                        for model in models:
                            if model.get("id") == model_id:
                                model_info = model
                                break
                        
                        if not model_info:
                            error_msg = ui.chat_history_panel.new_message(
                                f"Model '{model_id}' not found in OpenRouter catalog.\n\n"
                                "Browse available models at: https://openrouter.ai/models\n"
                                "Model IDs should be in format: provider/model-name\n"
                                "(e.g., anthropic/claude-3.5-sonnet, openai/gpt-4)",
                                msg_type=SysMsgError(),
                                title="server"
                            )
                            error_msg.command_text = command_text
                            ui.chat_history_panel.replace_message(placeholder, error_msg)
                            return
                        
                        # Validate provider if specified
                        if provider and model_info:
                            # Get supported providers from model info
                            supported_providers = model_info.get("supported_providers", [])
                            
                            # If the API provides provider info, validate against it
                            if supported_providers:
                                provider_ids = [p.get("id") if isinstance(p, dict) else p for p in supported_providers]
                                # Case-insensitive match
                                provider_lower = provider.lower()
                                valid_providers_lower = [p.lower() for p in provider_ids if p]
                                
                                if provider_lower not in valid_providers_lower:
                                    error_msg = ui.chat_history_panel.new_message(
                                        f"Provider '{provider}' is not supported for model '{model_id}'.\n\n"
                                        f"Supported providers: {', '.join(provider_ids)}\n\n"
                                        "Leave provider empty to use OpenRouter's default routing.",
                                        msg_type=SysMsgError(),
                                        title="server"
                                    )
                                    error_msg.command_text = command_text
                                    ui.chat_history_panel.replace_message(placeholder, error_msg)
                                    return
                            # else: API didn't provide provider info, trust the user's choice
                    else:
                        # Can't validate, but warn user
                        logger.warning(f"Could not fetch OpenRouter models list: HTTP {response.status_code}")
            except Exception as e:
                # Network error - can't validate, but continue (user might be offline but model might be valid)
                logger.warning(f"Failed to validate OpenRouter model: {e}")
            
            # Test connection with API key
            test_config = LLMServerConfig(
                name=server_name,
                type="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,  # Use the actual API key value
                model=model_id,
                max_context=None,
                timeout=5.0,
                retry_attempts=1,
                retry_delay=1.0,
                provider=provider
            )
            
            test_server = create_server(test_config)
            online = await test_server.check_connection()
            
            if not online:
                error_msg = ui.chat_history_panel.new_message(
                    f"Failed to connect to OpenRouter\n"
                    "Check your API key and internet connection.\n"
                    "Get your key at: https://openrouter.ai/keys",
                    msg_type=SysMsgError(),
                    title="server"
                )
                error_msg.command_text = command_text
                ui.chat_history_panel.replace_message(placeholder, error_msg)
                return
            
            # Save config only after successful connection test
            server_config = {
                "type": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "model": model_id,
                "timeout": 30.0,
                "retry_attempts": 3,
                "retry_delay": 2.0,
            }
            
            # Add provider routing if specified
            if provider:
                server_config["provider"] = provider
            
            pico_cfg.config.save_server(server_name, server_config, set_active=False)
            
            provider_msg = f"\nProvider: {provider}" if provider else ""
            success_msg = ui.chat_history_panel.new_message(
                f"Added server '{server_name}'\n"
                f"Type: OpenRouter\n"
                f"Model: {model_id}{provider_msg}\n\n"
                f"Use '/server use {server_name}' to activate",
                msg_type=SysMsg(),
                title="server"
            )
            ui.chat_history_panel.replace_message(placeholder, success_msg)
            
        except Exception as e:
            error_msg = ui.chat_history_panel.new_message(
                f"Error adding server: {e}",
                msg_type=SysMsgError(),
                title="server"
            )
            ui.chat_history_panel.replace_message(placeholder, error_msg)
    
    async def _add_llamacpp(self, ui: ChatUIProtocol, url: str, server_name: str, args: list = None):
        """Add a llamacpp server configuration.
        
        Args:
            url: Server URL
            server_name: Custom name for this server config
            args: Original command args for error context
        """
        # Normalize URL
        if not url.startswith("http"):
            url = f"http://{url}"
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        
        placeholder = ui.chat_history_panel.add_message(
            f"Testing connection to {url}...",
            msg_type=SysMsg(),
            title="server"
        )
        
        try:
            from pico_chat.harness.llm_server_config import LLMServerConfig
            from pico_chat.harness.llm_server import create_server
            from pico_chat import pico_cfg
            
            # Test connection first
            test_config = LLMServerConfig(
                name=server_name,
                type="llamacpp",
                base_url=url,
                api_key="EMPTY",
                model=None,
                max_context=None,
                timeout=2.0,
                retry_attempts=3,
                retry_delay=1.0
            )
            
            test_server = create_server(test_config)
            online = await test_server.check_connection()
            
            if not online:
                error_msg = ui.chat_history_panel.new_message(
                    f"Failed to connect to {url}\n"
                    "Server is not responding. Check the URL and ensure the server is running.",
                    msg_type=SysMsgError(),
                    title="server"
                )
                ui.chat_history_panel.replace_message(placeholder, error_msg)
                return
            
            # Get model info
            model_name = await test_server.get_model_name()
            context_window = await test_server.get_context_window()
            
            # Save config
            server_config = {
                "type": "llamacpp",
                "base_url": url,
                "api_key": "EMPTY",
                "timeout": 30.0,
                "retry_attempts": 3,
                "retry_delay": 2.0,
            }
            
            pico_cfg.config.save_server(server_name, server_config, set_active=False)
            
            success_msg = ui.chat_history_panel.new_message(
                f"Added server '{server_name}'\n"
                f"Type: llamacpp\n"
                f"URL: {url}\n"
                f"Model: {model_name}\n"
                f"Context: {context_window:,} tokens\n\n"
                f"Use '/server use {server_name}' to activate",
                msg_type=SysMsg(),
                title="server"
            )
            ui.chat_history_panel.replace_message(placeholder, success_msg)
            
        except Exception as e:
            error_msg = ui.chat_history_panel.new_message(
                f"Error adding server: {e}",
                msg_type=SysMsgError(),
                title="server"
            )
            ui.chat_history_panel.replace_message(placeholder, error_msg)


class ServerListCommand(Command):
    def __init__(self):
        super().__init__("list", "List all configured servers")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat import pico_cfg
        from pico_chat.ui.tui.colors import theme
        
        servers = pico_cfg.config.servers
        active = pico_cfg.config.active_server
        
        if not servers:
            ui.chat_history_panel.add_message(
                "No servers configured.\n\n"
                "Add a server with:\n"
                "  /server add <name> openrouter <model> [provider]\n"
                "  /server add <name> llamacpp <url>",
                msg_type=SysMsg()
            )
            return
        
        # Use compact, colorful one-line display
        color = str(theme.DEFAULT)
        muted = str(theme.MUTED)
        active_color = str(theme.SUCCESS)
        reset = theme.reset()
        
        msg = f"{color}Configured servers:{reset}\n\n"
        
        for name, config in sorted(servers.items()):
            server_type = config.get("type", "unknown")
            
            # Build single-line display
            # Format: name (type) - details
            if name == active:
                line = f"{active_color}{name}{reset}"
            else:
                line = f"{color}{name}{reset}"
            
            line += f" {muted}({server_type}){reset}"
            
            # Add type-specific details on same line
            if server_type == "openrouter":
                model = config.get("model", "unknown")
                provider = config.get("provider")
                if provider:
                    line += f" {muted}- {model} via {provider}{reset}"
                else:
                    line += f" {muted}- {model}{reset}"
            elif server_type == "llamacpp":
                url = config.get("base_url", "unknown")
                line += f" {muted}- {url}{reset}"
            
            msg += line + "\n"
        
        msg += f"\n{muted}Use '/server use <name>' to switch{reset}"
        
        ui.chat_history_panel.add_message(msg, msg_type=SysMsg())


class ServerUseCommand(Command):
    def __init__(self):
        super().__init__("use", "Switch to a different server configuration")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /server use <name>\n\n"
                "Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return
        
        server_name = args[0]
        
        from pico_chat import pico_cfg
        
        if server_name not in pico_cfg.config.servers:
            ui.chat_history_panel.add_message(
                f"Server '{server_name}' not found.\n\n"
                f"Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return
        
        try:
            # Update active server in config
            config_path = pico_cfg.get_config_path()
            import toml
            
            if config_path.exists():
                data = toml.load(config_path)
            else:
                data = {}
            
            if "settings" not in data:
                data["settings"] = {}
            data["settings"]["active_server"] = server_name
            
            with open(config_path, "w") as f:
                toml.dump(data, f)
            
            pico_cfg.config.active_server = server_name
            
            # Switch server at runtime
            from pico_chat.harness.llm_server_config import LLMServerConfig, get_server_config
            import os
            
            server_dict = pico_cfg.config.servers[server_name]
            server_type = server_dict.get("type", "unknown")
            
            # Get API key from environment variable if specified
            api_key = server_dict.get("api_key", "")
            api_key_env = server_dict.get("api_key_env")
            if api_key_env:
                api_key = os.getenv(api_key_env, api_key)
            
            new_config = LLMServerConfig(
                name=server_name,
                type=server_type,
                base_url=server_dict.get("base_url", "http://localhost:8080/v1"),
                api_key=api_key,
                model=server_dict.get("model"),
                max_context=server_dict.get("max_context"),
                timeout=server_dict.get("timeout", 30.0),
                retry_attempts=server_dict.get("retry_attempts", 3),
                retry_delay=server_dict.get("retry_delay", 2.0),
                provider=server_dict.get("provider"),
            )
            
            # Switch the server in the running harness
            ui.agent.switch_server(new_config)
            
            # Compact single-line message
            if server_type == "openrouter":
                model = server_dict.get("model", "unknown")
                provider = server_dict.get("provider")
                if provider:
                    msg = f"Switched to {server_name} (openrouter) - {model} via {provider}"
                else:
                    msg = f"Switched to {server_name} (openrouter) - {model}"
            elif server_type == "llamacpp":
                url = server_dict.get("base_url", "unknown")
                msg = f"Switched to {server_name} (llamacpp) - {url}"
            else:
                msg = f"Switched to {server_name} ({server_type})"
            
            ui.chat_history_panel.add_message(msg, msg_type=SysMsg())
            
        except Exception as e:
            ui.chat_history_panel.add_message(
                f"Error switching server: {e}",
                msg_type=SysMsgError()
            )


class ServerRemoveCommand(Command):
    def __init__(self):
        super().__init__("remove", "Remove a server configuration")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /server remove <name>\n\n"
                "Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return
        
        server_name = args[0]
        
        from pico_chat import pico_cfg
        
        if server_name not in pico_cfg.config.servers:
            ui.chat_history_panel.add_message(
                f"Server '{server_name}' not found.\n\n"
                f"Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return
        
        try:
            config_path = pico_cfg.get_config_path()
            import toml
            
            if config_path.exists():
                data = toml.load(config_path)
                
                if "servers" in data and server_name in data["servers"]:
                    # Check if this is the active server
                    is_active = (pico_cfg.config.active_server == server_name)
                    
                    # Remove the server
                    del data["servers"][server_name]
                    
                    # If it was active, switch to another server or clear active
                    switched_to = None
                    if is_active:
                        remaining_servers = list(data["servers"].keys())
                        if remaining_servers:
                            # Switch to the first remaining server
                            new_active = remaining_servers[0]
                            if "settings" not in data:
                                data["settings"] = {}
                            data["settings"]["active_server"] = new_active
                            pico_cfg.config.active_server = new_active
                            switched_to = new_active
                            
                            # Switch server in running harness
                            try:
                                from pico_chat.harness.llm_server_config import LLMServerConfig
                                import os
                                
                                server_dict = data["servers"][new_active]
                                server_type = server_dict.get("type", "unknown")
                                
                                # Get API key from environment variable if specified
                                api_key = server_dict.get("api_key", "")
                                api_key_env = server_dict.get("api_key_env")
                                if api_key_env:
                                    api_key = os.getenv(api_key_env, api_key)
                                
                                new_config = LLMServerConfig(
                                    name=new_active,
                                    type=server_type,
                                    base_url=server_dict.get("base_url", "http://localhost:8080/v1"),
                                    api_key=api_key,
                                    model=server_dict.get("model"),
                                    max_context=server_dict.get("max_context"),
                                    timeout=server_dict.get("timeout", 30.0),
                                    retry_attempts=server_dict.get("retry_attempts", 3),
                                    retry_delay=server_dict.get("retry_delay", 2.0),
                                    provider=server_dict.get("provider"),
                                )
                                
                                ui.agent.switch_server(new_config)
                            except Exception as e:
                                # If switch fails, just log it but don't fail the removal
                                import logging
                                logger = logging.getLogger("tui")
                                logger.warning(f"Failed to switch to new server after removal: {e}")
                        else:
                            # No servers left, clear active_server
                            if "settings" in data and "active_server" in data["settings"]:
                                del data["settings"]["active_server"]
                            pico_cfg.config.active_server = "llamacpp_default"
                    
                    # Save updated config
                    with open(config_path, "w") as f:
                        toml.dump(data, f)
                    
                    # Remove from runtime config
                    del pico_cfg.config.servers[server_name]
                    
                    # Build response message
                    msg = f"Removed server '{server_name}'"
                    if switched_to:
                        msg += f"\nSwitched to '{switched_to}'"
                    elif is_active:
                        msg += "\nNo servers configured"
                    
                    ui.chat_history_panel.add_message(msg, msg_type=SysMsg())
                else:
                    ui.chat_history_panel.add_message(
                        f"Server '{server_name}' not found in config file",
                        msg_type=SysMsgError()
                    )
            else:
                ui.chat_history_panel.add_message(
                    "Config file not found",
                    msg_type=SysMsgError()
                )
                
        except Exception as e:
            ui.chat_history_panel.add_message(
                f"Error removing server: {e}",
                msg_type=SysMsgError()
            )


class ServerInfoCommand(Command):
    def __init__(self):
        super().__init__("info", "Show full details for a server configuration")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /server info <name>\n\n"
                "Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return

        server_name = args[0]
        from pico_chat import pico_cfg
        from pico_chat.ui.tui.colors import theme

        servers = pico_cfg.config.servers
        if server_name not in servers:
            ui.chat_history_panel.add_message(
                f"Server '{server_name}' not found.\n\n"
                "Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return

        cfg = servers[server_name]
        active = pico_cfg.config.active_server
        color = str(theme.WARNING)
        reset = theme.reset()

        msg = color + f"Name             : {reset}{server_name}"
        if server_name == active:
            msg += f" {color}(active){reset}"
        msg += "\n"
        msg += color + f"Type             : {reset}{cfg.get('type', 'unknown')}\n"

        server_type = cfg.get("type", "")
        if server_type == "openrouter":
            msg += color + f"Model            : {reset}{cfg.get('model', 'unknown')}\n"
            provider = cfg.get("provider")
            if provider:
                msg += color + f"Provider         : {reset}{provider}\n"
            msg += color + f"Base URL         : {reset}{cfg.get('base_url', 'unknown')}\n"
            api_key_env = cfg.get("api_key_env", "")
            msg += color + f"API Key Env      : {reset}{api_key_env}\n"
        elif server_type == "llamacpp":
            msg += color + f"Base URL         : {reset}{cfg.get('base_url', 'unknown')}\n"

        msg += color + f"Timeout          : {reset}{cfg.get('timeout', 30.0)}s\n"
        msg += color + f"Retry Attempts   : {reset}{cfg.get('retry_attempts', 3)}\n"
        msg += color + f"Retry Delay      : {reset}{cfg.get('retry_delay', 2.0)}s\n"
        if cfg.get("max_context"):
            msg += color + f"Max Context      : {reset}{cfg['max_context']:,} tokens\n"

        ui.chat_history_panel.add_message(msg.rstrip(), msg_type=SysMsg(), title="server")


class ServerCommand(Command):
    def __init__(self):
        _remove = ServerRemoveCommand()
        subcommands = {
            "add":    ServerAddCommand(),
            "list":   ServerListCommand(),
            "use":    ServerUseCommand(),
            "info":   ServerInfoCommand(),
            "remove": _remove,
            "rm":     _remove,
        }
        super().__init__("server", "Manage LLM server configurations", subcommands=subcommands)

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            help_text = "Usage: /server <subcommand> [options]\n\nSubcommands:\n"
            for name, cmd in sorted(self.subcommands.items()):
                help_text += f"  {name.ljust(10)} - {cmd.description}\n"
            # help_text += "\nExamples:\n"
            # help_text += "  /server add openrouter deepseek/deepseek-chat open-deepseek\n"
            # help_text += "  /server add llamacpp http://localhost:8080/v1 local-llama\n"
            # help_text += "  /server list\n"
            # help_text += "  /server use open-deepseek"
            ui.chat_history_panel.add_message(help_text, msg_type=SysMsgError())
        else:
            subcmd_name = args[0].lower()
            if subcmd_name in self.subcommands:
                await self.subcommands[subcmd_name].execute(ui, args[1:])
            else:
                ui.chat_history_panel.add_message(
                    f"Unknown subcommand: {subcmd_name}\n"
                    f"Available: {', '.join(sorted(self.subcommands.keys()))}",
                    msg_type=SysMsgError()
                )


class ToolsCommand(Command):
    def __init__(self):
        super().__init__("tools", "Show available tools and their permissions")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.tool_permissions import permissions

        available_tools: List[str] = []
        if hasattr(ui.agent, 'tools_map') and isinstance(ui.agent.tools_map, dict):
            available_tools = sorted(ui.agent.tools_map.keys())

        if not available_tools:
            available_tools = ["read", "write", "patch", "run", "memorize", "forget"]

        def permission_label(tool_name: str) -> str:
            if tool_name == "read":
                return f"inside={permissions.read.inside_repo} outside={permissions.read.outside_repo}"
            if tool_name == "write":
                return f"inside={permissions.write.inside_repo} outside={permissions.write.outside_repo}"
            if tool_name == "patch":
                return f"inside={permissions.patch.inside_repo} outside={permissions.patch.outside_repo}"
            if tool_name == "run":
                return (
                    f"allow={len(permissions.run.allow)} ask={len(permissions.run.ask)} "
                    f"deny={len(permissions.run.deny)} others={permissions.run.others} chain={permissions.run.chain_policy}"
                )
            if tool_name in ("memorize", "forget"):
                return permissions.memory
            return "unknown"

        lines = [f"profile: {permissions.name}"]
        for tool_name in available_tools:
            lines.append(f"{tool_name.ljust(10)} - {permission_label(tool_name)}")

        ui.chat_history_panel.add_message(
            "\n".join(lines),
            msg_type=SysMsg(),
            title="tools",
        )

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
        super().__init__("get_context", "Display and copy current LLM context")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        logger = logging.getLogger("tui")
        
        try:
            # Get the exact context that would be sent to the LLM
            context = await ui.agent.get_current_context()
            
            # Format as pretty JSON for clipboard
            context_json = json.dumps(context, indent=2, ensure_ascii=False)
            
            # Create human-readable formatted display
            formatted_lines = ["=" * 80]
            formatted_lines.append("CURRENT LLM CONTEXT")
            formatted_lines.append("=" * 80)
            formatted_lines.append("")
            
            for idx, msg in enumerate(context, 1):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                
                # Header for each message
                formatted_lines.append(f"[{idx}/{len(context)}] {role.upper()}")
                formatted_lines.append("-" * 80)
                
                # Content with proper newlines (not escaped)
                # The content is already a string, just add it directly
                formatted_lines.append(content)
                formatted_lines.append("")
            
            formatted_lines.append("=" * 80)
            formatted_lines.append(f"Total messages: {len(context)}")
            formatted_lines.append(f"Total characters: {len(context_json):,}")
            formatted_lines.append("=" * 80)
            
            formatted_display = "\n".join(formatted_lines)
            
            # Display in chat UI
            ui.chat_history_panel.add_message(formatted_display, msg_type=SysMsg())
            
            # Try to copy JSON to clipboard using various methods
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
                ui.chat_history_panel.add_message(
                    "✓ JSON also copied to clipboard",
                    msg_type=SysMsg()
                )
            else:
                logger.warning("No clipboard utility found")
                ui.chat_history_panel.add_message(
                    "⚠ Could not copy to clipboard (install xclip, xsel, or wl-copy)",
                    msg_type=SysMsg()
                )
                
        except Exception as e:
            logger.error(f"Error getting context: {e}", exc_info=True)
            ui.chat_history_panel.add_message(f"Failed to get context: {e}", msg_type=SysMsgError())

class DebugGetMemoryCommand(Command):
    def __init__(self):
        super().__init__("get_memory", "Copy current memory state to clipboard")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        logger = logging.getLogger("tui")
        
        try:
            # Get the current memory state
            if not hasattr(ui.agent, 'memory'):
                ui.chat_history_panel.add_message(
                    "Memory system not available",
                    msg_type=SysMsgError()
                )
                return
            
            memory = ui.agent.memory
            
            if not memory:
                ui.chat_history_panel.add_message(
                    "Memory is empty",
                    msg_type=SysMsg()
                )
                return
            
            # Format as pretty JSON (list of memory items)
            memory_items = list(memory.values())
            memory_json = json.dumps(memory_items, indent=2, ensure_ascii=False)
            
            # Try to copy to clipboard using various methods
            copied = False
            
            # Method 1: Try xclip (X11)
            try:
                subprocess.run(['xclip', '-selection', 'clipboard'], 
                             input=memory_json.encode(), 
                             check=True, 
                             stderr=subprocess.DEVNULL)
                copied = True
                logger.info("Memory copied to clipboard (xclip)")
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
            
            # Method 2: Try xsel (X11 alternative)
            if not copied:
                try:
                    subprocess.run(['xsel', '--clipboard', '--input'], 
                                 input=memory_json.encode(), 
                                 check=True,
                                 stderr=subprocess.DEVNULL)
                    copied = True
                    logger.info("Memory copied to clipboard (xsel)")
                except (FileNotFoundError, subprocess.CalledProcessError):
                    pass
            
            # Method 3: Try wl-copy (Wayland)
            if not copied:
                try:
                    subprocess.run(['wl-copy'], 
                                 input=memory_json.encode(), 
                                 check=True,
                                 stderr=subprocess.DEVNULL)
                    copied = True
                    logger.info("Memory copied to clipboard (wl-copy)")
                except (FileNotFoundError, subprocess.CalledProcessError):
                    pass
            
            if copied:
                item_count = len(memory_items)
                total_tokens = sum(item["metadata"]["token_size"] for item in memory_items)
                char_count = len(memory_json)
                ui.chat_history_panel.add_message(
                    f"Copied {item_count} memory items ({total_tokens} tokens, {char_count:,} characters) to clipboard",
                    msg_type=SysMsg()
                )
            else:
                logger.warning("No clipboard utility found")
                ui.chat_history_panel.add_message(
                    "Could not copy: no clipboard utility found\nInstall xclip, xsel, or wl-copy",
                    msg_type=SysMsgError()
                )
                
        except Exception as e:
            logger.error(f"Error getting memory: {e}", exc_info=True)
            ui.chat_history_panel.add_message(f"Failed to get memory: {e}", msg_type=SysMsgError())


class DebugLogCommand(Command):
    def __init__(self):
        super().__init__("log", "Show recent log messages (default: 50, max: 200)")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        """Show recent log messages from the debug panel."""
        # Parse number of lines to show
        num_lines = 50  # default
        if args:
            try:
                num_lines = int(args[0])
                num_lines = max(1, min(200, num_lines))  # Clamp to 1-200
            except ValueError:
                ui.chat_history_panel.add_message(
                    f"Invalid number: {args[0]}. Usage: /debug log [lines]",
                    msg_type=SysMsgError()
                )
                return
        
        # Get logs from debug panel
        if hasattr(ui, 'debug_panel') and hasattr(ui.debug_panel, 'lines'):
            lines = list(ui.debug_panel.lines)
            
            if not lines:
                ui.chat_history_panel.add_message(
                    "No log messages available.",
                    msg_type=SysMsg()
                )
                return
            
            # Get last N lines
            recent_lines = lines[-num_lines:]
            
            # Format output
            header = f"Last {len(recent_lines)} log messages:"
            separator = "─" * 80
            log_text = f"{header}\n{separator}\n" + "\n".join(recent_lines)
            
            ui.chat_history_panel.add_message(
                log_text,
                msg_type=SysMsg(),
                title="logs"
            )
        else:
            ui.chat_history_panel.add_message(
                "Debug panel not available.",
                msg_type=SysMsgError()
            )


class DebugCommand(Command):
    def __init__(self):
        subcommands = {
            "panel": DebugPanelCommand(),
            "get_context": DebugGetContextCommand(),
            "get_memory": DebugGetMemoryCommand(),
            "log": DebugLogCommand(),
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

class PermissionsCommand(Command):
    def __init__(self):
        super().__init__("permissions", "Show current permission configuration")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness import tool_permissions
        
        perm = tool_permissions.permissions
        
        output = f"Current Profile: {perm.name}\n"
        output += "=" * 60 + "\n\n"
        
        # File permissions
        output += "File Permissions:\n"
        output += "-" * 60 + "\n"
        output += f"  read  (inside repo):  {perm.read.inside_repo}\n"
        output += f"  read  (outside repo): {perm.read.outside_repo}\n"
        output += f"  write (inside repo):  {perm.write.inside_repo}\n"
        output += f"  write (outside repo): {perm.write.outside_repo}\n"
        output += f"  patch (inside repo):  {perm.patch.inside_repo}\n"
        output += f"  patch (outside repo): {perm.patch.outside_repo}\n\n"
        
        # Run permissions
        output += "Run Permissions:\n"
        output += "-" * 60 + "\n"
        output += f"  others policy:     {perm.run.others}\n"
        output += f"  chain policy:      {perm.run.chain_policy}\n"
        output += f"  use container:     {perm.run.use_container}\n"
        output += f"  container network: {perm.run.container_network}\n\n"
        
        # Command lists
        output += f"  ALLOW commands ({len(perm.run.allow)}):\n"
        if perm.run.allow:
            allow_sorted = sorted(perm.run.allow)
            for i in range(0, len(allow_sorted), 8):
                chunk = allow_sorted[i:i+8]
                output += f"    {', '.join(chunk)}\n"
        else:
            output += "    (none)\n"
        output += "\n"
        
        output += f"  ASK commands ({len(perm.run.ask)}):\n"
        if perm.run.ask:
            ask_sorted = sorted(perm.run.ask)
            for i in range(0, len(ask_sorted), 8):
                chunk = ask_sorted[i:i+8]
                output += f"    {', '.join(chunk)}\n"
        else:
            output += "    (none)\n"
        output += "\n"
        
        output += f"  DENY commands ({len(perm.run.deny)}):\n"
        if perm.run.deny:
            deny_sorted = sorted(perm.run.deny)
            for i in range(0, len(deny_sorted), 8):
                chunk = deny_sorted[i:i+8]
                output += f"    {', '.join(chunk)}\n"
        else:
            output += "    (none)\n"
        output += "\n"
        
        # Dangerous patterns
        from pico_chat.harness.tool_permissions import CMD_DANGEROUS_PATTERNS
        output += "Dangerous Pattern Detection:\n"
        output += "-" * 60 + "\n"
        for cmd, patterns in sorted(CMD_DANGEROUS_PATTERNS.items()):
            output += f"  {cmd}: {', '.join(patterns)}\n"
        output += "\n"
        
        # Memory permissions
        output += f"Memory Operations: {perm.memory}\n"
        
        ui.chat_history_panel.add_message(
            output.rstrip(),
            msg_type=SysMsg(),
            title="permissions"
        )

class OpenRouterBalanceCommand(Command):
    def __init__(self):
        super().__init__("balance", "Show OpenRouter account credit balance")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        import httpx

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            ui.chat_history_panel.add_message(
                "OpenRouter API key not found.\n"
                "Set environment variable: export OPENROUTER_API_KEY=sk-or-...",
                msg_type=SysMsgError(),
            )
            return

        placeholder = ui.chat_history_panel.add_message(
            "Fetching OpenRouter balance...",
            msg_type=SysMsg(),
            title="openrouter",
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/credits",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )

            if response.status_code != 200:
                error_msg = ui.chat_history_panel.new_message(
                    f"OpenRouter API error: HTTP {response.status_code}",
                    msg_type=SysMsgError(),
                    title="openrouter",
                )
                ui.chat_history_panel.replace_message(placeholder, error_msg)
                return

            data = response.json().get("data", {})
            total_credits = data.get("total_credits", 0.0)
            total_usage = data.get("total_usage", 0.0)
            remaining = total_credits - total_usage

            color = str(theme.WARNING)
            reset = theme.reset()

            if remaining > 5:
                balance_color = theme.SUCCESS
            elif remaining > 1:
                balance_color = theme.WARNING
            else:
                balance_color = theme.ERROR

            msg  = color + f"Remaining        : {reset}{balance_color}${remaining:.4f}{reset}\n"
            msg += color + f"Total Credits    : {reset}${total_credits:.4f}\n"
            msg += color + f"Total Usage      : {reset}${total_usage:.4f}\n"

            result_msg = ui.chat_history_panel.new_message(
                msg.rstrip(),
                msg_type=SysMsg(),
                title="openrouter",
            )
            ui.chat_history_panel.replace_message(placeholder, result_msg)

        except Exception as e:
            error_msg = ui.chat_history_panel.new_message(
                f"Failed to fetch balance: {e}",
                msg_type=SysMsgError(),
                title="openrouter",
            )
            ui.chat_history_panel.replace_message(placeholder, error_msg)


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


class PwdCommand(Command):
    def __init__(self):
        super().__init__("pwd", "Show current workspace directory")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        workspace = ui.agent.workspace if hasattr(ui.agent, 'workspace') else "unknown"
        ui.chat_history_panel.add_message(workspace, msg_type=SysMsg(), title="pwd")


class CdCommand(Command):
    def __init__(self):
        super().__init__("cd", "Change workspace directory and rebuild context")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /cd <path>",
                msg_type=SysMsgError()
            )
            return

        path = " ".join(args)

        try:
            warnings = ui.agent.switch_workspace(path)
            workspace = ui.agent.workspace

            ui.chat_history_panel.add_message(
                workspace,
                msg_type=SysMsg(),
                title="cd"
            )

            from pico_chat.ui.tui.msg_types import SysMsgWarning
            for w in warnings:
                ui.chat_history_panel.add_message(w, msg_type=SysMsgWarning())

        except (ValueError, OSError, PermissionError) as e:
            ui.chat_history_panel.add_message(str(e), msg_type=SysMsgError())


# Command Registry
COMMANDS: Dict[str, Command] = {
    "help":        HelpCommand(),
    "clear":       ClearCommand(),
    "compact":     CompactCommand(),
    "exit":        ExitCommand(),
    "stop":        StopCommand(),
    "resume":      ResumeCommand(),
    "prefill":     PrefillCommand(),
    "status":      StatusCommand(),
    "server":      ServerCommand(),
    "tools":       ToolsCommand(),
    "debug":       DebugCommand(),
    "permissions": PermissionsCommand(),
    "openrouter":  OpenRouterCommand(),
    "cd":          CdCommand(),
    "pwd":         PwdCommand(),
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
            msg_type=SysMsgError(),
            command_text=text
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
