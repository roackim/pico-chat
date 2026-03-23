"""Pico-Chat TUI Application."""

import sys
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
from pico_chat.ui.chat_history_panel import ChatHistoryPanel
from pico_chat.ui.chat_message import Message
from pico_chat.ui.commands import handle_command, get_command_list, get_subcommand_list
from pico_chat.ui.tui.container import Vsplit, Hsplit
from pico_chat.ui.tui.layout_utils import strip_ansi

        # Setup logging to debug panel
import logging
from pico_chat.ui.commands import StatusCommand
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.msg_types import PicoMsg, ThinkingMsg, UserMsg, SysMsg, SysMsgError, ToolPermissionMsg

from pico_chat import pico_cfg

# Import chunks module for type checking
from pico_chat.harness import chunks

TARGET_FPS = 60
# TARGET_FPS = pico_cfg.target_fps

class chatTUI:
    """Terminal UI for the agent."""

    def __init__(self, agent):
        self.agent = agent
        self.message_queue = asyncio.Queue()
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
        
        class TuiLogHandler(logging.Handler):
            def __init__(self, panel):
                super().__init__()
                self.panel = panel
                # Only show logs from internal code, not external libraries
                self.allowed_prefixes = ('pico_chat', 'harness', 'tui', '__main__')
                self.blocked_prefixes = ('httpcore', 'httpx', 'openai', 'urllib3', 'asyncio')
            
            def emit(self, record):
                try:
                    # Filter out external library logs
                    logger_name = record.name
                    
                    # Block known noisy libraries
                    if any(logger_name.startswith(prefix) for prefix in self.blocked_prefixes):
                        return
                    
                    # Allow internal loggers or warn/error from any source
                    is_internal = any(logger_name.startswith(prefix) for prefix in self.allowed_prefixes)
                    is_important = record.levelno >= logging.WARNING
                    
                    if is_internal or is_important:
                        msg = self.format(record)
                        self.panel.log(msg)
                except Exception:
                    self.handleError(record)
        
        # Custom formatter that adds orange color to timestamp
        class ColoredFormatter(logging.Formatter):
            def format(self, record):
                # Format the record normally
                result = super().format(record)
                # Split to separate timestamp from rest
                parts = result.split(' ', 1)
                if len(parts) == 2:
                    # Add orange color to timestamp
                    timestamp = parts[0]
                    rest = parts[1]
                    colored_timestamp = f"{theme.WARNING.ansi_fg()}{timestamp}\033[0m"
                    return f"{colored_timestamp} {rest}"
                return result
        
        self.log_handler = TuiLogHandler(self.debug_panel)
        self.log_handler.setLevel(logging.DEBUG)
        formatter = ColoredFormatter('%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')
        self.log_handler.setFormatter(formatter)
        
        # Configure root logger to accept all levels
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(self.log_handler)
        
        # Test log message
        logging.info("[TUI] Debug panel initialized")
        
        # Track the current generation task
        self.current_generation_task: Optional[asyncio.Task] = None
        
        # Track which message is being edited (for edit-then-submit workflow)
        self.editing_message_index: Optional[int] = None
        
        # Track if we're in a retry (to avoid duplicate user message in UI)
        self.is_retrying: bool = False
        # Track the specific user message being processed (for harness ID assignment)
        self.processing_user_msg: Optional[Message] = None
        
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

    async def _process_generation(self, user_input: str):
        """Process a single generation request."""
        import logging
        logger = logging.getLogger("tui")
        logger.info(f"Starting generation for user input: {user_input[:50]}...")
        
        # Show thinking indicator
        chat = self.chat_history_panel
        current_msg = chat.add_message("Sending request...", msg_type=SysMsg())
        
        mode = "request"
        current_harness_ids = []  # Track harness message IDs for current UI message
        
        # Process streaming response from Harness
        try:
            async for chunk in self.agent.chat(user_input):
                
                if isinstance(chunk, chunks.MessageStart):
                    # New message starting from harness
                    current_harness_ids = [chunk.message_id]
                    logger.debug(f"MessageStart: {chunk.role} with ID {chunk.message_id}")
                    
                    if chunk.role == "user":
                        # Find the specific user message being processed or last one without ID
                        target_msg = self.processing_user_msg if self.processing_user_msg else None
                        if target_msg and not target_msg.harness_message_ids:
                            target_msg.harness_message_ids = [chunk.message_id]
                            logger.debug(f"Updated tracked user message with harness ID {chunk.message_id}")
                            self.processing_user_msg = None
                        else:
                            # Fallback: find last user message without ID
                            for msg in reversed(chat.messages):
                                if isinstance(msg.type, UserMsg) and not msg.harness_message_ids:
                                    msg.harness_message_ids = [chunk.message_id]
                                    logger.debug(f"Updated user message with harness ID {chunk.message_id}")
                                    break
                    
                elif isinstance(chunk, chunks.Thinking): # Special chunk type for "thinking" content
                    
                    if mode == "request":
                        # Start a new message for thinking content
                        new_msg = chat.new_message("", msg_type=ThinkingMsg(), harness_message_ids=current_harness_ids)
                        chat.replace_message(current_msg, new_msg) # Replace the "Sending request..." message with the new thinking message
                        current_msg = new_msg
                        mode = "thinking"
                    
                    current_msg.append(chunk.content)
                
                elif isinstance(chunk, chunks.Content): # Regular content chunk
                    
                    text = chunk.content
                    if mode == "thinking":
                        current_msg.set_title("thoughts") # Update title for thinking content
                        current_msg = chat.add_message("", msg_type=PicoMsg(), harness_message_ids=current_harness_ids) # Create a new message for regular content
                        mode = "answering"
                    
                    # Render regular content
                    current_msg.append(text)
                
                elif isinstance(chunk, chunks.ToolStart):
                    # Show which tool is being called
                    current_msg.append(f"{theme.DEFAULT}🔧 {chunk.name}{theme.reset()} ")
                
                elif isinstance(chunk, chunks.ToolComplete):
                    # Show tool completion (truncate long results)
                    result = chunk.result
                    if len(result) > 100:
                        result = result[:100] + "..."
                    current_msg.append(f"{theme.DEFAULT}✓{theme.reset()}\n")
                
                elif isinstance(chunk, chunks.ToolWaitInput):
                    # Show waiting for user input
                    current_msg.append(f"\n{theme.DEFAULT}[Waiting for input: {chunk.prompt}]{theme.reset()}\n")
                
                elif isinstance(chunk, chunks.ToolError):
                    # Show tool error
                    current_msg.append(f"\n{theme.ERROR}[Error in {chunk.name}: {chunk.error}]{theme.reset()}\n")

                # Ensure we scroll to bottom if needed
                if self.chat_history_panel.auto_scroll:
                    self.chat_history_panel.scroll_offset = 0

                # Yield to let the compositor render the update
                await asyncio.sleep(0)
                
        except asyncio.CancelledError:
            # If cancelled, we want to stop and show that
            current_msg.append(f"\n{theme.MUTED}[Generation stopped]{theme.reset()}")
            # Finalize and re-raise
            raise 
            
        except Exception as e:
            raise e
    
        finally:
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
                    user_input = completed.result()
                    import logging
                    logger = logging.getLogger("tui")
                    logger.debug(f"Agent worker received user input")

                    self.current_generation_task = asyncio.create_task(
                        self._process_generation(user_input)
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

            except asyncio.TimeoutError:
                continue
            
            except Exception as e: # Errors during generation or processing
                import logging
                logger = logging.getLogger("tui")
   
                recoverable_exceptions = [openai.APIConnectionError]
                
                if type(e) in recoverable_exceptions:
                    logger.warning(f"Recoverable error: {type(e).__name__}: {str(e)}")
                    # self.chat_history_panel.remove_last_message()  # Remove the pico message
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

    # Action handlers for focused messages
    
    def handle_copy_action(self, message):
        """Handle copy action for a focused message."""
        import logging
        logger = logging.getLogger("tui")
        
        try:
            # Strip ANSI escape codes for clean clipboard content
            text_to_copy = strip_ansi(message.base_text)
            
            # Try to copy to clipboard using various methods
            
            # Method 1: Try xclip (X11)
            try:
                import subprocess
                subprocess.run(['xclip', '-selection', 'clipboard'], 
                             input=text_to_copy.encode(), 
                             check=True, 
                             stderr=subprocess.DEVNULL)
                logger.info("Message copied to clipboard (xclip)")
                self.chat_history_panel.add_message("Copied to clipboard", msg_type=SysMsg())
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
            
            # Method 2: Try xsel (X11 alternative)
            try:
                import subprocess
                subprocess.run(['xsel', '--clipboard', '--input'], 
                             input=text_to_copy.encode(), 
                             check=True,
                             stderr=subprocess.DEVNULL)
                logger.info("Message copied to clipboard (xsel)")
                self.chat_history_panel.add_message("Copied to clipboard", msg_type=SysMsg())
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
            
            # Method 3: Try wl-copy (Wayland)
            try:
                import subprocess
                subprocess.run(['wl-copy'], 
                             input=text_to_copy.encode(), 
                             check=True,
                             stderr=subprocess.DEVNULL)
                logger.info("Message copied to clipboard (wl-copy)")
                self.chat_history_panel.add_message("Copied to clipboard", msg_type=SysMsg())
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
            
            # If all methods fail
            logger.warning("No clipboard utility found (tried xclip, xsel, wl-copy)")
            self.chat_history_panel.add_message(
                "Could not copy: no clipboard utility found\nInstall xclip, xsel, or wl-copy",
                msg_type=SysMsgError()
            )
            
        except Exception as e:
            logger.error(f"Error copying to clipboard: {e}")
            self.chat_history_panel.add_message(f"Copy failed: {e}", msg_type=SysMsgError())
    
    def handle_edit_action(self, message):
        """Handle edit action for a focused message (user messages only)."""
        import logging
        logger = logging.getLogger("tui")
        logger.info("Edit action triggered")
        
        # Store which message is being edited
        try:
            self.editing_message_index = self.chat_history_panel.messages.index(message)
        except ValueError:
            self.editing_message_index = None
        
        # Populate input field with message content
        self.input_component.update(message.base_text)
        
        # Switch focus to input
        self._last_focus_id = "input"
        self._update_focus_states()
        
        # Clear message focus
        self.chat_history_panel.clear_focus()
    
    def handle_retry_action(self, message):
        """Handle retry action for a message (regenerate response)."""
        import logging
        logger = logging.getLogger("tui")
        logger.info("Retry action triggered")
        
        # Stop any ongoing generation first
        if self.stop_generation():
            logger.info("Stopped ongoing generation for retry")
        
        # Find the previous user message to retry using harness IDs
        try:
            msg_index = self.chat_history_panel.messages.index(message)
            
            # Look backwards for the last user message
            user_msg = None
            user_msg_index = None
            for i in range(msg_index - 1, -1, -1):
                msg = self.chat_history_panel.messages[i]
                if isinstance(msg.type, UserMsg):
                    user_msg = msg
                    user_msg_index = i
                    break
            
            if user_msg and user_msg.harness_message_ids:
                # Use the harness ID to delete from harness history
                user_harness_id = user_msg.harness_message_ids[0]
                
                # Delete user message AND everything after from harness (will be re-added on resubmit)
                if self.agent.delete_messages_after_id(user_harness_id, inclusive=True):
                    logger.info(f"Deleted harness messages after ID {user_harness_id} (inclusive)")
                
                # Remove UI messages AFTER the user message (keep user visible)
                messages_to_remove = len(self.chat_history_panel.messages) - user_msg_index - 1
                for _ in range(messages_to_remove):
                    self.chat_history_panel.remove_last_message()
                
                # Clear the user message's harness ID (will get new one)
                user_msg.harness_message_ids = []
                
                # Set retry flag to prevent duplicate in UI
                self.is_retrying = True
                # Track which message we're processing so ID gets assigned correctly
                self.processing_user_msg = user_msg
                
                # Resubmit the user message
                user_text = user_msg.base_text
                self.chat_history_panel.auto_scroll = True
                self.message_queue.put_nowait(user_text)
                logger.info(f"Retrying with message: {user_text[:50]}...")
            else:
                self.chat_history_panel.add_message(
                    "Could not find user message to retry",
                    msg_type=SysMsgError()
                )
        except ValueError:
            logger.error("Message not found in history")
    
    def handle_stop_action(self, message):
        """Handle stop action for ongoing generation."""
        import logging
        logger = logging.getLogger("tui")
        logger.info("Stop action triggered")
        
        if self.stop_generation():
            logger.info("Generation stopped by user")
            # The cancellation will be handled in _process_generation
        else:
            logger.info("No active generation to stop")
    
    def handle_allow_action(self, message):
        """Handle allow action for tool permission requests."""
        import logging
        logger = logging.getLogger("tui")
        logger.info("Allow action triggered")
        
        # TODO: Implement tool permission system
        self.chat_history_panel.add_message(
            "Tool permission system not yet implemented",
            msg_type=SysMsg()
        )
    
    def handle_deny_action(self, message):
        """Handle deny action for tool permission requests."""
        import logging
        logger = logging.getLogger("tui")
        logger.info("Deny action triggered")
        
        # TODO: Implement tool permission system
        self.chat_history_panel.add_message(
            "Tool permission system not yet implemented",
            msg_type=SysMsg()
        )


    def on_command_submit(self, text: str):
        """Handle execution of commands."""
        import logging
        logger = logging.getLogger("tui")
        logger.info(f"Command submitted: {text}")
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


    def on_user_submit(self, text: str):
        """Handle user input submission."""
        clean_text = text.strip()
        if not clean_text:
            return  # Ignore empty or whitespace-only input
            
        if clean_text.startswith('/'):
            self.on_command_submit(clean_text)
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
                
                # Set flag to prevent duplicate user message
                self.is_retrying = True
                # Track which message we're processing
                self.processing_user_msg = edited_msg
                
                # Clear editing state
                self.editing_message_index = None
                
                # Fall through to add the edited message and resubmit
            else:
                logger.info(f"User submitted: {text[:50]}...")
            
            # Enable auto-scroll to show the new message
            self.chat_history_panel.auto_scroll = True
            
            # Add user message to UI (skip if retrying - already exists)
            if not self.is_retrying:
                # Track the new message for harness ID assignment
                new_msg = self.chat_history_panel.add_message(text, msg_type=UserMsg())
                self.processing_user_msg = new_msg
            else:
                self.is_retrying = False
            
            # Add to processing queue for agent
            self.message_queue.put_nowait(text)

    def _update_focus_states(self):
        """Update focus states of components based on _last_focus_id."""
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
        
        # Handle keyboard navigation between input and history
        if isinstance(event, str):
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
        
        # Set initial focus states
        self._update_focus_states()
        
        # Start background server status check (non-blocking)
        async def background_startup_check():
            status = await self.agent.get_status()

            
            self.chat_history_panel.add_message(
                StatusCommand.format_status(status),
                msg_type=SysMsg(),
                title="status"
            )
            logger.info(f"Server status online: {status['online']}")
            

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
