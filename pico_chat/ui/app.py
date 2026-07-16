"""
Pico-Chat TUI Application.
"""

import sys
import os
import asyncio
import atexit
from turtle import done
from typing import Optional, Any

from openai import chat
import openai

from pico_chat.ui.tui.compositor import Compositor
from pico_chat.ui.tui.terminal import MouseEvent
from pico_chat.ui.tui.components import TextComponent, Box, InputComponent
from pico_chat.ui.tui.components.debug_panel import DebugLogPanel
from pico_chat.ui.tui.components.popup import Popup
from pico_chat.ui.tui.components.form_popup import FormPopup
from pico_chat.ui.chat_history_panel import ChatHistoryPanel
from pico_chat.ui.chat_message import Message
from pico_chat.ui.commands import handle_command, get_command_list, get_subcommand_list
from pico_chat.ui.tui.container import Hsplit
from pico_chat.ui.tui.layout_utils import strip_ansi

        # Setup logging to debug panel
import logging
from pico_chat.ui.commands import StatusCommand
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import MsgType, PicoMsg, ThinkingMsg, UserMsg, SysMsg, SysMsgError, SysMsgWarning, ToolCallMsg, ToolDraftMsg, AskPermissionMsg

from pico_chat import pico_cfg
from pico_chat.ui.logging_handlers import setup_tui_logging
from pico_chat.ui.chat_action_handlers import ChatActionHandlers

# Import chunks module for type checking
from pico_chat.harness import chunks

TARGET_FPS = pico_cfg.config.target_fps

