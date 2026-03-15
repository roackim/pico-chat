"""Pico-Chat TUI Application."""

import asyncio
from typing import Optional

from pico_chat.ui.tui.compositor import Compositor
from pico_chat.ui.tui.container import Vsplit, Hsplit
from pico_chat.ui.portrait_panel import PortraitPanel
from pico_chat.ui.stats_panel import StatsPanel
from pico_chat.ui.input_panel import InputPanel
from pico_chat.ui.chat_history_panel import ChatHistoryPanel


TARGET_FPS = 30


class chatTUI:
    """Terminal UI for the agent."""

    def __init__(self, agent):
        self.agent = agent
        self.message_queue = asyncio.Queue()
        self.compositor: Optional[Compositor] = None
        
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
                self.chat_history_panel.add_pico_message("", self.assistant_color)
                
                # Process streaming response from Harness
                full_response = ""
                try:
                    async for chunk in self.agent.chat(user_input):
                        self.chat_history_panel.add_message(chunk, append=True)
                        full_response += chunk
                        # Yield to let the compositor render the update
                        await asyncio.sleep(0)
                except Exception as e:
                     self.chat_history_panel.add_message(f"\n\033[31m[Error]: {str(e)}\033[0m", append=True)
                
                # Finalize the message to render markdown now that streaming is complete
                self.chat_history_panel.finalize_last_message()
                
                # Ensure we end with a newline after the agent finishes
                # check message objects directly instead of hitting deprecated get_history
                messages = self.chat_history_panel.get_messages()
                if messages and not messages[-1].base_text.endswith("\n"):
                    self.chat_history_panel.add_message("\n", append=True)
                
                # Notify completion if needed (e.g. state update, captured via poller anyway)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.chat_history_panel.add_message(
                    f"\n\033[31m[Error]:\033[0m {str(e)}"
                )


    def on_user_submit(self, text: str):
        """Handle user input submission."""
        if text.strip().lower() in ["exit", "quit", "q"]:
            if self.compositor:
                self.compositor.running = False
        else:
            # Add user message immediately with color and header
            self.chat_history_panel.add_user_message(text, self.user_color)
            # Add to processing queue for agent
            self.message_queue.put_nowait(text)

    async def run(self):
        """Run the TUI application."""
        # Start the harness services if available
        if hasattr(self.agent, 'start'):
            self.agent.start()
            
        # Set up panels
        self.portrait_panel.set_portrait("clank_term_text")
        self.input_panel.set_on_submit(self.on_user_submit)
        
        # # Left Column
        # left_col = Hsplit([
        #     self.portrait_panel.get_component(),
        #     self.stats_panel.get_component()
        # ], ["9c", "100%"])

        # Right Column
        right_col = Hsplit([
            self.chat_history_panel.get_component(),
            self.input_panel.get_component()
        ], ["100%", 0]) # Change 3c to 0 (auto-calculate height)

        # Main Layout
        # root = Vsplit([left_col, right_col], ["20c", "100%"])
        root = right_col # For Phase 1, we focus on the chat and input panels only.
        self.compositor = Compositor(root, fps=TARGET_FPS)
        
        # Set compositor for all panels
        self.portrait_panel.set_compositor(self.compositor)
        self.stats_panel.set_compositor(self.compositor)
        self.chat_history_panel.set_compositor(self.compositor)

        # Run all tasks
        try:
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
