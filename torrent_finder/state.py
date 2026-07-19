"""Persist engine modes, active filter presets, history, and misc settings.

Persistence itself (cache / dirty / flush of filter_state.json) is owned by
``store.py``; this module reads and mutates the dict through that interface.
Destructive UI sites (``save_state``, ``clear_history``) flush explicitly so
the action survives a hard kill.
"""

from torrent_finder import store


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
    data = store.read()
    if _migrate_legacy_names(data):
        store.write(data)
    provider_states = data.get("providers", {})
    for provider in providers:
        pstate = provider_states.get(provider.slug)
        if not pstate:
            continue

        saved_engines = pstate.get("engines", {})
        saved_modes = pstate.get("engine_modes")
        explicit_names = pstate.get("explicitly_disabled_engines")
        has_explicit_metadata = isinstance(explicit_names, list)
        explicit_names = set(explicit_names or ())
        for engine in provider.engines:
            if isinstance(saved_modes, dict) and engine.name in saved_modes:
                try:
                    engine.set_mode(saved_modes[engine.name])
                    continue
                except (TypeError, ValueError):
                    pass
            if engine.name in saved_engines:
                engine.enabled = bool(saved_engines[engine.name])
                engine.explicitly_disabled = (
                    engine.name in explicit_names
                    if has_explicit_metadata
                    else not engine.enabled
                )

        saved_preset_names = pstate.get("active_presets", [])
        provider.active_presets = [
            p for p in provider.presets if p.name in saved_preset_names
        ]


def save_state(providers) -> None:
    """Write current engine/preset selections, preserving other top-level keys.

    Flushes immediately — filter-menu Confirm is an explicit user action and
    should survive a hard kill.
    """
    data = store.read()
    data["providers"] = {
        p.slug: {
            "engines": {e.name: e.enabled for e in p.engines},
            "engine_modes": {e.name: e.mode for e in p.engines},
            "explicitly_disabled_engines": [
                e.name
                for e in p.engines
                if e.mode == "off" and e.explicitly_disabled
            ],
            "active_presets": [pr.name for pr in p.active_presets],
        }
        for p in providers
    }
    store.write(data)
    store.flush()


def load_setting(key: str, default=None):
    """Read a value from the `settings` subtree of the state file."""
    return store.read().get("settings", {}).get(key, default)


def save_setting(key: str, value) -> None:
    """Write a value into the `settings` subtree of the state file, preserving other keys."""
    data = store.read()
    data.setdefault("settings", {})[key] = value
    store.write(data)


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------

_HISTORY_MAX = 50


def load_history() -> list[dict]:
    """Return the saved search history (newest first).

    Each entry is ``{"query": str, "provider": str, "timestamp": str}``.
    """
    return store.read().get("history", [])


def save_history(entries: list[dict]) -> None:
    """Persist a history list, capping at *_HISTORY_MAX* entries."""
    data = store.read()
    data["history"] = entries[:_HISTORY_MAX]
    store.write(data)


def add_history_entry(
    query: str,
    provider_name: str,
    presets: list[str] | None = None,
    kind: str = "keyword",
    facet: str | None = None,
    name: str | None = None,
) -> None:
    """Record a search, newest on top, deduplicated.

    Keyword searches dedup on query+provider and replay as a normal search.
    ``kind="creator"`` records a by-creator search (``facet`` key + creator
    ``name``, with ``query`` as the display label); those dedup on
    provider+facet+name and replay through the by-creator flow. *presets* are the
    active preset names at search time, shown in the history menu.
    """
    from datetime import datetime, timezone

    history = load_history()

    if kind == "creator":
        history = [
            e for e in history
            if not (e.get("kind") == "creator"
                    and e.get("provider") == provider_name
                    and e.get("facet") == facet
                    and (e.get("name", "") or "").lower() == (name or "").lower())
        ]
    else:
        history = [
            e for e in history
            if not (e.get("kind", "keyword") == "keyword"
                    and e.get("query", "").lower() == query.lower()
                    and e.get("provider") == provider_name)
        ]

    entry = {
        "query": query,
        "provider": provider_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "presets": list(presets) if presets else [],
    }
    if kind == "creator":
        entry["kind"] = "creator"
        entry["facet"] = facet
        entry["name"] = name
    history.insert(0, entry)
    save_history(history)


def history_queries(provider_slug: str) -> list[str]:
    """Past search query strings for one provider, newest first.

    Powers the ↑/↓ history recall in the search prompt. History is already
    deduped per query+provider, so these are unique.
    """
    return [
        e.get("query", "")
        for e in load_history()
        if e.get("provider") == provider_slug and e.get("query")
    ]


def creator_history(provider_slug: str, facet_key: str) -> list[str]:
    """Past creator names searched for one provider+facet, newest first — derived
    from the main history's creator entries (powers ↑/↓ recall in the name
    prompt). Already deduped per provider+facet+name at record time.
    """
    return [
        e.get("name", "")
        for e in load_history()
        if e.get("kind") == "creator"
        and e.get("provider") == provider_slug
        and e.get("facet") == facet_key
        and e.get("name")
    ]


def clear_history() -> None:
    """Wipe all history entries (keyword + creator). Flushes immediately."""
    save_history([])
    store.flush()
