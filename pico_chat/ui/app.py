"""
Pico-Chat TUI Application.
"""

import sys
import os
import asyncio
import atexit
from turtle import done
from typing import Optional, Any

from pico_chat.ui.tui.compositor import Compositor
from pico_chat.ui.tui.events import KeyEvent, MouseEvent, TickEvent
from pico_chat.ui.tui.components.box import SPINNER_FRAMES
from pico_chat.ui.tui.components import (
    TextComponent, Box, InputComponent, ComponentField, Label,
)
from pico_chat.ui.tui.components.debug_panel import DebugLogPanel
from pico_chat.ui.tui.components.popup import Popup, PopupScreen
from pico_chat.ui.tui.components.form_popup import FormPopup
from pico_chat.ui.tui.components.tab_bar import TabBar
from pico_chat.ui.tui.components.tab_view import TabView
from pico_chat.ui.tui.components.bars import StatusBar
from pico_chat.ui.chat_history_panel import ChatHistoryPanel
from pico_chat.ui.chat_message import Message
from pico_chat.ui.commands import handle_command, get_command_list, get_subcommand_list
from pico_chat.ui.tui.layout_utils import strip_ansi
from pico_chat.ui.tui.focus import FocusScope
from pico_chat.ui.tui.navigation import Navigator, ModalHost
from pico_chat.ui.tui.chat_screen import ChatScreen

        # Setup logging to debug panel
import logging
from pico_chat.ui.commands import StatusCommand
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import MsgType, MsgAction, PicoMsg, ThinkingMsg, UserMsg, SysMsg, SysMsgError, SysMsgWarning, ToolCallMsg, ToolDraftMsg, AskPermissionMsg

from pico_chat import pico_cfg
from pico_chat.ui.logging_handlers import setup_tui_logging
from pico_chat.ui.chat_action_handlers import ChatActionHandlers
from pico_chat.ui.conversation_runtime import ConversationRuntime

# Import chunks module for type checking
from pico_chat.harness import chunks

TARGET_FPS = pico_cfg.config.target_fps


class _AppFocusTarget:
    """Adapter exposing an application focus target to the TUI focus API."""

    focusable = True
    enabled = True

    def __init__(self, component, on_focus, handle_input):
        self._component = component
        self._on_focus = on_focus
        self._handle_input = handle_input
        self.focused = False

    @property
    def x(self):
        return self._component.x

    @property
    def y(self):
        return self._component.y

    @property
    def width(self):
        return self._component.width

    @property
    def height(self):
        return self._component.height

    def set_focused(self, focused: bool):
        self.focused = focused
        self._on_focus(focused)

    def set_component(self, component):
        self._component = component

    def handle_input(self, event):
        return self._handle_input(event)


class ConversationState(ConversationRuntime):
    """Compatibility constructor for callers that create tab state directly."""

    def __init__(self, name: str = "chat", kind: str = "chat"):
        super().__init__(name=name, kind=kind)


