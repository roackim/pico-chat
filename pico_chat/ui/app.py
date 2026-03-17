"""Pico-Chat TUI Application."""

import sys
import asyncio
from typing import Optional, Any

from pico_chat.ui.tui.compositor import Compositor
from pico_chat.ui.tui.terminal import MouseEvent
from pico_chat.ui.tui.container import Vsplit, Hsplit
from pico_chat.ui.input_panel import InputPanel
from pico_chat.ui.chat_history_panel import ChatHistoryPanel
from pico_chat.ui.commands import handle_command


TARGET_FPS = 60


class chatTUI:
    """Terminal UI for the agent."""

    def __init__(self, agent):
        self.agent = agent
        self.message_queue = asyncio.Queue()
        self.compositor: Optional[Compositor] = None
        self._last_focus_id: Optional[str] = None
        
        # Get colors from config
        self.user_color = agent.config.ui_user_color
        self.assistant_color = agent.config.ui_assistant_color
        
        # Create ANSI color codes
        self.user_color_code = self._rgb_to_ansi_fg(*self.user_color)
        self.assistant_color_code = self._rgb_to_ansi_fg(*self.assistant_color)
        self.reset_code = "\033[0m"
        
        self.chat_history_panel = ChatHistoryPanel()
        self.input_panel = InputPanel(agent)
        
        # Track the current generation task
        self.current_generation_task: Optional[asyncio.Task] = None
        
    @staticmethod
    def _rgb_to_ansi_fg(r: int, g: int, b: int) -> str:
        """Convert RGB to ANSI foreground color code."""
        return f"\033[38;2;{r};{g};{b}m"

    async def _process_generation(self, user_input: str):
        """Process a single generation request."""
        # Show thinking indicator
        current_msg = self.chat_history_panel.add_pico_message("Thinking..", self.assistant_color)
        
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
             current_msg.append("\n\033[90m[Generation stopped]\033[0m")
             # Finalize and re-raise
             self.chat_history_panel.finalize_last_message()
             raise 
        except Exception as e:
             # If we fail before getting any chunk, the "Thinking..." might still be there.
             # We can append the error.
             current_msg.append(f"\n\033[31m[Error]: {str(e)}\033[0m")
        
        # Finalize the message to render markdown now that streaming is complete
        self.chat_history_panel.finalize_last_message()

    async def agent_worker(self):
        """Background worker that processes harness requests."""
        while self.compositor and self.compositor.running:
            try:
                # Wait for a message with timeout
                user_input = await asyncio.wait_for(self.message_queue.get(), timeout=0.1)
                
                # Create a task for generation so it can be cancelled
                self.current_generation_task = asyncio.create_task(self._process_generation(user_input))
                
                try:
                    await self.current_generation_task
                except asyncio.CancelledError:
                    # Task was cancelled (by /stop), continue to next message
                    pass
                finally:
                    self.current_generation_task = None
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.chat_history_panel.new_message(
                    f"\n\033[31m[Error]:\033[0m {str(e)}"
                )

    def stop_generation(self):
        """Stop the current generation task if active."""
        if self.current_generation_task and not self.current_generation_task.done():
            self.current_generation_task.cancel()
            return True
        return False


    def on_command_submit(self, text: str):
        """Handle execution of commands."""
        # Use the command module to handle the command
        asyncio.create_task(handle_command(self, text))

    def on_user_submit(self, text: str):
        """Handle user input submission."""
        if text.startswith('/'):
            self.on_command_submit(text)
            return

        if text.strip().lower() in ["exit", "quit", "q"]:
            if self.compositor:
                self.compositor.running = False
        else:
            # Enable auto-scroll to show the new message
            self.chat_history_panel.auto_scroll = True
            # Add user message immediately with color and header
            self.chat_history_panel.add_user_message(text, self.user_color)
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
                i_box = self.input_panel.get_component()
                
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
        
        # 1. Render Floating Panels
        # Input Menu (ensure it's on top of history)
        if hasattr(self, 'input_panel'):
            self.input_panel.render_menu(self.compositor.buffer)
            
        # Use Buffer's built-in render method
        output = self.compositor.buffer.render()
        sys.stdout.write(output)
        sys.stdout.flush()

    async def run(self):
        """Run the TUI application."""
        # Start the harness services if available
        if hasattr(self.agent, 'start'):
            self.agent.start()
            
        # Set up panels
        self.input_panel.set_on_submit(self.on_user_submit)
        
        # Right Column
        right_col = Hsplit([
            self.chat_history_panel.get_component(),
            self.input_panel.get_component()
        ], ["100%", 0])

        # Main Layout
        root = right_col
        self.root = root  # Store root for global handler
        self.compositor = Compositor(root, fps=TARGET_FPS)
        
        # Store the original handle_input method before overriding
        self._original_handle_input = root.handle_input
        self.root.handle_input = self.handle_global_input

        # Set compositor for all panels
        self.chat_history_panel.set_compositor(self.compositor)

        # Run all tasks
        try:
            # Override compositor.render to use our render
            self.compositor.render = self.render
            
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(self.compositor.run()),
                    asyncio.create_task(self.agent_worker()),
                ],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
        finally:
            # Clean shutdown
            if hasattr(self.agent, 'stop'):
                self.agent.stop()
