"""Pico-Chat TUI Application."""

import sys
import asyncio
from typing import Optional, Any

from pico_chat.ui.tui.compositor import Compositor
from pico_chat.ui.tui.terminal import MouseEvent
from pico_chat.ui.tui.container import Vsplit, Hsplit
from pico_chat.ui.portrait_panel import PortraitPanel
from pico_chat.ui.stats_panel import StatsPanel
from pico_chat.ui.input_panel import InputPanel
from pico_chat.ui.chat_history_panel import ChatHistoryPanel


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
        
        # Initialize panels
        self.portrait_panel = PortraitPanel()
        self.stats_panel = StatsPanel(agent) 
        
        self.chat_history_panel = ChatHistoryPanel()
        self.input_panel = InputPanel(self.user_color)
        
    @staticmethod
    def _rgb_to_ansi_fg(r: int, g: int, b: int) -> str:
        """Convert RGB to ANSI foreground color code."""
        return f"\033[38;2;{r};{g};{b}m"

    async def agent_worker(self):
        """Background worker that processes harness requests."""
        while self.compositor and self.compositor.running:
            try:
                # Wait for a message with timeout
                user_input = await asyncio.wait_for(self.message_queue.get(), timeout=0.1)
                
                # Show thinking indicator
                self.chat_history_panel.add_pico_message("Thinking..", self.assistant_color)
                
                # Process streaming response from Harness
                full_response = ""
                is_first_chunk = True
                try:
                    async for chunk in self.agent.chat(user_input):
                        if is_first_chunk:
                            # Replace "Thinking..." with the first real chunk
                            self.chat_history_panel.add_message(chunk, append=False, overwrite_last=True)
                            is_first_chunk = False
                        else:
                            self.chat_history_panel.add_message(chunk, append=True)
                        full_response += chunk
                        # Yield to let the compositor render the update
                        await asyncio.sleep(0)
                except Exception as e:
                     # If we fail before getting any chunk, the "Thinking..." might still be there.
                     # We can append the error.
                     self.chat_history_panel.add_message(f"\n\033[31m[Error]: {str(e)}\033[0m", append=True)
                
                # Finalize the message to render markdown now that streaming is complete
                self.chat_history_panel.finalize_last_message()
                
                # Notify completion if needed (e.g. state update, captured via poller anyway)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.chat_history_panel.add_message(
                    f"\n\033[31m[Error]:\033[0m {str(e)}"
                )


    def on_command_submit(self, text: str):
        """Handle execution of commands."""
        cmd = text.strip().lower()
        if cmd == "/exit":
            if self.compositor:
                self.compositor.running = False
        elif cmd == "/clear":
            # 1. Clear the UI
            self.chat_history_panel.clear()
            # 2. Clear the agent's history if clear_history is available
            if hasattr(self.agent, 'clear_history'):
                self.agent.clear_history()
            # 3. Inform the user in the new cleared history (without adding another welcome)
            self.chat_history_panel.add_system_message("Conversation history cleared.")
            self.chat_history_panel.finalize_last_message()
        elif cmd == "/status":
            # Use a closure or helper to run the async check and update UI
            async def run_status():
                is_online = await self.agent.check_connection()
                status_text = "online" if is_online else "offline"
                color_code = "\x1b[32m" if is_online else "\x1b[31m"
                
                # Context estimation
                cur, max_ctx, perc = self.agent.check_context() if hasattr(self.agent, 'check_context') else self.agent.estimate_context_usage()
                
                # Retrieve model name from config
                model_name = getattr(self.agent.config, 'model', 'unknown')
                
                report = (
                    f"LLM Connectivity : {color_code}{status_text}\x1b[0m\n"
                    f"Active Model     : {model_name}\n"
                    f"Context Pressure : {perc:.1f}% | {cur/1024:.1f}k / {max_ctx/1024:.1f}k"
                )
                self.chat_history_panel.add_system_message(report, title="status")
                self.chat_history_panel.finalize_last_message()
            
            asyncio.create_task(run_status())

        elif cmd == "/help":
            help_text = (
                "\033[1mAvailable commands:\033[0m\n"
                "/help   - Show this help\n"
                "/status - Show system and connection status\n"
                "/exit   - Close the application\n"
                "/clear  - Clear chat history"
            )
            # Add as a system message
            self.chat_history_panel.add_system_message(help_text, title=cmd[1:])
            self.chat_history_panel.finalize_last_message()
        else:
            self.chat_history_panel.add_system_message(f"Unknown command: {cmd}", color=(255, 0, 0))
            self.chat_history_panel.finalize_last_message()

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
        self.portrait_panel.set_portrait("clank_term_text")
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
        self.portrait_panel.set_compositor(self.compositor)
        self.stats_panel.set_compositor(self.compositor)
        self.chat_history_panel.set_compositor(self.compositor)

        # Run all tasks
        try:
            # Override compositor.render to use our render
            self.compositor.render = self.render
            
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(self.compositor.run()),
                    asyncio.create_task(self.agent_worker()),
                    asyncio.create_task(self.stats_panel.update_loop()),
                    asyncio.create_task(self.portrait_panel.update_loop()),
                ],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
        finally:
            # Clean shutdown
            if hasattr(self.agent, 'stop'):
                self.agent.stop()
