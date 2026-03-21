import datetime
import json
import logging
from pathlib import Path
from typing import Any

from pico_chat import pico_cfg


class DebugStream:
    """The Observability Layer (Debug Stream)."""

    def __init__(self):
        self.config = pico_cfg.config
        self.log_path = Path("debug_stream.log")
        # Keep file open for performance
        self._file = open(self.log_path, "a", encoding="utf-8", buffering=1) # Line buffering
        # Also get Python logger for TUI integration
        self._logger = logging.getLogger("harness")

    def log(self, direction: str, payload: str | dict[str, Any] | list[Any]):
        """Log payload to the debug stream file and Python logging."""
        timestamp = datetime.datetime.now().isoformat()
        
        if isinstance(payload, (dict, list)):
            try:
                payload_str = json.dumps(payload, ensure_ascii=False)
            except TypeError:
                payload_str = str(payload)
        else:
            payload_str = str(payload)
            
        entry = f"[{timestamp}] [{direction}] {payload_str}\n"
        
        # Write to the open file handle
        try:
            self._file.write(entry)
            # Flushing is handled by buffering=1 (line buffering) roughly, 
            # or explicit self._file.flush() if we want immediate disk sync (slower).
            # For "The Wire" debugging, immediate flush isn't critical strictly per token
            # if we get crashes, but beneficial.
            # Let's trust the OS buffering unless debugging.
        except Exception:
            pass # Don't crash on logging error
        
        # Also send to Python logging for TUI debug panel
        try:
            # Format as: [DIRECTION] payload
            log_message = f"[{direction}] {payload_str}"
            self._logger.debug(log_message)
        except Exception:
            pass  # Don't crash on logging error

    def __del__(self):
        """Cleanup file handle on destruction."""
        try:
            if hasattr(self, '_file') and self._file:
                self._file.close()
        except:
            pass



_debug_stream: DebugStream | None = None


def get_debug_stream() -> DebugStream:
    """Get global debug stream instance."""
    global _debug_stream
    if _debug_stream is None:
        _debug_stream = DebugStream()
    return _debug_stream
