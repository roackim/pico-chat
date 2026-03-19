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
from pico_chat.ui.chat_history_panel import ChatHistoryPanel
from pico_chat.ui.commands import handle_command, get_command_list
from pico_chat.ui.tui.container import Vsplit, Hsplit

from pico_chat.ui.tui.colors import theme

from pico_chat import pico_cfg

TARGET_FPS = 60
# TARGET_FPS = pico_cfg.target_fps

class chatTUI:
    """Terminal UI for the agent."""

    def __init__(self, agent):
        self.agent = agent
        self.message_queue = asyncio.Queue()
        self.compositor: Optional[Compositor] = None
        self._last_focus_id: Optional[str] = None
        
        # Get colors from config
        self.chat_history_panel = ChatHistoryPanel()
        
        # New: Direct InputComponent usage
        self.input_component = InputComponent(" ", id="entry", fg=theme.USER)
        self.input_component.on_submit = self.on_user_submit
        
        # Setup menus
        commands = get_command_list()
        get_context = lambda: agent.list_files_and_folders() if hasattr(agent, 'list_files_and_folders') else []
        self.input_component.setup_menus(commands, get_context_items=get_context)
        
        self.input_box = Box(self.input_component, title="message")
        
        # Track the current generation task
        self.current_generation_task: Optional[asyncio.Task] = None
        
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
        # Show thinking indicator
        chat = self.chat_history_panel
        current_msg = chat.add_pico_message("Thinking..", frame_color=theme.PICO)
        
        # Process streaming response from Harness
        try:
            is_first_chunk = True
            async for chunk in self.agent.chat(user_input):
                if is_first_chunk:
                    # Replace "Thinking..." with the first real chunk
                    current_msg.base_text = chunk
                    current_msg.reformat(self.chat_history_panel.max_width - 2)
                    is_first_chunk = False
                else:
                    current_msg.append(chunk)

                # Ensure we scroll to bottom if needed (handled by panel logic ideally, 
                # but we can poke it)
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
                    await handle_command(self, command)  # exceptions propagate → crash
                else:
                    user_input = completed.result()

                    self.current_generation_task = asyncio.create_task(
                        self._process_generation(user_input)
                    )

                    try:
                        await self.current_generation_task
                    except asyncio.CancelledError:
                        pass
                    finally:
                        self.current_generation_task = None

            except asyncio.TimeoutError:
                continue
            
            except Exception as e: # Errors during generation or processing
   
                recoverable_exceptions = [openai.APIConnectionError]
                
                if type(e) in recoverable_exceptions:
                    self.chat_history_panel.remove_last_message()  # Remove the pico message
                    self.chat_history_panel.add_system_message(
                        message=f"Error: {str(e)}",
                        frame_color=theme.ERROR,
                        content_color=theme.ERROR,
                    )
                    
                else: # raise for non-recoverable errors
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
            # Enable auto-scroll to show the new message
            self.chat_history_panel.auto_scroll = True
            # Add user message immediately with color and header
            self.chat_history_panel.add_user_message(text)
            # Add to processing queue for agent
            self.message_queue.put_nowait(text)


    def handle_global_input(self, event: Any) -> bool:
        """Handle focus logging and input dispatch."""
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
                    
                if target_id and target_id != self._last_focus_id:
                    # Log focus change
                    import logging
                    logger = logging.getLogger("harness")
                    logger.info(f"[UI] Focus changed to: {target_id}")
                    self._last_focus_id = target_id
            
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
        # Start the harness services if available
        if hasattr(self.agent, 'start'):
            self.agent.start()
            
        # Column
        column = Hsplit([
            self.chat_history_panel.get_component(),
            self.input_box
        ], ["100%", 0]) # 0 means use preferred height

        # Main Layout
        root = column
        self.root = root  # Store root for global handler
        self.compositor = Compositor(root, fps=TARGET_FPS, shutdown_event=self.shutdown_event)
        
        # Store the original handle_input method before overriding
        self._original_handle_input = root.handle_input
        self.root.handle_input = self.handle_global_input

        # Set compositor for all panels
        self.chat_history_panel.set_compositor(self.compositor)

        # Run all tasks
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self.compositor.run())
                tg.create_task(self.agent_worker())
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
