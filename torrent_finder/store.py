"""Single owner of filter_state.json: in-memory cache, dirty flag, flush.

Every module that persists something (state.py's engine toggles / settings /
history, stats.py's counters) goes through the ``read`` / ``write`` / ``flush``
trio here and never touches the file, the cache, or the dirty flag directly.

Lifecycle: the first ``read()`` loads the file and registers an atexit flush.
``write()`` only updates the cache and marks it dirty — no disk hit. ``flush()``
persists if dirty; it runs at process exit and is called explicitly from
destructive UI sites (save_state, clear_history, reset_stats) so an explicit
user action survives a hard kill.
"""

import atexit
import json
import os

from torrent_finder.constants import data_path

STATE_PATH = data_path("filter_state.json")

_cache: dict | None = None
_dirty: bool = False
_atexit_registered: bool = False


def _load_from_disk() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def read() -> dict:
    """Return the in-memory state dict, loading from disk on first call."""
    global _cache, _atexit_registered
    if _cache is None:
        _cache = _load_from_disk()
        if not _atexit_registered:
            atexit.register(flush)
            _atexit_registered = True
    return _cache


def write(data: dict) -> None:
    """Update the cache and mark it dirty. No disk hit — see ``flush()``."""
    global _cache, _dirty
    _cache = data
    _dirty = True


def flush() -> None:
    """Persist the cache to disk if dirty. Called from atexit + destructive sites."""
    global _dirty
    if not _dirty or _cache is None:
        return
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2)
        _dirty = False
    except OSError:
        pass
