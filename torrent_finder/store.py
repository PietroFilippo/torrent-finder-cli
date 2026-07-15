"""Single owner of filter_state.json: location, migration, cache, and flush.

Every module that persists something (state.py's engine toggles / settings /
history, stats.py's counters) goes through the ``read`` / ``write`` / ``flush``
trio here and never touches the file, the cache, or the dirty flag directly.

Lifecycle: the first ``read()`` consolidates legacy state copies when needed,
loads the machine-stable file, and registers an atexit flush.
``write()`` only updates the cache and marks it dirty — no disk hit. ``flush()``
persists if dirty; it runs at process exit and is called explicitly from
destructive UI sites (save_state, clear_history, reset_stats) so an explicit
user action survives a hard kill.
"""

import atexit
import json
import os

from torrent_finder.constants import legacy_data_paths, machine_state_path

STATE_PATH = machine_state_path("filter_state.json")
LEGACY_STATE_PATHS = legacy_data_paths("filter_state.json")

_cache: dict | None = None
_dirty: bool = False
_atexit_registered: bool = False


def _read_json(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _history_identity(entry: dict) -> tuple:
    if entry.get("kind", "keyword") == "creator":
        return (
            "creator",
            entry.get("provider", ""),
            entry.get("facet", ""),
            (entry.get("name", "") or "").lower(),
        )
    return (
        "keyword",
        entry.get("provider", ""),
        (entry.get("query", "") or "").lower(),
    )


def _merge_history(copies: list[tuple[float, dict]]) -> list[dict]:
    indexed = []
    for _, data in copies:
        for entry in data.get("history", []):
            if isinstance(entry, dict):
                indexed.append((len(indexed), entry))

    indexed.sort(
        key=lambda pair: (str(pair[1].get("timestamp", "")), pair[0]),
        reverse=True,
    )
    merged = []
    seen = set()
    for _, entry in indexed:
        identity = _history_identity(entry)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(entry)
    return merged[:50]


def _merge_stat_value(current, incoming, key: str):
    if (
        key == "first_use"
        and isinstance(current, str)
        and isinstance(incoming, str)
    ):
        return min(current, incoming)
    if isinstance(current, dict) and isinstance(incoming, dict):
        merged = dict(current)
        for child_key, value in incoming.items():
            if child_key in merged:
                merged[child_key] = _merge_stat_value(
                    merged[child_key], value, child_key
                )
            else:
                merged[child_key] = value
        return merged
    if (
        isinstance(current, (int, float))
        and not isinstance(current, bool)
        and isinstance(incoming, (int, float))
        and not isinstance(incoming, bool)
    ):
        return max(current, incoming)
    return incoming


def _merge_state_copies(copies: list[tuple[float, dict]]) -> dict:
    """Consolidate diverged state without double-counting cumulative stats."""
    ordered = sorted(copies, key=lambda copy: copy[0])
    merged = {}
    has_history = False
    stats = None
    for _, data in ordered:
        merged.update(data)
        if isinstance(data.get("history"), list):
            has_history = True
        candidate_stats = data.get("stats")
        if isinstance(candidate_stats, dict):
            stats = (
                candidate_stats
                if stats is None
                else _merge_stat_value(stats, candidate_stats, "stats")
            )

    if has_history:
        merged["history"] = _merge_history(ordered)
    if stats is not None:
        merged["stats"] = stats
    return merged


def _load_initial_state(target_path: str, legacy_paths: list[str]) -> dict:
    current = _read_json(target_path)
    if current is not None:
        return current

    copies = []
    seen = set()
    for path in legacy_paths:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen or key == os.path.normcase(os.path.abspath(target_path)):
            continue
        seen.add(key)
        data = _read_json(path)
        if data is not None:
            try:
                modified = os.path.getmtime(path)
            except OSError:
                modified = 0.0
            copies.append((modified, data))

    if not copies:
        return {}

    merged = _merge_state_copies(copies)
    try:
        parent = os.path.dirname(target_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
    except OSError:
        pass
    return merged


def _load_from_disk() -> dict:
    return _load_initial_state(STATE_PATH, LEGACY_STATE_PATHS)


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
