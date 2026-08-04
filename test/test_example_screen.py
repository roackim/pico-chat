from pico_chat.ui.tui.buffer import Buffer
from pico_chat.ui.tui.example_screen import ExampleScreen
from pico_chat.ui.tui.actions import Action, Actions


def test_example_screen_uses_library_primitives_and_action_map():
    activated = []
    screen = ExampleScreen(lambda: activated.append(True))
    screen.root.set_layout(0, 0, 30, 6)
    screen.root.layout()
    screen.focus_scope.enter()
    screen.root.render(Buffer(30, 6))

    assert screen.action_map.dispatch(Action(Actions.ACTIVATE, "activate"))
    assert activated == [True]