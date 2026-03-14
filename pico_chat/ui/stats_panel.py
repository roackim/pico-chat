"""Stats panel for the Open-Clank TUI."""

import asyncio
import datetime
from typing import Optional

from pico_chat.ui.tui.component import TextComponent, Box


STATS_TEMPLATE = """
 {model}
 State: {state}
 Session: {session}
 Tools: {tools}
 Time: {time}
"""


class StatsPanel:
    """Manages the stats display panel."""

    def __init__(self, agent):
        """Initialize the stats panel.
        
        Args:
            agent: The agent instance to get stats from
        """
        self.agent = agent
        self.component = TextComponent("", id="stats", fg=(0, 255, 255))
        self.box = Box(self.component, title="Stats")
        self.compositor: Optional[object] = None

    def set_compositor(self, compositor):
        """Set the compositor for updates."""
        self.compositor = compositor
    
    def get_state(self) -> str:
        """Get current agent state."""
        if hasattr(self.agent, "get_state"):
            state = self.agent.get_state()
            # Handle both enum and potential string fallback
            state_str = state.name if hasattr(state, "name") else str(state)
            
            # Simple color coding for state
            if state_str == "UNCONNECTED":
                return f"\033[31m{state_str}\033[0m"  # Red
            elif state_str == "IDLE":
                return f"\033[32m{state_str}\033[0m"  # Green
            elif state_str == "THINKING":
                return f"\033[33m{state_str}\033[0m"  # Yellow
            elif state_str == "ANSWERING":
                return f"\033[34m{state_str}\033[0m"  # Blue
            return state_str
        return "Unknown"

    def get_model_info(self) -> str:
        """Get model info from config."""
        if hasattr(self.agent, "config"):
            model = self.agent.config.model
        else:
            return "Unknown"
            
        # Shorten model name if too long
        if len(model) > 25:
            model = model[:22] + "..."
        return model

    def get_enabled_tools(self) -> str:
        """Get list of enabled tools."""
        if not hasattr(self.agent, "config"):
            return "Unknown"
            
        tools = [name for name, enabled in self.agent.config.enabled_tools.items() if enabled]
        if len(tools) > 5:
            return ", ".join(tools[:5]) + "..."
        return ", ".join(tools) if tools else "None"

    async def update_loop(self):
        """Update stats panel periodically."""
        while self.compositor and hasattr(self.compositor, 'running') and self.compositor.running:
            now = datetime.datetime.now().strftime("%H:%M:%S")
            stats_text = STATS_TEMPLATE.format(
                model=self.get_model_info(),
                state=self.get_state(),
                session="default",
                tools=self.get_enabled_tools(),
                time=now
            )
            self.compositor.update_component("stats", stats_text)
            await asyncio.sleep(0.25)

    def get_component(self):
        """Get the box component for layout."""
        return self.box
