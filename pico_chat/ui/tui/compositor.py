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
        self._render_requested = True
        self._full_redraw = True
        self.idle_sleep_seconds = 0.0
        self._wake_event = asyncio.Event()
        self.streaming_active = False
        
        # Performance tracking - use rolling window for accurate current FPS
        self.render_times = deque(maxlen=10)  # Track last 10 render times for recent FPS

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

    def request_render(self):
        """Request a repaint on the next loop iteration."""
        self._render_requested = True
        self._wake_event.set()

    def set_streaming_active(self, active: bool):
        """Mark whether high-frequency LLM streaming is in progress."""
        self.streaming_active = active
        self.request_render()

    async def run(self):
        self.running = True
        with self.terminal:
            self._update_size()

            # Track absolute target time for next frame (prevents drift)
            current_fps = self.fps
            frame_time = (1.0 / current_fps) if current_fps > 0 else 0.0
            now = time.perf_counter()
            next_frame_time = now

            while self.running:
                # Pick up runtime FPS changes immediately
                new_fps = self.fps
                if new_fps != current_fps:
                    current_fps = new_fps
                    frame_time = (1.0 / current_fps) if current_fps > 0 else 0.0
                    next_frame_time = time.perf_counter()

                if self.terminal.resized:
                    # Debounce resize events
                    await asyncio.sleep(0.05)
                    self.terminal.resized = False
                    self._update_size()
                    self._full_redraw = True
                    self.request_render()
                    # Reset frame timing after resize
                    next_frame_time = time.perf_counter()

                # Handle input first (non-blocking)
                event = self.terminal.get_input()
                if event:
                    if event == '\x03': # Ctrl-C
                        self.running = False
                        if self.shutdown_event:
                            self.shutdown_event.set()
                        break
                    self.root.handle_input(event)
                    self.request_render()

                has_dirty = self.root.is_dirty() if hasattr(self.root, 'is_dirty') else True
                should_render = self.streaming_active or self._render_requested or has_dirty

                if not should_render:
                    idle_timeout = (1.0 / current_fps) if current_fps > 0 else (self.idle_sleep_seconds or 0.016)
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=idle_timeout)
                        self._wake_event.clear()
                    except asyncio.TimeoutError:
                        pass
                    continue
                
                # Render once per scheduled frame
                self.render()

                # Uncapped mode (fps <= 0): render as fast as possible while yielding.
                if current_fps <= 0:
                    await asyncio.sleep(0)
                else:
                    # Advance schedule in absolute time (no cumulative drift)
                    next_frame_time += frame_time
                    now = time.perf_counter()
                    sleep_time = next_frame_time - now

                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                    else:
                        # Behind schedule: skip ahead to avoid sustained lag
                        frames_behind = int((-sleep_time) / frame_time) + 1
                        next_frame_time += frames_behind * frame_time
                        # Always yield so other tasks don't starve at very high target FPS
                        await asyncio.sleep(0)

    def _update_size(self):
        w, h = self.terminal.get_size()
        self.width, self.height = w, h
        self.buffer = Buffer(w, h)

    def render(self):
        """Render the compositor."""
        if self.width == 0 or self.height == 0:
            return

        now = time.perf_counter()

        # Track this render time for FPS calculation
        self.render_times.append(now)

        # Apply global padding to root component layout
        pad = self.padding
        inner_width = max(0, self.width - 2 * pad)
        inner_height = max(0, self.height - 2 * pad)
        self.root.set_layout(pad, pad, inner_width, inner_height)

        if self._full_redraw:
            self.buffer.clear()
            self.root.render(self.buffer)
            for overlay in self.overlays:
                overlay.render(self.buffer)
        else:
            dirty_rects: list[tuple[int, int, int, int]] = []
            if hasattr(self.root, 'collect_dirty_rects'):
                self.root.collect_dirty_rects(dirty_rects)

            valid_dirty_rects = [
                (x, y, width, height)
                for x, y, width, height in dirty_rects
                if width > 0 and height > 0
            ]

            # If a repaint was explicitly requested but no valid dirty rects exist
            # (e.g. before first stable layout), fall back to a full redraw.
            if self._render_requested and not valid_dirty_rects:
                self.buffer.clear()
                self.root.render(self.buffer)
                for overlay in self.overlays:
                    overlay.render(self.buffer)
            elif not valid_dirty_rects:
                self._render_requested = False
                return
            else:
                for x, y, width, height in valid_dirty_rects:
                    self.buffer.clear_rect(x, y, width, height)
                    self.buffer.set_clip(x, y, width, height)
                    self.root.render(self.buffer)
                    for overlay in self.overlays:
                        overlay.render(self.buffer)
                    self.buffer.clear_clip()
        
        # Use Buffer's built-in render method
        output = self.buffer.render()
        sys.stdout.write(output)
        sys.stdout.flush()

        self._render_requested = False
        self._full_redraw = False
        if hasattr(self.root, 'clear_dirty'):
            self.root.clear_dirty()
    
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
