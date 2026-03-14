# TODO REMOVE FILE


import asyncio
import random
import datetime
from pico_chat.ui.tui.compositor import Compositor
from pico_chat.ui.tui.container import Vsplit, Hsplit
from pico_chat.ui.tui.component import TextComponent, Box
from pico_chat.ui.portraits.portrait import Portrait



TARGET_FPS = 30

STATS_TEMPLATE = """
 GLM 4.7 flash Q8
 HP: 100/100
 MP: 50/50
 Gold: 1337
 Time: {time}
"""

CHAT_HISTORY = """
[System]: Welcome to the chat!
[User]: Hello world!
[Bot]: Hi there! How can I help you today?
[User]: I'm testing this cool TUI library.
[Bot]: It looks very efficient!
"""

async def main():
    # Left Column
    portrait = TextComponent("", id="portrait", fg=(255, 255, 0))
    stats = TextComponent(STATS_TEMPLATE.format(time="--:--:--"), id="stats", fg=(0, 255, 255))
    
    # Hsplit/Vsplit sizes:
    # - float (e.g., 0.4) = percentage of total space
    # - int (e.g., 10) = fixed number of characters
    # - str (e.g., "60%", "10c") = percentage or fixed characters
    left_col = Hsplit([
        Box(portrait, title="Clank"),
        Box(stats, title="Stats")
    ], ["9c", "100%"])

    # Right Column
    history = TextComponent(CHAT_HISTORY, id="history")
    entry = TextComponent("> Type here...", id="entry", fg=(150, 150, 150))
    right_col = Hsplit([
        Box(history, title="Chat History"),
        Box(entry, title="Input")
    ], ["100%", "5c"])

    Portrait.set_current_portrait("clank_term_text")

    # Main Layout
    root = Vsplit([left_col, right_col], ["20c", "100%"])
    compositor = Compositor(root, fps=TARGET_FPS)

    # Async task to simulate chat updates
    async def chat_simulator():
        messages = [
            "[Bot]: Did you know this uses double buffering?",
            "[Bot]: It only updates changed cells!",
            "[Bot]: Very smooth resize handling too.",
            "[System]: New user joined: Roo"
        ]
        current_history = CHAT_HISTORY
        while compositor.running:
            await asyncio.sleep(random.randint(3, 7))
            if not compositor.running:
                break
            new_msg = random.choice(messages)
            current_history += new_msg + "\n"
            # Keep only last 10 lines
            lines = current_history.strip().splitlines()
            current_history = "\n".join(lines[-15:]) + "\n"
            compositor.update_component("history", current_history)

    async def stat_updater():
        while compositor.running:
            now = datetime.datetime.now().strftime("%H:%M:%S")
            compositor.update_component("stats", STATS_TEMPLATE.format(time=now))
            await asyncio.sleep(1) # Update at 1Hz cause it's just a clock with seconds precision

    async def portrait_updater():
        portrait = Portrait.get_current_portrait()
        while compositor.running:
            image = portrait.get_current_frame()
            compositor.update_component("portrait", image)
            await asyncio.sleep(1 / portrait.fps) 

    # Run both, and cancel the simulator when the compositor finishes
    done, pending = await asyncio.wait(
        [
            asyncio.create_task(compositor.run()),
            asyncio.create_task(chat_simulator()),
            asyncio.create_task(stat_updater()),
            asyncio.create_task(portrait_updater()),
        ],
        return_when=asyncio.FIRST_COMPLETED
    )
    
    for task in pending:
        task.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
