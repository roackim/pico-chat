from pathlib import Path
from time import time

from . import res_clank_term_scroll

class Portrait:
    
    portraits = {}
    portrait = None
    
    def set_current_portrait(name: str):
        Portrait.portrait = Portrait.get_portrait(name)
    
    def get_current_portrait():
        return Portrait.portrait
    
    def get_portrait(name: str):
        return Portrait.portraits.get(name)
    
    def __init__(self, name: str, frames: list[str], fps: int = 10):
        self.name = name
        self.frames = frames
        self.fps = fps
        self.current_frame = 0
        self.last_update = None
        
        Portrait.portraits[name] = self  # Register this animation in the class-level dictionary
    
    def update(self):
        
        if len(self.frames) <= 1:
            return
        
        now = time()
        if self.last_update is None:
            self.last_update = now
            return
        
        if now - self.last_update >= 1.0 / self.fps:
            self.current_frame = (self.current_frame + 1) % len(self.frames)
            self.last_update = now
    
    def get_frame(self) -> str:
        return self.frames[self.current_frame]
    
    def get_current_frame(self) -> str:
        self.update()
        return self.get_frame()

clank_term_scroll = Portrait("clank_term_text", fps=15, frames=res_clank_term_scroll.frames)