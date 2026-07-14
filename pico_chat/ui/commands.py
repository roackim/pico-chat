from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Union
import asyncio
import json
import subprocess
import os

from pico_chat.ui.tui.colors import RGB, theme
from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError
from pico_chat import pico_cfg

import logging

# ---------------------------------------------------------------------------
# Dynamic completion helpers (read from pico_cfg at call-time, always fresh)
# ---------------------------------------------------------------------------

def _server_name_completions() -> List[str]:
    """Return current server names from config (always fresh)."""
    return list(pico_cfg.config.servers.keys())


# Type for completion sources: a static list of strings, or a callable returning strings.
CompletionSource = Union[List[str], Callable[[], List[str]]]


@dataclass
class Param:
    """Defines a single command parameter for hints and autocomplete."""
    name: str                                          # Display name in hint (e.g. "NAME")
    completions: Optional[CompletionSource] = None     # Static list or callable
    path: bool = False                                 # If True, completions scans filesystem dirs
    required: bool = False                             # True → "NAME", False → "[NAME]"


class ChatUIProtocol(Protocol):
    agent: Any
    chat_history_panel: Any
    input_panel: Any
    compositor: Any
    
    def show_popup(self, title: str, content: str) -> None: ...
    def hide_popup(self) -> None: ...

class Command:
    def __init__(self, name: str, description: str,
                 subcommands: Optional[Dict[str, 'Command']] = None,
                 params: Optional[List[Param]] = None):
        self.name = name
        self.description = description
        self.subcommands = subcommands or {}
        self.params = params or []

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        raise NotImplementedError
    
    def has_subcommands(self) -> bool:
        return len(self.subcommands) > 0

    def resolve_command(self, parts: List[str]) -> tuple['Command', int]:
        """Walk the subcommand tree to find the deepest command and remaining arg index.

        Returns (command, arg_offset) where arg_offset is the index into `parts`
        where the command's own arguments begin.

        Example: parts = ["server", "add", "foo"]
          → (ServerAddCommand, 2)  because parts[2:] are ServerAddCommand's args
        """
        cmd = self
        offset = 0
        while cmd.has_subcommands() and offset < len(parts):
            sub_name = parts[offset]
            if sub_name in cmd.subcommands:
                cmd = cmd.subcommands[sub_name]
                offset += 1
            else:
                break
        return cmd, offset

    def get_completions(self, arg_index: int) -> List[str]:
        """Resolve completions for the argument at the given index.

        For commands with subcommands, the first arg (arg_index 0) is the
        subcommand name.  Subsequent args are resolved from the subcommand's
        own params list.
        """
        # If this command has subcommands, arg 0 = subcommand name
        if self.has_subcommands():
            if arg_index == 0:
                return sorted(self.subcommands.keys())
            # Caller must resolve subcommand and shift index
            return []

        # Leaf command — resolve from params
        if arg_index < 0 or arg_index >= len(self.params):
            return []

        p = self.params[arg_index]
        if p.path:
            return self._scan_dirs(p.completions)

        if p.completions is None:
            return []
        if callable(p.completions):
            return p.completions()
        return list(p.completions)

    @staticmethod
    def _scan_dirs(workspace: Any = None) -> List[str]:
        """Scan directories for path completion.

        Args:
            workspace: If provided (str or callable), scan this directory
                       instead of the current working directory.
        """
        base = None
        if workspace is not None:
            base = workspace() if callable(workspace) else workspace

        try:
            entries = []
            target = base or '.'
            with os.scandir(target) as it:
                for entry in sorted(it, key=lambda e: e.name.lower()):
                    if entry.name.startswith('.'):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=True):
                            entries.append(entry.name + '/')
                    except OSError:
                        pass
            return entries
        except OSError:
            return []

