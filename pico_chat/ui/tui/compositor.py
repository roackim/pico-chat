import sys
import time
import asyncio
from typing import Optional, Dict, Any
from collections import deque
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
        self.padding = 0  # Global app padding
        self.overlays = []  # Floating components rendered on top
        
        # Performance tracking - use rolling window for accurate current FPS
        self.render_times = deque(maxlen=10)  # Track last 10 render times for recent FPS
        self.last_render_time = 0  # Track when we last actually rendered for FPS limiting

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
    
    def add_overlay(self, component: Component):
        """Register a component as a floating overlay.
        
        Overlays are rendered on top of the main component tree and are not
        clipped by parent bounds. Useful for menus, modals, tooltips, etc.
        """
        if component not in self.overlays:
            self.overlays.append(component)
    
    def remove_overlay(self, component: Component):
        """Unregister a component from overlays."""
        if component in self.overlays:
            self.overlays.remove(component)

    async def run(self):
        self.running = True
        with self.terminal:
            self._update_size()

            while self.running:
                if self.terminal.resized:
                    # Debounce resize events
                    await asyncio.sleep(0.05)
                    self.terminal.resized = False
                    self._update_size()
                    self.render(force_full=True)

                # Handle input
                event = self.terminal.get_input()
                if event:
                    if event == '\x03': # Ctrl-C
                        self.running = False
                        if self.shutdown_event:
                            self.shutdown_event.set()
                        break
                    self.root.handle_input(event)
                
                # Try to render (will be throttled by FPS limit in render() method)
                self.render()
                
                # Sleep for a short time to yield control and reduce CPU usage
                # Cap at 5ms for input responsiveness, but scale with FPS
                frame_time = 1.0 / self.fps
                sleep_time = min(0.005, frame_time / 2)
                await asyncio.sleep(sleep_time)

    def _update_size(self):
        w, h = self.terminal.get_size()
        self.width, self.height = w, h
        self.buffer = Buffer(w, h)

    def render(self, force_full=False):
        if self.width == 0 or self.height == 0:
            return
        
        # Enforce FPS limit (unless force_full is True)
        now = time.time()
        if not force_full:
            frame_time = 1.0 / self.fps
            time_since_last_render = now - self.last_render_time
            
            if time_since_last_render < frame_time:
                # Too soon, skip this render
                return
            
            self.last_render_time = now
        
        # Track this render time for FPS calculation
        self.render_times.append(now)

        self.buffer.clear()
        # Apply global padding to root component layout
        pad = self.padding
        inner_width = max(0, self.width - 2 * pad)
        inner_height = max(0, self.height - 2 * pad)
        self.root.set_layout(pad, pad, inner_width, inner_height)
        self.root.render(self.buffer)
        
        # Render overlays on top (not clipped by parents)
        for overlay in self.overlays:
            overlay.render(self.buffer)
        
        # Use Buffer's built-in render method
        output = self.buffer.render()
        sys.stdout.write(output)
        sys.stdout.flush()
    
    def get_actual_fps(self) -> float:
        """Calculate actual measured FPS based on recent render times."""
        if len(self.render_times) < 2:
            return 0.0
        
        # Calculate FPS from time difference between first and last render in window
        time_span = self.render_times[-1] - self.render_times[0]
        if time_span == 0:
            return 0.0
        
        # Number of frames in the time span (frames - 1 intervals)
        frame_count = len(self.render_times) - 1
        return frame_count / time_span
