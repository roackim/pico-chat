"""Argument completion shares the selector look and shows descriptions."""

from pico_chat.ui.commands.base import Command, Param
from pico_chat.ui.tui.colors import theme
from pico_chat.ui.tui.components.input.completion import ArgumentCompletion
from pico_chat.ui.tui.components.menu import SelectionMenu


def _registry():
    return {
        "demo": Command("demo", "d", params=[
            Param("A", completions=["one", "two"], descriptions={"one": "first"}),
        ]),
    }


def test_argument_menu_matches_the_shared_selector_style():
    comp = ArgumentCompletion(SelectionMenu(), _registry())

    assert comp.menu.fill_width is True
    assert comp.menu.frame_color == theme.USER
    assert comp.menu.content_color == theme.DEFAULT


def test_argument_completion_passes_descriptions():
    comp = ArgumentCompletion(SelectionMenu(), _registry())

    comp.update("/demo ", len("/demo "))

    assert comp.is_active
    assert comp.menu.item_descriptions.get("one") == "first"


def test_config_role_completion_uses_role_descriptions(monkeypatch):
    import pico_chat.ui.commands.core as core

    monkeypatch.setattr(core, "role_name_completions", lambda: ["agent", "chat"])
    monkeypatch.setattr(core, "role_descriptions", lambda: {"agent": "General agent"})

    cmd = core.ConfigCommand()

    assert cmd.get_completions(1, ("role",)) == ["agent", "chat"]
    assert cmd.get_descriptions(1, ("role",)) == {"agent": "General agent"}
    assert cmd.get_descriptions(1, ("ui",)) == {}