class chatTUI(ChatActionHandlers):
    """Terminal UI for the agent."""

    def __init__(self, agent):
        self.agent = agent
        self.message_queue: asyncio.Queue[tuple[str, Message]] = asyncio.Queue()  # Queue of (text, user_message)
        self.compositor: Optional[Compositor] = None
        self._last_focus_id: Optional[str] = "input"  # Start with input focused
        
        # Get colors from config
        self.chat_history_panel = ChatHistoryPanel()
        
        # New: Direct InputComponent usage
        self.input_component = InputComponent(" ", id="entry", frame_color=theme.USER)
        self.input_component.config = pico_cfg.config  # Pass config for max height, cursor settings, etc.
        self.input_component.on_submit = self.on_user_submit
        
        # Setup command completion
        commands = get_command_list()
        self.input_component.setup_commands(commands)
        
        # Setup subcommand completion
        self.input_component.setup_subcommands(get_subcommand_list)
        
        # Setup context (@file) completion
        get_context_items = lambda: agent.list_files_and_folders() if hasattr(agent, 'list_files_and_folders') else []
        self.input_component.setup_context(get_context_items)

        # Setup generic argument completion (driven by Command.params schema)
        from pico_chat.ui.commands import COMMANDS
        self.input_component.setup_command_registry(COMMANDS)
        
        self.input_box = Box(self.input_component, title="message", fg=self.input_component.frame_color)

        # Debug console
        self.debug_panel = DebugLogPanel(
            max_lines=1000,
            frame_color=theme.ERROR,
            content_color=theme.MUTED,
            left_pad=1,
            right_pad=0
        )
        self.debug_box = Box(self.debug_panel, title="debug console", fg=self.debug_panel.frame_color)
        self.show_debug = False
        
        # Popup overlay for commands like /help, /status, etc.
        self.popup = Popup()
        
        # Form popup overlay for interactive forms (server add, git commit, etc.)
        self.form_popup = FormPopup()
        
        # Setup logging to debug panel
        self.log_handler = setup_tui_logging(self.debug_panel)
        
        # Track the current generation task
        self.current_generation_task: Optional[asyncio.Task] = None

        # Track the user input/message currently being generated (for steer/pause/resume)
        self._active_user_input: Optional[str] = None
        self._active_user_msg: Optional[Message] = None

        # Set by handle_steer_action so agent_worker re-queues the active input
        # after cancellation (with the thinking prefill already set).
        self._requeue_after_cancel: bool = False

        # Pause context: populated by handle_pause_action, cleared by handle_resume_action
        self._paused_user_input: Optional[str] = None
        self._paused_user_msg: Optional[Message] = None

        # Set when the user edits a paused message's thinking prefill instead of a
        # normal user message; on submit we call set_thinking_prefill + resume.
        self.editing_prefill_for_resume: bool = False
        
        # Track which message is being edited (for edit-then-submit workflow)
        self.editing_message_index: Optional[int] = None
        
        # Track pending permission requests
        self.pending_permission_prompt: Optional[str] = None
        
        # Track active tool messages by call_id
        self.active_tool_messages = {}  # tool_call_id -> Message
        
        # Command queue for structured execution
        self.command_queue = asyncio.Queue()
        
        # Shutdown event for coordinated exit
        self.shutdown_event = asyncio.Event()
        
        # Register cleanup handler for abnormal exits
        atexit.register(self._emergency_cleanup)
        
    def _emergency_cleanup(self):
        """Emergency cleanup handler called by atexit."""
        if self.compositor and self.compositor.terminal:
            try:
                # Don't clear screen in emergency cleanup to preserve errors
                self.compositor.terminal.cleanup(clear_screen=False)
            except Exception:
                pass  # Silently fail in atexit handler
    
    @staticmethod
    def _rgb_to_ansi_fg(r: int, g: int, b: int) -> str:
        """Convert RGB to ANSI foreground color code."""
        return f"\033[38;2;{r};{g};{b}m"

    async def _process_generation(self, user_input: str, user_msg: Message):
        """Process a single generation request.
        
        Args:
            user_input: The text input from the user
            user_msg: The UI message object representing the user's message
        """
        import logging
        logger = logging.getLogger("tui")
        logger.info(f"Starting generation for user input: {user_input[:50]}...")
        
        # Show thinking indicator
        chat = self.chat_history_panel
        current_msg = chat.add_message("Sending request...", msg_type=SysMsg())
        
        current_msg_type = SysMsg  # Track the type of current message
        current_harness_ids = []  # Track harness message IDs for current UI message
        processing_msg = None  # Track the "processing..." message to replace it

        def ensure_tool_message_type(msg: Message, target_type: MsgType) -> Message:
            """Replace message with a new one if type differs, preserving tool metadata."""
            if isinstance(msg.type, type(target_type)):
                return msg

            new_msg = chat.new_message(
                "",
                msg_type=target_type,
                harness_message_ids=msg.harness_message_ids or current_harness_ids
            )
            new_msg.tool_name = msg.tool_name
            new_msg.tool_args = msg.tool_args
            new_msg.tool_output = msg.tool_output
            new_msg.tool_status = msg.tool_status
            new_msg.show_output = msg.show_output
            chat.replace_message(msg, new_msg)
            return new_msg

        if self.compositor and hasattr(self.compositor, "set_streaming_active"):
            self.compositor.set_streaming_active(True)
        
        # Process streaming response from Harness
        try:
            async for chunk in self.agent.chat(user_input):
                if self.compositor and hasattr(self.compositor, "request_render"):
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
                        if current_msg_type == SysMsg:
                            # Replace "Sending request..." or "Processing results..." with thinking
                            new_msg = chat.new_message("", msg_type=ThinkingMsg(), harness_message_ids=current_harness_ids)
                            chat.replace_message(current_msg, new_msg)
                            current_msg = new_msg
                            processing_msg = None  # Clear processing indicator
                        else:
                            # Finalize previous and create new
                            current_msg.finalize()
                            current_msg = chat.add_message("", msg_type=ThinkingMsg(), harness_message_ids=current_harness_ids)
                        current_msg_type = ThinkingMsg
                    
                    current_msg.append(chunk.content)
                
                elif isinstance(chunk, chunks.Content):
                    # If not currently in a content message, create one
                    if current_msg_type != PicoMsg:
                        if current_msg_type == SysMsg:
                            # Replace "Sending request..." or "Processing results..." with content
                            new_msg = chat.new_message("", msg_type=PicoMsg(), harness_message_ids=current_harness_ids)
                            chat.replace_message(current_msg, new_msg)
                            current_msg = new_msg
                            processing_msg = None  # Clear processing indicator
                        else:
                            # Finalize previous and create new
                            current_msg.finalize()
                            current_msg = chat.add_message("", msg_type=PicoMsg(), harness_message_ids=current_harness_ids)
                        current_msg_type = PicoMsg
                    
                    current_msg.append(chunk.content)
                
                elif isinstance(chunk, chunks.ToolDraft):
                    tool_id = chunk.tool_call_id
                    msg = self.active_tool_messages.get(tool_id)
                    preserve_active_text_stream = current_msg_type in (ThinkingMsg, PicoMsg)

                    # Flush any incomplete text message before showing tool draft
                    if current_msg_type in (ThinkingMsg, PicoMsg) and current_msg:
                        current_msg.finalize()

                    if not msg:
                        if current_msg_type == SysMsg:
                            # Replace processing message with tool draft
                            msg = chat.new_message("", msg_type=ToolDraftMsg(), harness_message_ids=current_harness_ids)
                            chat.replace_message(current_msg, msg)
                            processing_msg = None  # Clear processing indicator
                        else:
                            msg = chat.add_message("", msg_type=ToolDraftMsg(), harness_message_ids=current_harness_ids)
                        self.active_tool_messages[tool_id] = msg

                    msg = ensure_tool_message_type(msg, ToolDraftMsg())
                    self.active_tool_messages[tool_id] = msg
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
                        msg = self.active_tool_messages.get(tool_id)

                        if chunk.auto_decision:
                            # Auto-decision: show status marker
                            if not msg:
                                msg = chat.add_message(
                                    "",  # Will be built by rebuild_tool_display
                                    msg_type=ToolCallMsg(),
                                    harness_message_ids=current_harness_ids
                                )
                                self.active_tool_messages[tool_id] = msg
                                processing_msg = None  # Clear processing indicator if showing new tool

                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            self.active_tool_messages[tool_id] = msg
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
                                self.active_tool_messages[tool_id] = msg
                                processing_msg = None  # Clear processing indicator

                            msg = ensure_tool_message_type(msg, AskPermissionMsg())
                            self.active_tool_messages[tool_id] = msg
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
                            self._last_focus_id = "history"
                            self._update_focus_states()
                            
                            # Force compositor render to show actions immediately
                            if self.compositor:
                                self.compositor.render()
                            
                            # Store prompt for handler
                            self.pending_permission_prompt = chunk.permission_prompt

                        current_msg = msg
                        current_msg_type = type(msg.type)
                    
                    elif chunk.status == chunks.ToolStatus.APPROVED:
                        msg = self.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            self.active_tool_messages[tool_id] = msg
                            # Update status
                            msg.tool_name = chunk.tool_name
                            msg.tool_args = chunk.tool_args
                            msg.tool_status = "approved"
                            msg.rebuild_tool_display()
                        self.pending_permission_prompt = None
                    
                    elif chunk.status == chunks.ToolStatus.DENIED:
                        msg = self.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            msg.tool_name = chunk.tool_name
                            msg.tool_args = chunk.tool_args
                            msg.tool_status = "denied"
                            msg.tool_output = chunk.denial_reason
                            msg.show_output = True  # Always show denial reason
                            msg.rebuild_tool_display()
                            msg.finalize()
                            del self.active_tool_messages[tool_id]
                        self.pending_permission_prompt = None
                    
                    elif chunk.status == chunks.ToolStatus.EXECUTING:
                        msg = self.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            self.active_tool_messages[tool_id] = msg
                            # Update status to show executing
                            msg.tool_status = "approved | executing"
                            msg.rebuild_tool_display()
                    
                    elif chunk.status == chunks.ToolStatus.COMPLETED:
                        msg = self.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            # Store output and update to completed
                            msg.tool_status = "approved | completed"
                            msg.tool_output = chunk.result or ""
                            msg.rebuild_tool_display()
                            msg.finalize()
                            del self.active_tool_messages[tool_id]
                            
                            # Show processing indicator after tool completes
                            # This will be replaced by the next content/thinking/tool
                            if processing_msg is None or processing_msg.finalized:
                                import time
                                processing_start_time = time.time()
                                
                                async def update_processing_time():
                                    """Update processing message with elapsed time."""
                                    await asyncio.sleep(2.0)  # Wait 2 seconds before showing timer
                                    while processing_msg and not processing_msg.finalized:
                                        elapsed = int(time.time() - processing_start_time)
                                        if elapsed >= 2:
                                            processing_msg.set_text(
                                                f"{theme.MUTED}Processing results... ({elapsed}s){theme.reset()}"
                                            )
                                            if self.compositor:
                                                self.compositor.request_render()
                                        await asyncio.sleep(1.0)
                                
                                processing_msg = chat.add_message(
                                    f"{theme.MUTED}Processing results...{theme.reset()}",
                                    msg_type=SysMsg(),
                                    harness_message_ids=current_harness_ids
                                )
                                current_msg = processing_msg
                                current_msg_type = SysMsg
                                
                                # Start background timer task
                                asyncio.create_task(update_processing_time())
                    
                    elif chunk.status == chunks.ToolStatus.ERROR:
                        msg = self.active_tool_messages.get(tool_id)
                        if msg:
                            msg = ensure_tool_message_type(msg, ToolCallMsg())
                            msg.tool_status = "error"
                            msg.tool_output = chunk.error
                            msg.show_output = True  # Always show errors
                            msg.rebuild_tool_display()
                            msg.finalize()
                            del self.active_tool_messages[tool_id]
                
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

                # Ensure we scroll to bottom if needed
                if self.chat_history_panel.auto_scroll:
                    self.chat_history_panel.scroll_offset = 0
                    # Auto-focus input when new messages arrive (if at bottom)
                    # BUT: Don't steal focus if user has explicitly focused a message
                    if self._last_focus_id != "input" and self.chat_history_panel.focused_message_index is None:
                        self._last_focus_id = "input"
                        self._update_focus_states()

                # Yield to let the compositor render the update
                await asyncio.sleep(0)
                
        except asyncio.CancelledError:
            # Finalize current message and add a plain SysMsg notification.
            # Avoid appending ANSI codes to a MarkdownComponent message (PicoMsg)
            # since the component would render the escape sequences as literal text.
            current_msg.finalize()
            chat.add_message("[Generation stopped]", msg_type=SysMsg())
            raise 
            
        except Exception as e:
            raise e
    
        finally:
            if self.compositor and hasattr(self.compositor, "set_streaming_active"):
                self.compositor.set_streaming_active(False)
            if current_msg is not None:
                current_msg.finalized = True
                current_msg.update_actions()
            
            
        
    async def agent_worker(self):
        """Background worker that processes harness requests."""
        
        while not self.shutdown_event.is_set():
            try:
                msg_task = asyncio.create_task(self.message_queue.get())
                cmd_task = asyncio.create_task(self.command_queue.get())
                shutdown_task = asyncio.create_task(self.shutdown_event.wait())

                done, pending = await asyncio.wait(
                    [msg_task, cmd_task, shutdown_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # cancel the tasks that didn't complete
                for p in pending:
                    p.cancel()

                # If shutdown was triggered, exit immediately
                if shutdown_task in done:
                    # Cancel any active generation
                    if self.current_generation_task and not self.current_generation_task.done():
                        self.current_generation_task.cancel()
                    break

                completed = done.pop()

                # distinguish source
                if completed is cmd_task:
                    command = completed.result()
                    import logging
                    logger = logging.getLogger("tui")
                    logger.debug(f"Processing command: {command}")
                    await handle_command(self, command)  # exceptions propagate → crash
                else:
                    user_input, user_msg = completed.result()
                    import logging
                    logger = logging.getLogger("tui")
                    logger.debug("Agent worker received user input")

                    # Skip messages that were consumed as steer injections
                    if getattr(user_msg, 'is_steered', False):
                        logger.debug("Skipping steered message (already consumed as thinking prefill)")
                        continue

                    # Un-queue: restore normal visual state before processing
                    if getattr(user_msg, 'is_queued', False):
                        user_msg.is_queued = False
                        user_msg.set_title("user")
                        from pico_chat.ui.tui.colors import theme
                        user_msg.set_frame_color(theme.USER)

                    # Track the active user input for steer/pause/resume
                    self._active_user_input = user_input
                    self._active_user_msg   = user_msg

                    self.current_generation_task = asyncio.create_task(
                        self._process_generation(user_input, user_msg)
                    )

                    # Wait for generation to complete, but keep checking for commands
                    try:
                        while not self.current_generation_task.done():
                            # Wait for EITHER generation to finish OR a command to arrive
                            cmd_task = asyncio.create_task(self.command_queue.get())
                            gen_task = self.current_generation_task
                            shutdown_task = asyncio.create_task(self.shutdown_event.wait())
                            
                            done, pending = await asyncio.wait(
                                [cmd_task, gen_task, shutdown_task],
                                return_when=asyncio.FIRST_COMPLETED
                            )
                            
                            # Handle shutdown - cancel everything
                            if shutdown_task in done:
                                # Cancel command task if it's pending
                                if cmd_task in pending:
                                    cmd_task.cancel()
                                # Cancel generation
                                if not self.current_generation_task.done():
                                    self.current_generation_task.cancel()
                                return
                            
                            # Handle command during generation
                            if cmd_task in done:
                                command = cmd_task.result()
                                logger.debug(f"Processing command during generation: {command}")
                                # Cancel shutdown task if pending
                                if shutdown_task in pending:
                                    shutdown_task.cancel()
                                # DO NOT cancel generation - keep it running!
                                await handle_command(self, command)
                                # Continue loop to wait for more commands or generation completion
                            
                            # Generation completed
                            if gen_task in done:
                                # Cancel pending tasks
                                if cmd_task in pending:
                                    cmd_task.cancel()
                                if shutdown_task in pending:
                                    shutdown_task.cancel()
                                # Check if it raised an exception
                                try:
                                    gen_task.result()
                                except asyncio.CancelledError:
                                    pass
                                break
                    
                    except asyncio.CancelledError:
                        pass
                    finally:
                        self.current_generation_task = None
                        # Steer action: re-queue the active input so it is
                        # regenerated with the thinking prefill already in place.
                        if self._requeue_after_cancel and self._active_user_input:
                            self.message_queue.put_nowait(
                                (self._active_user_input, self._active_user_msg)
                            )
                        self._requeue_after_cancel = False
                        self._active_user_input = None
                        self._active_user_msg   = None

            except asyncio.TimeoutError:
                continue
            
            except Exception as e: # Errors during generation or processing
                import logging
                import httpx
                import httpcore
                logger = logging.getLogger("tui")
   
                network_exceptions = (
                    httpx.RemoteProtocolError,
                    httpx.ReadError,
                    httpx.ConnectError,
                    httpx.ReadTimeout,
                    httpcore.RemoteProtocolError,
                    httpcore.ReadError,
                    httpcore.ConnectError,
                )

                recoverable_exceptions = (
                    openai.APIConnectionError,
                    openai.InternalServerError,
                ) + network_exceptions
                
                # Check if it's a recoverable error (use isinstance for subclass coverage)
                is_recoverable = isinstance(e, recoverable_exceptions)
                
                # Special case: 503 model loading errors should show a better message
                if isinstance(e, openai.InternalServerError) and e.status_code == 503:
                    error_message = str(e)
                    if "Loading model" in error_message or "unavailable" in error_message.lower():
                        logger.warning(f"Model still loading after retries: {str(e)}")
                        self.chat_history_panel.add_message(
                            message="Model is still loading. Please wait a moment and try again.",
                            msg_type=SysMsgError()
                        )
                        continue  # Don't crash, just continue event loop
                
                if is_recoverable:
                    logger.warning(f"Recoverable error: {type(e).__name__}: {str(e)}")
                    # Give a friendlier message for raw network errors
                    if isinstance(e, network_exceptions):
                        self.chat_history_panel.add_message(
                            message="Server closed the connection mid-stream (the model may have crashed). Response may be incomplete.",
                            msg_type=SysMsgError()
                        )
                    else:
                        self.chat_history_panel.add_message(
                            message=f"{str(e)}",
                            msg_type=SysMsgError()
                        )
                    
                else: # raise for non-recoverable errors
                    logger.error(f"Non-recoverable error: {type(e).__name__}: {str(e)}", exc_info=True)
                    raise e

    def stop_generation(self):
        """Stop the current generation task if active."""
        if self.current_generation_task and not self.current_generation_task.done():
            self.current_generation_task.cancel()
            return True
        return False

    def on_command_submit(self, text: str):
        """Handle execution of commands."""
        self.command_queue.put_nowait(text)
        
    def toggle_debug_console(self):
        """Toggle the visibility of the debug console."""
        import logging
        self.show_debug = not self.show_debug
        logger = logging.getLogger("tui")
        logger.info(f"Debug console toggled: {'visible' if self.show_debug else 'hidden'}")
        
        children = [
            self.chat_history_panel.get_component(),
            self.input_box
        ]
        sizes = ["100%", 0]
        
        if self.show_debug:
            children.insert(0, self.debug_box)
            sizes.insert(0, pico_cfg.config.ui_debug_console_height)
            
        # Update the root container (Hsplit)
        if isinstance(self.root, Hsplit):
            self.root.children = children
            self.root.sizes = sizes
            # Update parent references
            for child in children:
                child.parent = self.root

    def show_popup(self, title: str, content: str):
        """Show a popup overlay with the given title and content."""
        self.popup.set_compositor(self.compositor)
        self.popup.show(title, content)

    def hide_popup(self):
        """Hide the popup overlay."""
        self.popup.hide()

    def show_form_popup(self, title: str, fields: list, on_submit, on_cancel=None):
        """Show a form popup overlay with interactive fields."""
        self.form_popup.set_compositor(self.compositor)
        self.form_popup.show(title, fields, on_submit, on_cancel)


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

        if clean_text.lower() in ["exit", "quit", "q"]:
            if self.compositor:
                self.compositor.running = False
        else:
            import logging
            logger = logging.getLogger("tui")
            
            # Check if we're editing an existing message
            if self.editing_message_index is not None:
                logger.info(f"Editing message at index {self.editing_message_index}: {text[:50]}...")
                
                # Get the message being edited
                if self.editing_message_index < len(self.chat_history_panel.messages):
                    edited_msg = self.chat_history_panel.messages[self.editing_message_index]
                    
                    # Delete from harness history starting at this message's ID
                    if edited_msg.harness_message_ids:
                        harness_id = edited_msg.harness_message_ids[0]
                        if self.agent.delete_messages_after_id(harness_id, inclusive=True):
                            logger.info(f"Deleted harness messages after ID {harness_id}")
                    
                    # Update the message text in place
                    edited_msg.set_text(text)
                    
                    # Clear its harness ID (will be reassigned)
                    edited_msg.harness_message_ids = []
                    
                    # Remove all UI messages AFTER the edited one (keep edited message visible)
                    messages_to_remove = len(self.chat_history_panel.messages) - self.editing_message_index - 1
                    for _ in range(messages_to_remove):
                        self.chat_history_panel.remove_last_message()
                    
                    # Queue the edited message for processing
                    self.message_queue.put_nowait((text, edited_msg))
                else:
                    # Message was deleted (e.g., via /clear) - treat as new message
                    logger.warning(f"Edited message at index {self.editing_message_index} no longer exists, creating new message")
                    user_msg = self.chat_history_panel.add_message(text, msg_type=UserMsg())
                    self.message_queue.put_nowait((text, user_msg))
                
                # Clear editing state
                self.editing_message_index = None
            else:
                logger.info(f"User submitted: {text[:50]}...")
                
                # Create user message and queue it
                user_msg = self.chat_history_panel.add_message(text, msg_type=UserMsg())

                # If a generation is active, mark as queued so the UI shows it
                if self.current_generation_task and not self.current_generation_task.done():
                    user_msg.is_queued = True
                    user_msg.set_title("user (queued)")
                    user_msg.set_frame_color(
                        getattr(__import__('pico_chat.ui.tui.colors', fromlist=['theme']).theme, 'MUTED')
                    )

                self.message_queue.put_nowait((text, user_msg))
            
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

    def _update_focus_states(self):
        """Update focus states of components based on _last_focus_id."""
        # Default to input focus if nothing is focused
        if self._last_focus_id is None:
            self._last_focus_id = "input"
        
        is_input_focused = (self._last_focus_id == "input")
        is_history_focused = (self._last_focus_id == "history")
        
        # Update input component focus state
        self.input_component.set_focused(is_input_focused)
        
        # Update input box border style
        self.input_box.set_focused(is_input_focused)
        
        # Update chat history keyboard focus
        self.chat_history_panel.set_keyboard_focus(is_history_focused)
        
        # Auto-scroll to bottom when input field is focused
        if is_input_focused:
            self.chat_history_panel.auto_scroll = True
            self.chat_history_panel.scroll_offset = 0

    def handle_global_input(self, event: Any) -> bool:
        """Handle focus logging and input dispatch with navigation between input and history."""
        
        # Popup takes priority — all input goes to popup when visible
        if self.popup.is_visible:
            return self.popup.handle_input(event)
        
        # Form popup takes priority — all input goes to form when visible
        if self.form_popup.is_visible:
            return self.form_popup.handle_input(event)
        
        # Handle keyboard navigation between input and history
        if isinstance(event, str):
            if self._last_focus_id == "input" and self.input_component.has_active_completion():
                if event in ('\x1b', '\x1b[A', '\x1b[B', '\t', '\r', '\n'):
                    return self._original_handle_input(event)

            # Shortcuts to focus input: 'i' or Enter (when not already in input)
            # Skip when an inline editor is active (Enter must go to the editor)
            if (event == 'i' or event == '\r') and self._last_focus_id != "input" \
                    and not self.chat_history_panel._inline_editing_msg:
                self.chat_history_panel.clear_focus()
                self._last_focus_id = "input"
                self._update_focus_states()
                return True
            
            if event == '\x1b[A':  # Up arrow
                # If input has focus and cursor is on first line, move to history
                if self._last_focus_id == "input" and self.input_component.is_cursor_on_first_line():
                    # Focus the last message (or the first message if list is empty)
                    if self.chat_history_panel.messages:
                        self.chat_history_panel.set_focused_message(len(self.chat_history_panel.messages) - 1)
                        self._last_focus_id = "history"
                        self._update_focus_states()
                        return True
                # Otherwise, let the event pass through to the active component
            
            elif event == '\x1b[B':  # Down arrow
                # Only handle focus change when in history (not when in input)
                if self._last_focus_id == "history" and self.chat_history_panel.focused_message_index is not None:
                    if self.chat_history_panel.focused_message_index == len(self.chat_history_panel.messages) - 1:
                        # At the bottom of history, switch to input
                        self.chat_history_panel.clear_focus()
                        self._last_focus_id = "input"
                        self._update_focus_states()
                        return True
                # Otherwise: if in input, let DOWN work normally for cursor movement
                # If in history (not at bottom), let it navigate messages normally
        
        # Handle mouse click focus changes
        if isinstance(event, MouseEvent):
            if event.pressed:
                # Find which component was clicked to log focus
                target_id = None
                
                # Very simple hit detection for our two main panels
                h_comp = self.chat_history_panel.get_component()
                i_box = self.input_box
                
                if h_comp.x <= event.x < h_comp.x + h_comp.width and \
                   h_comp.y <= event.y < h_comp.y + h_comp.height:
                    target_id = "history"
                elif i_box.x <= event.x < i_box.x + i_box.width and \
                     i_box.y <= event.y < i_box.y + i_box.height:
                    target_id = "input"
                    # Clear focused message when clicking input
                    self.chat_history_panel.clear_focus()
                    
                if target_id and target_id != self._last_focus_id:
                    # Log focus change
                    import logging
                    logger = logging.getLogger("harness")
                    logger.info(f"[UI] Focus changed to: {target_id}")
                    self._last_focus_id = target_id
                    self._update_focus_states()
            
        # Call the original method to avoid infinite recursion
        return self._original_handle_input(event)


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
        
        # Column
        children = [
            self.chat_history_panel.get_component(),
            self.input_box
        ]
        sizes = ["100%", 0]
        
        if self.show_debug:
            children.insert(0, self.debug_box)
            sizes.insert(0, pico_cfg.config.ui_debug_console_height)
            
        column = Hsplit(children, sizes) # 0 means use preferred height

        # Main Layout
        root = column
        self.root = root  # Store root for global handler
        self.compositor = Compositor(root, fps=TARGET_FPS, shutdown_event=self.shutdown_event)
        self.compositor.padding = pico_cfg.config.ui_app_global_padding  # Apply global padding from config
        
        # Store the original handle_input method before overriding
        self._original_handle_input = root.handle_input
        self.root.handle_input = self.handle_global_input

        # Set compositor for all panels
        self.chat_history_panel.set_compositor(self.compositor)
        self.input_component.set_compositor(self.compositor)
        
        # Wire up action handlers
        self.chat_history_panel.on_copy_action = self.handle_copy_action
        self.chat_history_panel.on_edit_action = self.handle_edit_action
        self.chat_history_panel.on_retry_action = self.handle_retry_action
        self.chat_history_panel.on_stop_action = self.handle_stop_action
        self.chat_history_panel.on_allow_action = self.handle_allow_action
        self.chat_history_panel.on_deny_action = self.handle_deny_action
        self.chat_history_panel.on_output_action = self.handle_output_action
        self.chat_history_panel.on_steer_action = self.handle_steer_action
        self.chat_history_panel.on_pause_action = self.handle_pause_action
        self.chat_history_panel.on_resume_action = self.handle_resume_action
        self.chat_history_panel.on_delete_action = self.handle_delete_action
        
        # Set initial focus states
        self._update_focus_states()
        
        # Start background server status check (non-blocking)
        async def background_startup_check():
            # Show placeholder while checking status
            placeholder = self.chat_history_panel.add_message(
                "Checking server status...",
                msg_type=SysMsg(),
                title="status"
            )
            
            # Get actual status (may take time if server is unreachable)
            status = await self.agent.get_status()
            
            # Replace placeholder with actual status
            status_msg = self.chat_history_panel.new_message(
                StatusCommand.format_status(status),
                msg_type=SysMsg(),
                title="status"
            )
            self.chat_history_panel.replace_message(placeholder, status_msg)
            
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
                tg.create_task(self.agent_worker())
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