class chatTUI(ChatActionHandlers):
    """Terminal UI for the agent."""

    def __init__(self, agent):
        self._initial_agent = agent
        self._agent_factory = self._runtime_agent_factory()
        # Pre-warm .local hostname resolution for the initial agent so the
        # first message doesn't stall on DNS/mDNS lookup.
        server = getattr(agent, "server", None)
        if server is not None:
            from pico_chat.harness.llm_server import prewarm_local_resolution
            prewarm_local_resolution(server._original_base_url)
        self.compositor = None
        self.navigator = None
        self.modal_host = None
        self.popup_screen = None
        self._last_focus_id = "input"
        self.chat_history_panel = ChatHistoryPanel()
        self.input_component = InputComponent(" ", id="entry", frame_color=theme.USER)
        self.input_component.config = pico_cfg.config
        self.input_component.on_submit = self.on_user_submit
        self.input_component.setup_commands(get_command_list())
        self.input_component.setup_subcommands(get_subcommand_list)
        get_context_items = lambda: agent.list_files_and_folders() if hasattr(agent, "list_files_and_folders") else []
        self.input_component.setup_context(get_context_items)
        from pico_chat.ui.commands import COMMANDS
        self.input_component.setup_command_registry(COMMANDS)
        self.input_box = Box(
            self.input_component,
            title="",
            fg=theme.USER,  # Color the bars/prefix with the user color.
            lines_only=True,
        )
        self._focus_targets = [
            _AppFocusTarget(self.input_component, self._set_input_focus, self.input_component.handle_input),
            _AppFocusTarget(self.chat_history_panel, self._set_history_focus, self.chat_history_panel.handle_input),
        ]
        self._focus_scope = FocusScope(self._focus_targets)
        self.debug_panel = DebugLogPanel(max_lines=1000, frame_color=theme.ERROR, content_color=theme.MUTED, left_pad=1, right_pad=0)
        self.debug_box = self.debug_panel
        self.show_debug = False
        self.popup = Popup()
        self.form_popup = FormPopup()
        self.confirmation_popup = FormPopup(
            frame_color=theme.ERROR,
            focus_color=theme.ERROR,
            padding=1,
            min_height=3,
        )
        self.log_handler = setup_tui_logging(self.debug_panel)
        self.editing_prefill_for_resume = False
        self.tab_bar = TabBar(id="tabs")
        # Restore BarStyle's default 1-col left padding so the status text
        # sits one space in from the left edge, matching the message gutter.
        self.status_bar = StatusBar(
            fields=pico_cfg.config.ui_status_bar_fields,
            id="status",
        )
        self._status_spinner_frame = 0
        self.tab_view = TabView(tab_bar=self.tab_bar)
        self._tabs = []
        self._active_tab_index = 0
        self._next_tab_id = 1
        self._pending_tab_restore = None
        self._chat_workspace = None
        self.command_queue = asyncio.Queue()
        self.shutdown_event = asyncio.Event()
        self._active_user_input = None
        self._active_user_msg = None
        self._active_generation_tab = None
        self._requeue_after_cancel = False
        self._paused_user_input = None
        self._paused_user_msg = None
        self._pending_permission_fallback = None
        self._message_queue_fallback = asyncio.Queue()
        atexit.register(self._emergency_cleanup)

    def _active_runtime(self):
        if not self._tabs or self._active_tab_index >= len(self._tabs):
            return None
        return self._tabs[self._active_tab_index]

    @staticmethod
    def _format_status_tokens(value: int | None) -> str:
        if value is None:
            return "?"
        if value < 1000:
            return str(value)
        # Use binary-sized exact values for common context limits (32k for
        # 32768), while keeping the compact decimal style for live usage.
        if value % 1024 == 0:
            return f"{value // 1024}k"
        return f"{value / 1000:.1f}k"

    def refresh_status_bar(self) -> None:
        """Refresh local status fields without performing network I/O."""
        runtime = self._active_runtime()
        agent = runtime.agent if runtime and getattr(runtime, "agent", None) else self._initial_agent
        server = getattr(agent, "server", None)
        if server is None:
            return

        config = server.config
        model = (
            getattr(server, "selected_model", None)
            or config.model
            or getattr(server, "_cached_model_name", None)
            or "?"
        )
        # Strip a leading path and common file suffix from a model id
        # (e.g. /data/llm/weights/Qwen3.8-27B-Q4_0.gguf -> Qwen3.8-27B-Q4_0)
        # for a compact status bar.
        if isinstance(model, str):
            if "/" in model:
                model = model.rsplit("/", 1)[-1]
            for suffix in (".gguf", ".bin", ".safetensors"):
                if model.endswith(suffix):
                    model = model[: -len(suffix)]
                    break
        role = getattr(getattr(agent, "role", None), "name", "default")
        state = getattr(getattr(agent, "state", None), "name", "IDLE").lower()

        # Show an animated spinner while .local hostname resolution or model
        # name discovery is pending.
        from pico_chat.harness.llm_server import is_local_resolution_pending
        if is_local_resolution_pending(server._original_base_url) or getattr(server, "_model_name_pending", False):
            frame = SPINNER_FRAMES[self._status_spinner_frame % len(SPINNER_FRAMES)]
            model = f"{frame} {model}"

        # Color the server/model field by connection state:
        #   checking -> orange, error -> red, ok -> green.
        conn = getattr(server, "_connection_state", "unknown")
        if conn == "checking":
            server_color = theme.WARNING
        elif conn == "error":
            server_color = theme.ERROR
        elif conn == "ok":
            server_color = theme.SUCCESS
        else:
            server_color = theme.DEFAULT

        usage = getattr(agent, "_last_usage", None)
        context_used = getattr(usage, "prompt_tokens", None)
        context_max = getattr(server, "_cached_context_window", None)
        if context_max is None:
            context_max = config.max_context or 32768
        if context_used is None:
            try:
                context_used, estimated_max, _ = agent.estimate_context_usage()
                context_max = estimated_max or context_max
            except Exception:
                context_used = 0

        self.status_bar.set_values({
            "endpoint_model": f"{config.name}:{model}",
            "context": f"ctx {self._format_status_tokens(context_used)}/{self._format_status_tokens(context_max)}",
            "role": f"role {role}",
            "state": state,
            "endpoint": config.name,
            "model": model,
            "workspace": getattr(agent, "workspace", ""),
        })
        self.status_bar.set_field_colors({
            "context": self._context_color(context_used, context_max),
            "endpoint": server_color,
            "model": server_color,
            "endpoint_model": server_color,
        })

    @staticmethod
    def _context_color(used: int | None, maximum: int | None) -> Any:
        """Color the context field by how full the window is.

        green < 33%, orange < 66%, red >= 66%.
        """
        if not used or not maximum or maximum <= 0:
            return theme.DEFAULT
        ratio = used / maximum
        if ratio < 0.33:
            return theme.SUCCESS
        if ratio < 0.66:
            return theme.WARNING
        return theme.ERROR

    @property
    def agent(self):
        runtime = self._active_runtime()
        return runtime.ensure_agent() if runtime else self._initial_agent

    @property
    def message_queue(self):
        runtime = self._active_runtime()
        return runtime.message_queue if runtime else self._message_queue_fallback

    @property
    def current_generation_task(self):
        runtime = self._active_runtime()
        return runtime.current_generation_task if runtime else None

    @current_generation_task.setter
    def current_generation_task(self, value):
        runtime = self._active_runtime()
        if runtime:
            runtime.current_generation_task = value

    @property
    def active_tool_messages(self):
        runtime = self._active_runtime()
        return runtime.active_tool_messages if runtime else {}

    @active_tool_messages.setter
    def active_tool_messages(self, value):
        runtime = self._active_runtime()
        if runtime:
            runtime.active_tool_messages = value

    @property
    def pending_permission_prompt(self):
        runtime = self._active_runtime()
        return runtime.pending_permission_prompt if runtime else self._pending_permission_fallback

    @pending_permission_prompt.setter
    def pending_permission_prompt(self, value):
        runtime = self._active_runtime()
        if runtime:
            runtime.pending_permission_prompt = value
        else:
            self._pending_permission_fallback = value

    def _runtime_field(name):
        def getter(self):
            runtime = self._active_runtime()
            return getattr(runtime, name, None) if runtime else None

        def setter(self, value):
            runtime = self._active_runtime()
            if runtime:
                setattr(runtime, name, value)

        return property(getter, setter)

    _active_user_input = _runtime_field("active_user_input")
    _active_user_msg = _runtime_field("active_user_msg")
    _paused_user_input = _runtime_field("paused_user_input")
    _paused_user_msg = _runtime_field("paused_user_msg")
    _requeue_after_cancel = _runtime_field("requeue_after_cancel")

    def _runtime_agent_factory(self):
        source_agent = self._initial_agent

        def create_agent():
            agent_type = type(source_agent)
            workspace = getattr(source_agent, "workspace", None)
            if workspace is not None:
                try:
                    return agent_type(workspace_path=workspace)
                except TypeError:
                    pass
            return agent_type()

        return create_agent

    def _emergency_cleanup(self):
        """Emergency cleanup handler called by atexit."""
        if self.compositor and self.compositor.terminal:
            try:
                self.compositor.terminal.cleanup(clear_screen=False)
            except Exception:
                pass

    @staticmethod
    def _rgb_to_ansi_fg(r: int, g: int, b: int) -> str:
        return f"\033[38;2;{r};{g};{b}m"

    async def _process_generation(self, runtime, user_input, user_msg=None):
        """Process a single generation request for one conversation runtime."""
        legacy_runtime = user_msg is None
        if legacy_runtime:
            user_msg = user_input
            user_input = runtime
            runtime = self._active_runtime()
            if runtime is None:
                runtime = ConversationRuntime(agent=self._initial_agent, name="chat")
                runtime.chat_history_panel = self.chat_history_panel
                runtime.pending_permission_prompt = self._pending_permission_fallback

        import logging
        logger = logging.getLogger("tui")
        logger.info(f"Starting generation for user input: {user_input[:50]}...")

        chat = self.chat_history_panel if runtime is self._active_runtime() else runtime.chat_history_panel
        agent = runtime.ensure_agent()
        if runtime is self._active_runtime():
            self.refresh_status_bar()
        # No placeholder status message: the first real chunk creates its own
        # message. This keeps the conversation free of transient "Sending
        # request..." / "Processing results..." clutter.
        current_msg = None
        current_msg_type = None
        current_harness_ids = []
        processing_msg = None

        def ensure_tool_message_type(msg: Message, target_type: MsgType) -> Message:
            if isinstance(msg.type, type(target_type)):
                return msg
            new_msg = chat.new_message("", msg_type=target_type, harness_message_ids=msg.harness_message_ids or current_harness_ids)
            new_msg.tool_name = msg.tool_name
            new_msg.tool_args = msg.tool_args
            new_msg.tool_output = msg.tool_output
            new_msg.tool_status = msg.tool_status
            new_msg.show_output = msg.show_output
            chat.replace_message(msg, new_msg)
            return new_msg

        if runtime is self._active_runtime() and self.compositor and hasattr(self.compositor, "set_streaming_active"):
            self.compositor.set_streaming_active(True)
        
        # Process streaming response from Harness
        try:
            async for chunk in agent.chat(user_input):
                if runtime is self._active_runtime() and self.compositor and hasattr(self.compositor, "request_render"):
                    self.compositor.request_render()
                
                if isinstance(chunk, chunks.MessageStart):
                    # New message starting from harness
                    current_harness_ids = [chunk.message_id]
                    logger.debug(f"MessageStart: {chunk.role} with ID {chunk.message_id}")
                    
                    if chunk.role == "user":
                        # Link the user message that was passed through the queue
                        if not user_msg.harness_message_ids:
                            user_msg.harness_message_ids = [chunk.message_id]
                            logger.debug(f"Linked user message to harness ID {chunk.message_id}")
                    
                elif isinstance(chunk, chunks.Thinking):
                    # If not currently in a thinking message, create one
                    if current_msg_type != ThinkingMsg:
                        if current_msg is not None:
                            # Finalize previous and create new
                            current_msg.finalize()
                        current_msg = chat.add_message("", msg_type=ThinkingMsg(), harness_message_ids=current_harness_ids)
                        # Thinking folds to a single line by default; expand on focus.
                        current_msg.set_collapsed(True)
                        current_msg_type = ThinkingMsg
                    
                    current_msg.append(chunk.content)
                
                elif isinstance(chunk, chunks.Content):
                    # If not currently in a content message, create one
                    if current_msg_type != PicoMsg:
                        if current_msg is not None:
                            # Finalize previous and create new
                            current_msg.finalize()
                        current_msg = chat.add_message("", msg_type=PicoMsg(), harness_message_ids=current_harness_ids)
                        current_msg_type = PicoMsg
                    
                    current_msg.append(chunk.content)
                
                elif isinstance(chunk, chunks.ToolDraft):
                    tool_id = chunk.tool_call_id
                    msg = runtime.active_tool_messages.get(tool_id)
                    preserve_active_text_stream = current_msg_type in (ThinkingMsg, PicoMsg)

                    # Flush any incomplete text message before showing tool draft
                    if current_msg_type in (ThinkingMsg, PicoMsg) and current_msg:
                        current_msg.finalize()

                    if not msg:
                        msg = chat.add_message("", msg_type=ToolDraftMsg(), harness_message_ids=current_harness_ids)
                        runtime.active_tool_messages[tool_id] = msg

                    msg = ensure_tool_message_type(msg, ToolDraftMsg())
                    runtime.active_tool_messages[tool_id] = msg
                    msg.tool_name = chunk.tool_name or msg.tool_name
                    msg.tool_args = chunk.tool_args
                    msg.tool_status = "drafting"
                    msg.rebuild_tool_display()

                    if not preserve_active_text_stream:
                        current_msg = msg
                        current_msg_type = type(msg.type)

                elif isinstance(chunk, chunks.ToolStatusChange):
                    # Handle tool status change
                    tool_id = chunk.tool_call_id

                    # Flush any incomplete text message before showing tool status
                    if current_msg_type in (ThinkingMsg, PicoMsg) and current_msg:
                        current_msg.finalize()
                    
                    if chunk.status == chunks.ToolStatus.PERMISSION_REQUESTED:
                        msg = runtime.active_tool_messages.get(tool_id)

                        if chunk.auto_decision:
                            # Auto-decision: show status marker
                            if not msg:
                                msg = chat.add_message(
                                    "",  # Will be built by rebuild_tool_display
                                    msg_type=ToolCallMsg(),
                                    harness_message_ids=current_harness_ids
                                )
                                runtime.active_tool_messages[tool_id] = msg
                                processing_msg = None  # Clear processing indicator if showing new tool

                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            runtime.active_tool_messages[tool_id] = msg
                            msg.tool_name = chunk.tool_name
                            msg.tool_args = chunk.tool_args
                            msg.tool_status = "auto-approved"
                            msg.rebuild_tool_display()
                        else:
                            # Need user permission - show request
                            if not msg:
                                msg = chat.add_message(
                                    "",
                                    msg_type=AskPermissionMsg(),
                                    harness_message_ids=current_harness_ids
                                )
                                runtime.active_tool_messages[tool_id] = msg
                                processing_msg = None  # Clear processing indicator

                            msg = ensure_tool_message_type(msg, AskPermissionMsg())
                            runtime.active_tool_messages[tool_id] = msg
                            msg.tool_name = chunk.tool_name
                            msg.tool_args = chunk.tool_args
                            msg.tool_status = None
                            msg.rebuild_tool_display()

                            # Auto-focus for user action
                            try:
                                msg_index = chat.messages.index(msg)
                                chat.set_focused_message(msg_index)
                            except ValueError:
                                pass
                            self._set_app_focus("history")
                            
                            # Force compositor render to show actions immediately
                            if self.compositor:
                                self.compositor.render()
                            
                            # Store prompt for handler
                            runtime.pending_permission_prompt = chunk.permission_prompt

                        current_msg = msg
                        current_msg_type = type(msg.type)
                    
                    elif chunk.status == chunks.ToolStatus.APPROVED:
                        msg = runtime.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            runtime.active_tool_messages[tool_id] = msg
                            # Update status
                            msg.tool_name = chunk.tool_name
                            msg.tool_args = chunk.tool_args
                            msg.tool_status = "approved"
                            msg.rebuild_tool_display()
                        runtime.pending_permission_prompt = None
                    
                    elif chunk.status == chunks.ToolStatus.DENIED:
                        msg = runtime.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            msg.tool_name = chunk.tool_name
                            msg.tool_args = chunk.tool_args
                            msg.tool_status = "denied"
                            msg.tool_output = chunk.denial_reason
                            msg.show_output = True  # Always show denial reason
                            msg.rebuild_tool_display()
                            msg.finalize()
                            del runtime.active_tool_messages[tool_id]
                        runtime.pending_permission_prompt = None
                    
                    elif chunk.status == chunks.ToolStatus.EXECUTING:
                        msg = runtime.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            runtime.active_tool_messages[tool_id] = msg
                            # Update status to show executing
                            msg.tool_status = "approved | executing"
                            msg.rebuild_tool_display()
                    
                    elif chunk.status == chunks.ToolStatus.COMPLETED:
                        msg = runtime.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            # Store output and update to completed
                            msg.tool_status = "approved | completed"
                            msg.tool_output = chunk.result or ""
                            msg.rebuild_tool_display()
                            msg.finalize()
                            del runtime.active_tool_messages[tool_id]
                    
                    elif chunk.status == chunks.ToolStatus.ERROR:
                        msg = runtime.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            msg.tool_status = "error"
                            msg.tool_output = chunk.error
                            msg.show_output = True  # Always show errors
                            msg.rebuild_tool_display()
                            msg.finalize()
                            del runtime.active_tool_messages[tool_id]
                
                elif isinstance(chunk, chunks.GenerationMetrics):
                    # Update message metrics (for live display in footer)
                    # Only update for thinking/content messages, not tool messages
                    if current_msg_type in (ThinkingMsg, PicoMsg):
                        current_msg.update_metrics(
                            tokens=chunk.tokens,
                            tokens_per_second=chunk.tokens_per_second,
                            ttft_ms=chunk.ttft_ms,
                            duration_ms=chunk.duration_ms
                        )
                    if runtime is self._active_runtime():
                        self.refresh_status_bar()

                # Ensure we scroll to bottom if needed
                if chat.auto_scroll:
                    chat.scroll_offset = 0
                    # Auto-focus input when new messages arrive (if at bottom)
                    # BUT: Don't steal focus if user has explicitly focused a message
                    if runtime is self._active_runtime() and self._last_focus_id != "input" and chat.focused_message_index is None:
                        self._set_app_focus("input")

                # Yield to let the compositor render the update
                await asyncio.sleep(0)
                
        except asyncio.CancelledError:
            # Finalize current message and add a plain SysMsg notification.
            # Avoid appending ANSI codes to a MarkdownComponent message (PicoMsg)
            # since the component would render the escape sequences as literal text.
            if current_msg is not None:
                current_msg.finalize()
            chat.add_message("[Generation stopped]", msg_type=SysMsg())
            raise 
            
        except Exception as e:
            raise e
    
        finally:
            if legacy_runtime:
                self._pending_permission_fallback = runtime.pending_permission_prompt
            if runtime is self._active_runtime() and self.compositor and hasattr(self.compositor, "set_streaming_active"):
                self.compositor.set_streaming_active(False)
            if current_msg is not None:
                current_msg.finalized = True
                current_msg.update_actions()
            
            
        
    async def agent_worker(self, runtime: ConversationRuntime):
        """Process queued requests for one conversation runtime."""
        import logging
        logger = logging.getLogger("tui")

        while not self.shutdown_event.is_set():
            try:
                user_input, user_msg = await runtime.message_queue.get()
                if getattr(user_msg, "is_steered", False):
                    continue
                if getattr(user_msg, "is_queued", False):
                    user_msg.is_queued = False
                    user_msg.set_title("user")
                    user_msg.set_frame_color(theme.USER)

                runtime.active_user_input = user_input
                runtime.active_user_msg = user_msg
                self._active_generation_tab = runtime
                runtime.current_generation_task = asyncio.create_task(
                    self._process_generation(runtime, user_input, user_msg)
                )
                await runtime.current_generation_task
            except asyncio.CancelledError:
                runtime.stop_generation()
                return
            except Exception as error:
                logger.error("Conversation generation failed: %s", error, exc_info=True)
                runtime.chat_history_panel.add_message(str(error), msg_type=SysMsgError())
            finally:
                runtime.current_generation_task = None
                if runtime.requeue_after_cancel and runtime.active_user_input:
                    runtime.enqueue(runtime.active_user_input, runtime.active_user_msg)
                runtime.requeue_after_cancel = False
                runtime.active_user_input = None
                runtime.active_user_msg = None
                if self._active_generation_tab is runtime:
                    self._active_generation_tab = None

    async def command_worker(self):
        """Dispatch queued slash commands independently of generation workers."""
        import logging
        logger = logging.getLogger("tui")

        while not self.shutdown_event.is_set():
            command_task = asyncio.create_task(self.command_queue.get())
            shutdown_task = asyncio.create_task(self.shutdown_event.wait())
            try:
                done, pending = await asyncio.wait(
                    (command_task, shutdown_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if shutdown_task in done:
                    return
                command = command_task.result()
                logger.debug("Processing command: %s", command)
                await handle_command(self, command)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.error("Command failed", exc_info=True)

    def stop_generation(self):
        """Stop the current generation task if active."""
        if self.current_generation_task and not self.current_generation_task.done():
            self.current_generation_task.cancel()
            return True
        return False

    def _ensure_runtime_worker(self, runtime: ConversationRuntime) -> None:
        if runtime.worker_task is None or runtime.worker_task.done():
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return
            runtime.worker_task = asyncio.create_task(self.agent_worker(runtime))

    def _enqueue_message(self, text: str, message: Message) -> None:
        """Queue a message and apply conversation-local queued presentation."""
        runtime = self._active_runtime()
        if runtime is None:
            self.message_queue.put_nowait((text, message))
            return

        if self._message_belongs_to_active_generation(message) and message is not runtime.active_user_msg:
            message.is_queued = True
            message.set_title("user (queued)")
            message.set_frame_color(theme.MUTED)

        self._ensure_runtime_worker(runtime)
        runtime.enqueue(text, message)

    def on_command_submit(self, text: str):
        """Handle execution of commands."""
        self.command_queue.put_nowait(text)
        
    def toggle_debug_console(self):
        """Toggle the debug console workspace tab."""
        import logging
        if self.show_debug:
            self._close_debug_tab()
            return

        self._open_debug_tab()
        logger = logging.getLogger("tui")
        logger.info("Debug console toggled: visible")

    def _handle_message_action(self, message, action: MsgAction):
        handlers = {
            MsgAction.COPY: self.handle_copy_action,
            MsgAction.RETRY: self.handle_retry_action,
            MsgAction.STOP: self.handle_stop_action,
            MsgAction.ALLOW: self.handle_allow_action,
            MsgAction.DENY: self.handle_deny_action,
            MsgAction.OUTPUT: self.handle_output_action,
            MsgAction.STEER: self.handle_steer_action,
            MsgAction.PAUSE: self.handle_pause_action,
            MsgAction.RESUME: self.handle_resume_action,
            MsgAction.DELETE: self.handle_delete_action,
        }
        handler = handlers.get(action)
        if handler:
            handler(message)

    def _replace_workspace_screen(self, children):
        """Install a workspace layout through Navigator when the app is running."""
        screen = ChatScreen(
            self.tab_bar,
            children[0],
            children[1],
            self._focus_scope,
            self._tabs[self._active_tab_index] if self._tabs else None,
            self.status_bar,
        )
        self._chat_workspace = screen.workspace
        self.root = screen.root
        if self.navigator is not None:
            self.navigator.replace(screen)

    def _install_chat_screen(self):
        model = self._tabs[self._active_tab_index] if self._tabs else None
        screen = ChatScreen(
            self.tab_bar,
            self.chat_history_panel,
            self.input_box,
            self._focus_scope,
            model,
            self.status_bar,
        )
        self._chat_workspace = screen.workspace
        self.root = screen.root
        if self.navigator is not None:
            self.navigator.replace(screen)

    def _debug_tab_index(self) -> Optional[int]:
        """Return the debug tab's position in the shared workspace tab list."""
        for index, tab in enumerate(self._tabs):
            if tab.kind == "debug":
                return index
        return None

    def _show_chat_workspace(self):
        self.show_debug = False
        self.input_component.hide_completions()
        self._install_chat_screen()

    def _open_debug_tab(self):
        self.input_component.hide_completions()
        debug_index = self._debug_tab_index()
        if debug_index is None:
            debug_index = len(self._tabs)
            debug_state = ConversationState("debug", kind="debug")
            self._tabs.append(debug_state)
            self.tab_view.add("debug", "debug", debug_state, closeable=True)
        self.show_debug = True
        self.tab_view.activate(debug_index)
        self._replace_workspace_screen([self.debug_box, self.input_box])
        self._set_app_focus("input")

    def _close_debug_tab(self):
        debug_index = self._debug_tab_index()
        if debug_index is None:
            return
        self.tab_view.close(debug_index)

    def show_popup(self, title: str, content: str, content_padding: int = 1):
        """Show a popup overlay with the given title and content."""
        self.popup.set_compositor(self.compositor)
        if self.modal_host is None:
            self.popup.show(title, content, content_padding=content_padding)
            return
        self.popup_screen = PopupScreen(self.popup, title, content,
                                        content_padding=content_padding)
        self.modal_host.present_screen(self.popup_screen)

    def hide_popup(self):
        """Hide the popup overlay."""
        if self.modal_host is not None and self.popup_screen is not None:
            self.modal_host.dismiss_screen(self.popup_screen)
            self.popup_screen = None
            return
        self.popup.hide()

    def show_form_popup(self, title: str, fields: list, on_submit, on_cancel=None, on_new_profile=None, field_spacing=1):
        """Show a form popup overlay with interactive fields."""
        self.form_popup.set_compositor(self.compositor)
        if self.modal_host is not None:
            self.form_popup.set_modal_host(self.modal_host)
        self.form_popup.show(title, fields, on_submit, on_cancel, on_new_profile=on_new_profile, field_spacing=field_spacing)

    def show_confirmation(self, title: str, on_confirm, on_cancel=None):
        """Show a compact Enter/Esc confirmation modal over the current popup."""
        self.confirmation_popup.set_compositor(self.compositor)
        self.confirmation_popup.show(
            title,
            [ComponentField(Label(
                "Enter to delete, Esc to cancel.",
                wrap=True,
            ))],
            lambda _values: on_confirm(), on_cancel,
            field_spacing=0,
            submit_label="Delete",
            focus_submit=True,
        )


    def on_user_submit(self, text: str):
        """Handle user input submission."""
        clean_text = text.strip()
        if not clean_text:
            return  # Ignore empty or whitespace-only input

        if clean_text.startswith('/'):
            self.on_command_submit(clean_text)
            return

        # $ prefix: execute shell command directly (not visible to LLM)
        if clean_text.startswith('$'):
            self._handle_shell_command(clean_text[1:].strip())
            return

        # Editing a paused message's thinking prefill: set prefill then resume
        if getattr(self, 'editing_prefill_for_resume', False):
            self.editing_prefill_for_resume = False
            self.agent.set_thinking_prefill(clean_text)
            self.handle_resume_action(None)
            return

        if self.pending_permission_prompt:
            self.chat_history_panel.add_message(
                "Permission required for pending tool call. Use [a] allow or [x] deny first. Commands like /status are still available.",
                msg_type=SysMsg()
            )
            return

        if not self._tabs:
            self._new_tab()

        runtime = self._active_runtime()
        self._ensure_runtime_worker(runtime)

        if clean_text.lower() in ["exit", "quit", "q"]:
            if self.compositor:
                self.compositor.running = False
        else:
            import logging
            logger = logging.getLogger("tui")
            logger.info(f"User submitted: {text[:50]}...")
            
            # Create user message and queue it
            user_msg = self.chat_history_panel.add_message(text, msg_type=UserMsg())
            user_msg._tab_state = self._tabs[self._active_tab_index] if self._tabs else None

            self._enqueue_message(text, user_msg)
            
            # Enable auto-scroll to show the new message
            self.chat_history_panel.auto_scroll = True

    def _handle_shell_command(self, command: str):
        """Execute a shell command and display output (not visible to LLM).
        
        Args:
            command: The shell command to execute (without the $ prefix)
        """
        import subprocess
        import time
        from pico_chat.ui.tui.msg_types import SysMsg, SysMsgError
        
        if not command:
            self.chat_history_panel.add_message(
                "Usage: $ <command>\nExample: $ ls -la",
                msg_type=SysMsgError()
            )
            return
        
        # Get workspace directory
        workspace = self.agent.workspace if hasattr(self.agent, 'workspace') else os.getcwd()
        
        # Show command being executed
        cmd_msg = self.chat_history_panel.add_message(
            f"{theme.MUTED}$ {command}{theme.reset()}",
            msg_type=SysMsg(),
            title="shell"
        )
        
        # Execute command
        start_time = time.time()
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout
            )
            
            elapsed = time.time() - start_time
            
            # Build output
            output_parts = []
            
            if result.stdout:
                output_parts.append(result.stdout.rstrip())
            
            if result.stderr:
                if output_parts:
                    output_parts.append("")
                output_parts.append(f"{theme.ERROR}[stderr]{theme.reset()}")
                output_parts.append(result.stderr.rstrip())
            
            # Add exit code and timing
            exit_color = theme.SUCCESS if result.returncode == 0 else theme.ERROR
            output_parts.append(f"\n{exit_color}[exit:{result.returncode}]{theme.reset()} {theme.MUTED}{elapsed:.1f}ms{theme.reset()}")
            
            # Display output
            output_text = "\n".join(output_parts)
            if output_text.strip():
                self.chat_history_panel.add_message(
                    output_text,
                    msg_type=SysMsg(),
                    title="output"
                )
            else:
                self.chat_history_panel.add_message(
                    f"{theme.MUTED}(no output){theme.reset()}",
                    msg_type=SysMsg(),
                    title="output"
                )
                
        except subprocess.TimeoutExpired:
            self.chat_history_panel.add_message(
                f"{theme.ERROR}Command timed out after 30 seconds{theme.reset()}",
                msg_type=SysMsgError(),
                title="shell"
            )
        except Exception as e:
            self.chat_history_panel.add_message(
                f"{theme.ERROR}Command failed: {e}{theme.reset()}",
                msg_type=SysMsgError(),
                title="shell"
            )
        
        # Enable auto-scroll to show the output
        self.chat_history_panel.auto_scroll = True

    # --- Tab Management ---

    def _bind_runtime_panel(self, runtime: ConversationRuntime):
        """Make one runtime's history panel the visible chat panel."""
        self.chat_history_panel = runtime.chat_history_panel
        self._focus_targets[1].set_component(self.chat_history_panel)
        self.chat_history_panel.set_compositor(self.compositor)
        self.chat_history_panel.on_action = self._handle_message_action
        if self._chat_workspace is not None:
            self._chat_workspace.children[0] = self.chat_history_panel
            self.chat_history_panel.parent = self._chat_workspace
            self.chat_history_panel.set_layout(
                self._chat_workspace.x,
                self._chat_workspace.y,
                self._chat_workspace.width,
                self._chat_workspace.height,
            )
            self.chat_history_panel.layout()

    def _save_current_tab(self):
        """Keep the active runtime panel mounted as the visible panel."""
        return

    def _message_belongs_to_active_generation(self, message: Message) -> bool:
        """Return whether a message shares the currently generating tab."""
        message_tab = getattr(message, "_tab_state", None)
        return (
            message_tab is self._active_runtime()
            and self._active_runtime() is not None
            and self._active_runtime().is_generating
            and (self._active_generation_tab is None or self._active_generation_tab is message_tab)
        )
    
    def _restore_tab(self, index: int):
        """Restore conversation state from a tab into the live UI."""
        if not self._tabs or index >= len(self._tabs):
            return
        tab = self._tabs[index]
        if tab.kind == "debug":
            return
        
        self._active_tab_index = index
        self._bind_runtime_panel(tab)
        self.tab_view.activate(index)
        self.refresh_status_bar()
    
    def _on_tab_select(self, index: int):
        """Handle tab click — switch to that tab."""
        if index < 0 or index >= len(self._tabs):
            return
        if self._tabs[index].kind == "debug":
            self._open_debug_tab()
            return
        if self.show_debug:
            self._show_chat_workspace()
        if index == self._active_tab_index:
            self.tab_view.activate(index)
            return
        self._save_current_tab()
        self._restore_tab(index)

    def _on_tab_view_change(self, item):
        """Apply application state after TabView changes active selection."""
        index = self.tab_view.items.index(item)
        if self._pending_tab_restore is not None:
            restore_index = self._pending_tab_restore
            self._pending_tab_restore = None
            self._restore_tab(restore_index)
            return
        self._on_tab_select(index)

    def _can_close_tab(self, index, item) -> bool:
        return True

    def _on_tab_view_close(self, index, item):
        """Remove application-owned conversation state for a TabView close."""
        if index < 0 or index >= len(self._tabs):
            return
        closing_debug = self._tabs[index].kind == "debug"
        was_active = index == self._active_tab_index
        self._tabs.pop(index)

        if index < self._active_tab_index:
            self._active_tab_index -= 1
        elif was_active:
            new_index = min(index, len(self._tabs) - 1)
            if closing_debug:
                self._show_chat_workspace()
            elif not self._tabs:
                self._active_tab_index = 0
                self.agent.history = []
                self.chat_history_panel.clear()
                self.active_tool_messages = {}
                self.pending_permission_prompt = None
                self._active_user_input = None
                self._active_user_msg = None
                self._paused_user_input = None
                self._paused_user_msg = None
                self._pending_tab_restore = None
                self._show_chat_workspace()
            else:
                self._active_tab_index = new_index
                self._pending_tab_restore = new_index
    
    def _close_tab(self, index: int):
        """Close a tab and switch to adjacent one."""
        if not self._tabs or index < 0 or index >= len(self._tabs):
            return
        self.tab_view.close(index)
    
    def _new_tab(self, name: Optional[str] = None):
        """Create a new conversation tab and switch to it."""
        # Save current tab first
        self._save_current_tab()

        if self.show_debug:
            self._show_chat_workspace()
        
        # Generate name
        tab_id = self._next_tab_id
        self._next_tab_id += 1
        tab_name = name or f"chat {tab_id}"
        
        # Create a runtime with its own agent, queue, and message model.
        tab_state = ConversationRuntime(
            agent=self._initial_agent if not self._tabs else None,
            name=tab_name,
            agent_factory=self._agent_factory,
        )
        if not self._tabs:
            tab_state.chat_history_panel = self.chat_history_panel
        self._tabs.append(tab_state)
        self.tab_view.add(f"chat-{tab_id}", tab_name, tab_state)
        
        # Switch to new tab and mount its independent history panel.
        new_index = len(self._tabs) - 1
        tab_state.ensure_agent().history = []
        self._active_tab_index = new_index
        self._bind_runtime_panel(tab_state)
        tab_state.chat_history_panel.clear()
        tab_state.active_tool_messages.clear()
        tab_state.pending_permission_prompt = None
        tab_state.active_user_input = None

        # Pre-warm .local hostname resolution so the first message doesn't
        # stall on DNS/mDNS lookup, and discover the model name in the
        # background so the status bar shows it instead of "?".
        agent = tab_state.agent
        server = getattr(agent, "server", None)
        if server is not None:
            from pico_chat.harness.llm_server import prewarm_local_resolution
            prewarm_local_resolution(server._original_base_url)
            async def _prewarm_and_refresh():
                await server.prewarm_model_name()
                self.refresh_status_bar()
            asyncio.ensure_future(_prewarm_and_refresh())
        tab_state.active_user_msg = None
        tab_state.paused_user_input = None
        tab_state.paused_user_msg = None
        self.tab_view.activate(new_index)
        self.chat_history_panel.auto_scroll = True

    def _update_focus_states(self):
        """Update focus states of components based on _last_focus_id."""
        # Default to input focus if nothing is focused
        if self._last_focus_id is None:
            self._last_focus_id = "input"

        target_index = 0 if self._last_focus_id == "input" else 1
        self._focus_scope.manager.focus(target_index)
        
        is_input_focused = (self._last_focus_id == "input")
        is_history_focused = (self._last_focus_id == "history")
        
        # Auto-scroll to bottom when input field is focused
        if is_input_focused:
            self.chat_history_panel.auto_scroll = True
            self.chat_history_panel.scroll_offset = 0

    def _set_input_focus(self, focused: bool):
        self.input_component.set_focused(focused)
        self.input_box.set_focused(focused)

    def _set_history_focus(self, focused: bool):
        self.chat_history_panel.set_keyboard_focus(focused)

    def _set_app_focus(self, focus_id: str):
        if focus_id not in ("input", "history"):
            raise ValueError(f"Unknown application focus target: {focus_id}")
        self._last_focus_id = focus_id
        self._focus_scope.manager.focus(0 if focus_id == "input" else 1)
        self._update_focus_states()

    def handle_global_input(self, event: Any) -> bool:
        """Handle focus logging and input dispatch with navigation between input and history."""
        
        # Advance the status-bar spinner while .local resolution or model
        # name discovery is pending. The input cursor blink is driven by the
        # input component's own handle_input(TickEvent) path.
        if isinstance(event, TickEvent):
            from pico_chat.harness.llm_server import is_local_resolution_pending
            server = getattr(self._initial_agent, "server", None)
            if server is not None and (
                is_local_resolution_pending(server._original_base_url)
                or getattr(server, "_model_name_pending", False)
            ):
                self._status_spinner_frame += 1
                self.refresh_status_bar()
            return False

        # Handle keyboard navigation between input and history
        if isinstance(event, (str, KeyEvent)):
            key = event.key if isinstance(event, KeyEvent) else event
            if self._last_focus_id == "input" and self.input_component.has_active_completion():
                if key in ('\x1b', '\x1b[A', '\x1b[B', '\t', '\r', '\n'):
                    return self.input_component.handle_input(event)

            # Shortcuts to focus input: 'i' or Enter (when not already in input)
            if (key == 'i' or key == '\r') and self._last_focus_id != "input":
                self.chat_history_panel.clear_focus()
                self._set_app_focus("input")
                return True
            
            if key == '\x1b[A':  # Up arrow
                # If input has focus and cursor is on first line, move to history
                if self._last_focus_id == "input" and self.input_component.is_cursor_on_first_line():
                    # Focus the last message (or the first message if list is empty)
                    if self.chat_history_panel.messages:
                        self.chat_history_panel.set_focused_message(len(self.chat_history_panel.messages) - 1)
                        self._set_app_focus("history")
                        return True
                # Otherwise, let the event pass through to the active component
            
            elif key == '\x1b[B':  # Down arrow
                # Only handle focus change when in history (not when in input)
                if self._last_focus_id == "history" and self.chat_history_panel.focused_message_index is not None:
                    if self.chat_history_panel.focused_message_index == len(self.chat_history_panel.messages) - 1:
                        # At the bottom of history, switch to input
                        self.chat_history_panel.clear_focus()
                        self._set_app_focus("input")
                        return True
                # Otherwise: if in input, let DOWN work normally for cursor movement
                # If in history (not at bottom), let it navigate messages normally
        
        # Handle mouse click focus changes
        if isinstance(event, MouseEvent):
            # Ignore wheel scroll events for focus purposes — they shouldn't
            # change focus, only scroll the panel under the cursor.
            if event.pressed and event.button not in (64, 65):
                clicked_focus = self._focus_scope.focus_at(event.x, event.y)
                # Clicking the input box (including its top/bottom bars) or the
                # status bar should always return focus to the input field.
                in_input_box = (
                    self.input_box.x <= event.x < self.input_box.x + self.input_box.width
                    and self.input_box.y <= event.y < self.input_box.y + self.input_box.height
                )
                if not clicked_focus and in_input_box:
                    # Clicking the input box (bars or field) focuses input.
                    self._set_app_focus("input")
                    self.chat_history_panel.clear_focus()
                    return True
                elif clicked_focus:
                    target_id = "input" if self._focus_scope.focused_index == 0 else "history"
                    if target_id == "input":
                    # Clear focused message when clicking input
                        self.chat_history_panel.clear_focus()
                    
                    if target_id != self._last_focus_id:
                    # Log focus change
                        import logging
                        logger = logging.getLogger("harness")
                        logger.info(f"[UI] Focus changed to: {target_id}")
                        self._set_app_focus(target_id)
            
        # Normal events are dispatched by EventRouter to the active focus target.
        return False


    def render(self, force_full=False):
        if not self.compositor or self.compositor.width == 0 or self.compositor.height == 0:
            return

        self.compositor.buffer.clear()
        self.root.set_layout(0, 0, self.compositor.width, self.compositor.height)
        self.root.render(self.compositor.buffer)
        
        # Use Buffer's built-in render method
        output = self.compositor.buffer.render()
        sys.stdout.write(output)
        sys.stdout.flush()

    async def run(self):
        """Run the TUI application."""
        import logging
        logger = logging.getLogger("tui")
        logger.info("Starting Pico-Chat TUI application")
        
        # Start the harness services if available
        if hasattr(self.agent, 'start'):
            self.agent.start()
            logger.info("Agent started")
        
        self.tab_view.on_change = self._on_tab_view_change
        self.tab_view.on_close = self._on_tab_view_close
        self.tab_view.can_close = self._can_close_tab
        self.tab_view.set_on_new(self._new_tab)
        
        # Start with an actual empty conversation tab rather than no tabs.
        if not self._tabs:
            self._new_tab()
        
        chat_screen = ChatScreen(
            self.tab_bar,
            self.chat_history_panel,
            self.input_box,
            self._focus_scope,
            self._tabs[self._active_tab_index] if self._tabs else None,
            self.status_bar,
        )
        self._chat_workspace = chat_screen.workspace
        self.root = chat_screen.root  # Store root for global handler
        self.compositor = Compositor(self.root, fps=TARGET_FPS, shutdown_event=self.shutdown_event)
        self.compositor.padding = pico_cfg.config.ui_app_global_padding  # Apply global padding from config
        self.modal_host = ModalHost(self.compositor)
        self._focus_scope.enter()
        self.navigator = Navigator(
            self.compositor,
            chat_screen,
        )
        
        self.compositor.event_router.set_interceptor(self.handle_global_input)
        self.compositor.event_router.set_focus_scope(self._focus_scope)

        # Set compositor for all panels
        self.chat_history_panel.set_compositor(self.compositor)
        self.input_component.set_compositor(self.compositor)
        
        self.chat_history_panel.on_action = self._handle_message_action
        
        # Set initial focus states
        self._update_focus_states()
        self.refresh_status_bar()

        # Start background server status check (non-blocking). No status
        # message is added to the conversation — the status bar reflects it.
        async def background_startup_check():
            status = await self.agent.get_status()
            self.refresh_status_bar()
            logger.info(f"Server status online: {status['online']}")

            # Show any startup warnings (e.g. not a git repository)
            for warning in self.agent.startup_warnings:
                self.chat_history_panel.add_message(
                    warning,
                    msg_type=SysMsgWarning(),
                )

        # Run all tasks
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self.compositor.run())
                tg.create_task(self.command_worker())
                for runtime in self._tabs:
                    self._ensure_runtime_worker(runtime)
                tg.create_task(background_startup_check())
        except Exception:
            # On exception, cleanup without clearing screen to preserve traceback
            if self.compositor and self.compositor.terminal:
                self.compositor.terminal.cleanup(clear_screen=False)
            
            # Clean shutdown
            if hasattr(self.agent, 'stop'):
                self.agent.stop()
            
            # Re-raise to display traceback
            raise
        finally:
            # Normal exit cleanup (clear screen OK)
            if self.compositor and self.compositor.terminal:
                self.compositor.terminal.cleanup(clear_screen=True)
            
            # Clean shutdown
            if hasattr(self.agent, 'stop'):
                self.agent.stop()