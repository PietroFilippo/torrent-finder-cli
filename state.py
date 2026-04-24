"""Persist engine toggles, active filter presets, and misc settings across runs."""

import json
import os

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filter_state.json")


def _read_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(data: dict) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def load_state(providers) -> None:
    """Apply saved engine/preset selections onto the given provider instances in place."""
    data = _read_state()
    provider_states = data.get("providers", {})
    for provider in providers:
        pstate = provider_states.get(provider.name)
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
    """Write current engine/preset selections to disk, preserving other top-level keys."""
    data = _read_state()
    data["providers"] = {
        p.name: {
            "engines": {e.name: e.enabled for e in p.engines},
            "active_presets": [pr.name for pr in p.active_presets],
        }
        for p in providers
    }
    _write_state(data)


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
    """Wipe all history entries."""
    save_history([])
