"""Shared command contracts and completion helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Union

from pico_chat import pico_cfg


CompletionSource = Union[List[str], Callable[[], List[str]]]


@dataclass
class Param:
    """Defines a command parameter for hints and autocomplete."""

    name: str
    completions: Optional[CompletionSource] = None
    path: bool = False
    required: bool = False


class ChatUIProtocol(Protocol):
    agent: Any
    chat_history_panel: Any
    input_panel: Any
    compositor: Any

    def show_popup(self, title: str, content: str, content_padding: int = 1) -> None: ...
    def hide_popup(self) -> None: ...
    def show_form_popup(self, title: str, fields: list, on_submit,
                        on_cancel=None, on_new_profile=None,
                        field_spacing=1) -> None: ...
    def show_confirmation(self, title: str, on_confirm,
                          on_cancel=None) -> None: ...


class Command:
    def __init__(self, name: str, description: str,
                 subcommands: Optional[Dict[str, "Command"]] = None,
                 params: Optional[List[Param]] = None):
        self.name = name
        self.description = description
        self.subcommands = subcommands or {}
        self.params = params or []

    async def execute(self, ui: ChatUIProtocol, args: List[str]):
        raise NotImplementedError

    def has_subcommands(self) -> bool:
        return bool(self.subcommands)

    def resolve_command(self, parts: List[str]) -> tuple["Command", int]:
        cmd = self
        offset = 0
        while cmd.has_subcommands() and offset < len(parts):
            sub_name = parts[offset]
            if sub_name not in cmd.subcommands:
                break
            cmd = cmd.subcommands[sub_name]
            offset += 1
        return cmd, offset

    def get_completions(self, arg_index: int) -> List[str]:
        if self.has_subcommands():
            return sorted(self.subcommands.keys()) if arg_index == 0 else []
        if arg_index < 0 or arg_index >= len(self.params):
            return []
        parameter = self.params[arg_index]
        if parameter.path:
            return self._scan_dirs(parameter.completions)
        if parameter.completions is None:
            return []
        return (parameter.completions() if callable(parameter.completions)
                else list(parameter.completions))

    @staticmethod
    def _scan_dirs(workspace: Any = None) -> List[str]:
        base = workspace() if callable(workspace) else workspace
        try:
            entries = []
            with os.scandir(base or ".") as directory:
                for entry in sorted(directory, key=lambda item: item.name.lower()):
                    if entry.name.startswith("."):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=True):
                            entries.append(entry.name + "/")
                    except OSError:
                        pass
            return entries
        except OSError:
            return []


def server_name_completions() -> List[str]:
    """Return current server names from config."""
    return list(pico_cfg.config.servers.keys())
