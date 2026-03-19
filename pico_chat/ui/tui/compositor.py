import sys
import time
import asyncio
from typing import Optional, Dict, Any
from pico_chat.ui.tui.terminal import ANSI, Terminal, MouseEvent
from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.components import Component

class Compositor:
    def __init__(self, root: Component, fps: int = 30, shutdown_event: Optional[Any] = None):
        self.root = root
        self.fps = fps
        self.terminal = Terminal()
        self.width, self.height = 0, 0
        self.buffer = Buffer(0, 0)
        self.components_by_id: Dict[str, Component] = {}
        self._collect_ids(self.root)
        self.running = False
        self.shutdown_event = shutdown_event

    def _collect_ids(self, component: Component):
        if component.id:
            self.components_by_id[component.id] = component
        # If it's a container, we'll need to recurse. 
        # For now, let's assume components might have children.
        if hasattr(component, 'children'):
            for child in component.children:
                self._collect_ids(child)

    def get_component(self, id: str) -> Optional[Component]:
        return self.components_by_id.get(id)

    def update_component(self, id: str, data: Any):
        comp = self.get_component(id)
        if comp:
            comp.update(data)

    async def run(self):
        self.running = True
        with self.terminal:
            self._update_size()
            
            last_render = 0
            frame_time = 1.0 / self.fps

            while self.running:
                now = time.time()
                
                if self.terminal.resized:
                    # Debounce resize events
                    await asyncio.sleep(0.05)
                    self.terminal.resized = False
                    self._update_size()
                    self.render(force_full=True)
                    last_render = now

                # Handle input
                event = self.terminal.get_input()
                if event:
                    if event == '\x03': # Ctrl-C
                        self.running = False
                        if self.shutdown_event:
                            self.shutdown_event.set()
                        break
                    self.root.handle_input(event)
                    # Force immediate render on input
                    self.render()
                    last_render = now
                
                if now - last_render >= frame_time:
                    self.render()
                    last_render = now
                
                await asyncio.sleep(0.001) # Yield to other tasks

    def _update_size(self):
        w, h = self.terminal.get_size()
        self.width, self.height = w, h
        self.buffer = Buffer(w, h)

    def render(self, force_full=False):
        if self.width == 0 or self.height == 0:
            return

        self.buffer.clear()
        self.root.set_layout(0, 0, self.width, self.height)
        self.root.render(self.buffer)
        
        # Use Buffer's built-in render method
        output = self.buffer.render()
        sys.stdout.write(output)
        sys.stdout.flush()
