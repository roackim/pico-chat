import asyncio
import random
from pico_chat.ui.tui.compositor import Compositor
from pico_chat.ui.tui.container import Vsplit, Hsplit
from pico_chat.ui.tui.component import TextComponent

async def main():
    # Create a layout
    # Left side: a vertical split with two components
    # Right side: a single component
    
    left_top = TextComponent("Left Top", id="lt", fg=(255, 100, 100))
    left_bottom = TextComponent("Left Bottom", id="lb", fg=(100, 255, 100))
    left_side = Hsplit([left_top, left_bottom], [0.5, 0.5])
    
    right_side = TextComponent("Right Side\nPress Ctrl-C to exit", id="rs", fg=(100, 100, 255))
    
    root = Vsplit([left_side, right_side], [0.3, 0.7])
    
    compositor = Compositor(root, fps=10)
    
    # Async task to update content
    async def updater():
        while True:
            await asyncio.sleep(1)
            val = random.randint(0, 100)
            compositor.update_component("lt", f"Random Value: {val}")
            compositor.update_component("lb", f"Time: {asyncio.get_event_loop().time():.2f}")

    # Run both
    await asyncio.gather(
        compositor.run(),
        updater()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
