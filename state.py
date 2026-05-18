"""Persist engine toggles, active filter presets, history, stats, and misc settings.

Mutations are held in an in-memory cache and flushed to disk at process exit
(atexit) or on explicit ``_flush()`` calls from destructive UI sites
(``save_state``, ``clear_history``, ``reset_stats``). Public ``save_*`` /
``record_*`` helpers no longer hit the disk on every call.
"""

import atexit
import json
import os

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filter_state.json")

_CACHE: dict | None = None
_DIRTY: bool = False
_ATEXIT_REGISTERED: bool = False


def _load_from_disk() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _read_state() -> dict:
    """Return the in-memory state dict, loading from disk on first call."""
    global _CACHE, _ATEXIT_REGISTERED
    if _CACHE is None:
        _CACHE = _load_from_disk()
        if not _ATEXIT_REGISTERED:
            atexit.register(_flush)
            _ATEXIT_REGISTERED = True
    return _CACHE


def _write_state(data: dict) -> None:
    """Update the cache and mark it dirty. No disk hit — see ``_flush()``."""
    global _CACHE, _DIRTY
    _CACHE = data
    _DIRTY = True


def _flush() -> None:
    """Persist the cache to disk if dirty. Called from atexit + destructive sites."""
    global _DIRTY
    if not _DIRTY or _CACHE is None:
        return
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(_CACHE, f, indent=2)
        _DIRTY = False
    except OSError:
        pass


# One-shot rename: legacy persistence keyed on display ``name``; new schema
# keys on immutable ``slug``. Map covers every display name that ever existed
# in this codebase. Idempotent — if keys are already slugs, no rewrites.
_LEGACY_NAME_TO_SLUG = {
    "Movies": "movies",
    "Movies & Series": "movies",
    "Games": "games",
    "Anime": "anime",
}


def _migrate_legacy_names(data: dict) -> bool:
    """Rewrite display-name keys to slugs across providers, history, and stats
    subtrees. Returns True if anything changed (caller should mark dirty)."""
    changed = False

    providers = data.get("providers")
    if isinstance(providers, dict) and any(k in _LEGACY_NAME_TO_SLUG for k in providers):
        renamed = {}
        for k, v in providers.items():
            renamed[_LEGACY_NAME_TO_SLUG.get(k, k)] = v
        data["providers"] = renamed
        changed = True

    history = data.get("history")
    if isinstance(history, list):
        for entry in history:
            prov = entry.get("provider") if isinstance(entry, dict) else None
            if prov in _LEGACY_NAME_TO_SLUG:
                entry["provider"] = _LEGACY_NAME_TO_SLUG[prov]
                changed = True

    stats = data.get("stats")
    if isinstance(stats, dict):
        for subkey in ("searches_by_provider", "torrents_picked_by_provider"):
            sub = stats.get(subkey)
            if not isinstance(sub, dict):
                continue
            if not any(k in _LEGACY_NAME_TO_SLUG for k in sub):
                continue
            merged: dict = {}
            for k, v in sub.items():
                slug = _LEGACY_NAME_TO_SLUG.get(k, k)
                merged[slug] = merged.get(slug, 0) + v
            stats[subkey] = merged
            changed = True

    return changed


def load_state(providers) -> None:
    """Apply saved engine/preset selections onto the given provider instances in place."""
    data = _read_state()
    if _migrate_legacy_names(data):
        _write_state(data)
    provider_states = data.get("providers", {})
    for provider in providers:
        pstate = provider_states.get(provider.slug)
        if not pstate:
            continue

        saved_engines = pstate.get("engines", {})
        for engine in provider.engines:
            if engine.name in saved_engines:
                engine.enabled = bool(saved_engines[engine.name])

        saved_preset_names = pstate.get("active_presets", [])
        provider.active_presets = [
            p for p in provider.presets if p.name in saved_preset_names
        ]


def save_state(providers) -> None:
    """Write current engine/preset selections, preserving other top-level keys.

    Flushes immediately — filter-menu Confirm is an explicit user action and
    should survive a hard kill.
    """
    data = _read_state()
    data["providers"] = {
        p.slug: {
            "engines": {e.name: e.enabled for e in p.engines},
            "active_presets": [pr.name for pr in p.active_presets],
        }
        for p in providers
    }
    _write_state(data)
    _flush()


def load_setting(key: str, default=None):
    """Read a value from the `settings` subtree of the state file."""
    return _read_state().get("settings", {}).get(key, default)


def save_setting(key: str, value) -> None:
    """Write a value into the `settings` subtree of the state file, preserving other keys."""
    data = _read_state()
    data.setdefault("settings", {})[key] = value
    _write_state(data)


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------

_HISTORY_MAX = 50


def load_history() -> list[dict]:
    """Return the saved search history (newest first).

    Each entry is ``{"query": str, "provider": str, "timestamp": str}``.
    """
    return _read_state().get("history", [])


def save_history(entries: list[dict]) -> None:
    """Persist a history list, capping at *_HISTORY_MAX* entries."""
    data = _read_state()
    data["history"] = entries[:_HISTORY_MAX]
    _write_state(data)


def add_history_entry(
    query: str,
    provider_name: str,
    presets: list[str] | None = None,
) -> None:
    """Record a search.  Deduplicates: if the same query+provider already
    exists, the old entry is removed so the new one lands on top.

    *presets* is the list of active preset names at search time, shown in
    the history menu so users can see which filters a past search used.
    """
    from datetime import datetime, timezone

    history = load_history()

    # Remove any previous duplicate (same query text + same provider)
    history = [
        e for e in history
        if not (e.get("query", "").lower() == query.lower()
                and e.get("provider") == provider_name)
    ]

    entry = {
        "query": query,
        "provider": provider_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "presets": list(presets) if presets else [],
    }
    history.insert(0, entry)
    save_history(history)


def clear_history() -> None:
    """Wipe all history entries. Flushes immediately — explicit destructive action."""
    save_history([])
    _flush()
