"""Crash-resilient conversation autosave and resume.

The conversation's source of truth is ``Harness.history`` — the same JSON the
``/conversation export`` command writes.  This module persists that history to a
hidden file in the agent's workspace after every user message and after every
completed generation.  On the next launch the file can be loaded back through
the exact ``/conversation import`` path, so a crash mid-conversation leaves only
the in-flight response lost.

The autosave file lives at ``<workspace>/.pico_convo`` (or
``<workspace>/.pico_convo.<suffix>`` when :ref:`conversation_autosave_suffix`
is set).  ``.gitignore`` already ignores ``.pico_*`` project-wide so the
snapshot never pollutes the repository.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from pico_chat import pico_cfg

logger = logging.getLogger("pico-chat.autosave")

#: Envelope version. Bump only on a breaking format change.
CONVERSATION_FORMAT_VERSION = 1


def _autosave_suffix() -> str:
    """Return the configured autosave file suffix, without the leading dot.

    Example: ``.pico_convo.mi`` for ``mi``.
    """
    value = getattr(pico_cfg.config, "conversation_autosave_suffix", "") or ""
    return value.strip().lstrip(".")


def autosave_path(workspace: str | None = None) -> str:
    """Resolve where this conversation gets autosaved.

    Uses the running agent's workspace when provided, otherwise the current
    working directory.
    """
    base = workspace or os.getcwd()
    suffix = _autosave_suffix()
    stem = ".pico_convo"
    if suffix:
        stem = f".pico_convo.{suffix}"
    return os.path.join(base, stem)


def _history_is_autosavable(history: Any) -> bool:
    """Return True when the harness history is in the importable format.

    Only a non-empty list of dicts with a ``role`` key can be restored by the
    import command; anything else is ignored so we never clobber a good
    snapshot with garbage.
    """
    if not isinstance(history, list) or not history:
        return False
    return all(isinstance(msg, dict) and isinstance(msg.get("role"), str)
               for msg in history)


def build_autosave_envelope(
    history: List[Dict[str, Any]],
    role: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the JSON envelope stored by the autosave snapshot."""
    return {
        "version": CONVERSATION_FORMAT_VERSION,
        "role": role or "default",
        "workspace": workspace or os.getcwd(),
        "history": history,
    }


def save_conversation_to_disk(
    history: List[Dict[str, Any]],
    role: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Optional[str]:
    """Atomically persist a conversation snapshot.

    Writes to ``<autosave_path>.tmp`` then renames over the real file so a
    crash mid-write never leaves a truncated conversation file.

    Returns the path that was written, or None when autosave is disabled or
    the history is not in a saveable shape.
    """
    if not pico_cfg.config.conversation_autosave:
        return None

    if not _history_is_autosavable(history):
        return None

    path = autosave_path(workspace)
    envelope = build_autosave_envelope(history, role=role, workspace=workspace)

    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        logger.warning("Autosave to %s failed", path, exc_info=True)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return None

    logger.debug("Autosaved conversation to %s (%d messages)",
                 path, len(history))
    return path


def resume_conversation_from_disk(workspace: str | None = None) -> Optional[str]:
    """Return the autosaved snapshot path when one exists for the workspace.

    Returns None when autosave is disabled or no snapshot is present.  The
    caller decides whether to load it — this helper only answers "is there
    something to resume?".
    """
    if not pico_cfg.config.conversation_autosave:
        return None
    path = autosave_path(workspace)
    return path if os.path.isfile(path) else None