class HelpCommand(Command):
    def __init__(self):
        super().__init__("help", "Show available commands")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        help_lines = []
        
        for cmd in sorted(COMMANDS.values(), key=lambda x: x.name):
            if cmd.name.startswith("_"):
                continue
            help_lines.append(f"/{cmd.name.ljust(8)} {cmd.description}")
        
        ui.show_popup("help", "\n".join(help_lines))

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
        # Show placeholder popup while checking status
        ui.show_popup("status", "Checking server status...")
        
        # Get actual status (may take time if server is unreachable)
        status = await ui.agent.get_status()
        
        # Update popup with actual status
        ui.show_popup("status", self.format_status(status))
        
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
        super().__init__("add", "Add a named LLM server configuration", params=[
            Param("NAME", required=True),
            Param("TYPE", completions=["openrouter", "llamacpp"], required=True),
            Param("MODEL_OR_URL", required=True),
            Param("PROVIDER"),
        ])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        """
        Add a named server configuration.
        Usage: /server add <name> <type> <model/url> [provider]
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
        command_text = "/server add " + " ".join(args)

        from pico_chat.harness.server_service import ServerService
        svc = ServerService()

        if server_type == "openrouter":
            placeholder = ui.chat_history_panel.add_message(
                f"Validating OpenRouter model {model_or_url}...",
                msg_type=SysMsg(),
                title="server"
            )
            try:
                result = await svc.add_openrouter(server_name, model_or_url, provider)
            except Exception as e:
                result = type("R", (), {"ok": False, "message": f"Error adding server: {e}"})()

            msg_type = SysMsg() if result.ok else SysMsgError()
            new_msg = ui.chat_history_panel.new_message(result.message, msg_type=msg_type, title="server")
            if not result.ok:
                new_msg.command_text = command_text
            ui.chat_history_panel.replace_message(placeholder, new_msg)

        elif server_type == "llamacpp":
            placeholder = ui.chat_history_panel.add_message(
                f"Testing connection to {model_or_url}...",
                msg_type=SysMsg(),
                title="server"
            )
            try:
                result = await svc.add_llamacpp(server_name, model_or_url)
            except Exception as e:
                result = type("R", (), {"ok": False, "message": f"Error adding server: {e}"})()

            msg_type = SysMsg() if result.ok else SysMsgError()
            new_msg = ui.chat_history_panel.new_message(result.message, msg_type=msg_type, title="server")
            ui.chat_history_panel.replace_message(placeholder, new_msg)

        else:
            ui.chat_history_panel.add_message(
                f"Unknown server type: {server_type}\n"
                "Supported types: openrouter, llamacpp",
                msg_type=SysMsgError(),
                command_text=command_text
            )


class ServerListCommand(Command):
    def __init__(self):
        super().__init__("list", "List all configured servers")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.server_service import ServerService
        svc = ServerService()
        servers = svc.list_servers()

        if not servers:
            ui.chat_history_panel.add_message(
                "No servers configured.\n\n"
                "Add a server with:\n"
                "  /server add <name> openrouter <model> [provider]\n"
                "  /server add <name> llamacpp <url>",
                msg_type=SysMsg()
            )
            return

        color = str(theme.DEFAULT)
        muted = str(theme.MUTED)
        active_color = str(theme.SUCCESS)
        reset = theme.reset()

        msg = f"{color}Configured servers:{reset}\n\n"

        from pico_chat import pico_cfg
        for name, server_type, is_active in servers:
            cfg = pico_cfg.config.servers[name]
            if is_active:
                line = f"{active_color}{name}{reset}"
            else:
                line = f"{color}{name}{reset}"
            line += f" {muted}({server_type}){reset}"

            if server_type == "openrouter":
                model = cfg.get("model", "unknown")
                provider = cfg.get("provider")
                if provider:
                    line += f" {muted}- {model} via {provider}{reset}"
                else:
                    line += f" {muted}- {model}{reset}"
            elif server_type == "llamacpp":
                url = cfg.get("base_url", "unknown")
                line += f" {muted}- {url}{reset}"

            msg += line + "\n"

        msg += f"\n{muted}Use '/server use <name>' to switch{reset}"
        ui.chat_history_panel.add_message(msg, msg_type=SysMsg())


class ServerUseCommand(Command):
    def __init__(self):
        super().__init__("use", "Switch to a different server configuration", params=[
            Param("SERVER_NAME", completions=_server_name_completions),
        ])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /server use <name>\n\n"
                "Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return

        from pico_chat.harness.server_service import ServerService
        svc = ServerService()
        result = svc.switch_server(args[0])

        if not result.ok:
            ui.chat_history_panel.add_message(result.message, msg_type=SysMsgError())
            return

        try:
            ui.agent.switch_server(result.new_config)
            ui.chat_history_panel.add_message(result.message, msg_type=SysMsg())
        except Exception as e:
            ui.chat_history_panel.add_message(
                f"Error switching server: {e}",
                msg_type=SysMsgError()
            )


class ServerRemoveCommand(Command):
    def __init__(self):
        super().__init__("remove", "Remove a server configuration", params=[
            Param("SERVER_NAME", completions=_server_name_completions),
        ])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /server remove <name>\n\n"
                "Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return

        from pico_chat.harness.server_service import ServerService
        svc = ServerService()
        result = svc.remove_server(args[0])

        if not result.ok:
            ui.chat_history_panel.add_message(result.message, msg_type=SysMsgError())
            return

        # If the active server was removed and we switched, apply the switch
        if result.new_config is not None:
            try:
                ui.agent.switch_server(result.new_config)
            except Exception as e:
                logger.warning(f"Failed to switch to new server after removal: {e}")

        ui.chat_history_panel.add_message(result.message, msg_type=SysMsg())


class ServerInfoCommand(Command):
    def __init__(self):
        super().__init__("info", "Show full details for a server configuration", params=[
            Param("SERVER_NAME", completions=_server_name_completions),
        ])

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            ui.chat_history_panel.add_message(
                "Usage: /server info <name>\n\n"
                "Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return

        from pico_chat.harness.server_service import ServerService
        svc = ServerService()
        info = svc.get_server_info(args[0])

        if info is None:
            ui.chat_history_panel.add_message(
                f"Server '{args[0]}' not found.\n\n"
                "Use '/server list' to see available servers",
                msg_type=SysMsgError()
            )
            return

        color = str(theme.WARNING)
        reset = theme.reset()

        msg = color + f"Name             : {reset}{info.name}"
        if info.is_active:
            msg += f" {color}(active){reset}"
        msg += "\n"
        msg += color + f"Type             : {reset}{info.server_type}\n"

        if info.server_type == "openrouter":
            msg += color + f"Model            : {reset}{info.model or 'unknown'}\n"
            if info.provider:
                msg += color + f"Provider         : {reset}{info.provider}\n"
            msg += color + f"Base URL         : {reset}{info.base_url or 'unknown'}\n"
            msg += color + f"API Key Env      : {reset}{info.api_key_env or ''}\n"
        elif info.server_type == "llamacpp":
            msg += color + f"Base URL         : {reset}{info.base_url or 'unknown'}\n"

        msg += color + f"Timeout          : {reset}{info.timeout}s\n"
        msg += color + f"Retry Attempts   : {reset}{info.retry_attempts}\n"
        msg += color + f"Retry Delay      : {reset}{info.retry_delay}s\n"
        if info.max_context:
            msg += color + f"Max Context      : {reset}{info.max_context:,} tokens\n"

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
            available_tools = ["read", "write", "patch", "run"]

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
            return "unknown"

        lines = [f"profile: {permissions.name}"]
        for tool_name in available_tools:
            lines.append(f"{tool_name.ljust(10)} - {permission_label(tool_name)}")

        ui.show_popup("tools", "\n".join(lines))

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
            "log": DebugLogCommand(),
        }
        super().__init__("debug", "Debug utilities", subcommands=subcommands)

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        if not args:
            # Show subcommand help in popup
            help_text = "Missing subcommand. Available subcommands:\n"
            for name, cmd in sorted(self.subcommands.items()):
                help_text += f"  {name.ljust(15)} - {cmd.description}\n"
            ui.show_popup("debug", help_text.rstrip())
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
        
        ui.show_popup("permissions", output.rstrip())

class OpenRouterBalanceCommand(Command):
    def __init__(self):
        super().__init__("balance", "Show OpenRouter account credit balance")

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        from pico_chat.harness.server_service import ServerService

        placeholder = ui.chat_history_panel.add_message(
            "Fetching OpenRouter balance...",
            msg_type=SysMsg(),
            title="openrouter",
        )

        svc = ServerService()
        ok, message, balance = await svc.get_openrouter_balance()

        if not ok:
            error_msg = ui.chat_history_panel.new_message(
                message,
                msg_type=SysMsgError(),
                title="openrouter",
            )
            ui.chat_history_panel.replace_message(placeholder, error_msg)
            return

        color = str(theme.WARNING)
        reset = theme.reset()

        if balance.remaining > 5:
            balance_color = theme.SUCCESS
        elif balance.remaining > 1:
            balance_color = theme.WARNING
        else:
            balance_color = theme.ERROR

        msg  = color + f"Remaining        : {reset}{balance_color}${balance.remaining:.4f}{reset}\n"
        msg += color + f"Total Credits    : {reset}${balance.total_credits:.4f}\n"
        msg += color + f"Total Usage      : {reset}${balance.total_usage:.4f}\n"

        result_msg = ui.chat_history_panel.new_message(
            msg.rstrip(),
            msg_type=SysMsg(),
            title="openrouter",
        )
        ui.chat_history_panel.replace_message(placeholder, result_msg)


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
        super().__init__("cd", "Change workspace directory and rebuild context", params=[
            Param("DIR", path=True),
        ])

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
