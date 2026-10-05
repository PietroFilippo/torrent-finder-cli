"""Persist engine modes, active filter presets, history, and misc settings.

Persistence itself (filter_state.json, its lock and cache) is owned by
``store.py``; this module reads the state and changes it with store operations.
Explicit user actions (``save_state``, ``clear_history``) are committed at once
and raise when saving fails; other changes are saved with the session.
"""

from copy import deepcopy
import hashlib
import json

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
    subtrees. Returns True if anything changed."""
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
    if _migrate_legacy_names(deepcopy(store.read())):
        store.update(_migrate_legacy_names)
    provider_states = store.read().get("providers", {})
    for provider in providers:
        pstate = provider_states.get(provider.slug)
        if not pstate:
            continue

        apply_provider_state(provider, pstate)


def apply_provider_state(provider, pstate: dict) -> None:
    """Apply a provider snapshot without reading or writing the shared store."""
    from torrent_finder.name_rules import NameRules
    provider.name_rules = NameRules.restore(pstate.get("name_rules", {}))
    categories = getattr(provider, "nyaa_categories", {})
    if pstate.get("nyaa_category") in categories:
        provider.nyaa_category = pstate["nyaa_category"]
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
                engine.name in explicit_names if has_explicit_metadata else not engine.enabled
            )
    saved_preset_names = pstate.get("active_presets", [])
    provider.active_presets = [p for p in provider.presets if p.name in saved_preset_names]
    preferred = pstate.get("preferred_presets", [])
    provider.preferred_presets = [p for p in provider.presets
                                 if p.name in preferred and p not in provider.active_presets]
    from torrent_finder.result_view import SORT_ORDERS
    order = pstate.get("result_sort", "relevance")
    provider.result_sort = order if isinstance(order, str) and order in SORT_ORDERS else "relevance"


def reload_state(providers) -> None:
    """Reset omitted provider choices before applying a replaced settings file."""
    for provider in providers:
        if not getattr(provider, "is_combined", False):
            apply_provider_state(provider, provider_snapshot(type(provider)()))
    load_state(providers)


def provider_snapshot(provider) -> dict:
    return {
        "name_rules": provider.name_rules.snapshot(),
        **({"nyaa_category": provider.nyaa_category} if getattr(provider, "nyaa_categories", {}) else {}),
        "engines": {e.name: e.enabled for e in provider.engines},
        "engine_modes": {e.name: e.mode for e in provider.engines},
        "explicitly_disabled_engines": [
            e.name for e in provider.engines if e.mode == "off"
        ],
        "active_presets": [p.name for p in provider.active_presets],
        "preferred_presets": [p.name for p in provider.preferred_presets if p not in provider.active_presets],
        "result_sort": provider.result_sort,
    }


def save_state(providers) -> None:
    """Save the selections of *providers*; other providers and keys are kept.

    Filter-menu Confirm is an explicit user action: it is saved immediately and
    raises ``ValueError`` / ``store.SaveError`` when that fails.
    """
    snapshots = {p.slug: provider_snapshot(p) for p in providers}

    def change(data):
        store.section(data, "providers").update(deepcopy(snapshots))
    store.commit(change)


def load_setting(key: str, default=None):
    """Read a value from the `settings` subtree of the state file."""
    settings = store.read().get("settings")
    return settings.get(key, default) if isinstance(settings, dict) else default


def commit_setting(key: str, value) -> None:
    """Set one value in the `settings` subtree and save it now (an explicit
    choice): raises ``ValueError`` / ``store.SaveError`` when that fails."""
    def change(data):
        store.section(data, "settings")[key] = deepcopy(value)
    store.commit(change)


def save_setting(key: str, value) -> None:
    """Set one value in the `settings` subtree; saved with the session's other changes."""
    def change(data):
        store.section(data, "settings")[key] = deepcopy(value)
    store.update(change)


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------

# Combined searches carry a profile snapshot (several KB). The saved file keeps
# each distinct snapshot once under this key; entries refer to it by id.
_HISTORY_PROFILES = "history_profiles"


def _profile_id(profile: dict) -> str:
    text = json.dumps(profile, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def compact_history(data: dict) -> None:
    """Store each history entry's combined-search profile once, by reference.

    Entries keep ``search_profile_id``; ``history_profiles`` holds only the
    snapshots still referenced. Idempotent, so history operations apply it after
    every change (and imports after merging full-form entries).
    """
    history = data.get("history")
    if not isinstance(history, list):
        return
    stored = data.get(_HISTORY_PROFILES)
    stored = stored if isinstance(stored, dict) else {}
    kept = {}
    for entry in history:
        if not isinstance(entry, dict):
            continue
        profile = entry.pop("search_profile", None)
        if isinstance(profile, dict):
            entry["search_profile_id"] = identity = _profile_id(profile)
            kept[identity] = profile
        elif entry.get("search_profile_id") in stored:
            kept[entry["search_profile_id"]] = stored[entry["search_profile_id"]]
    if kept:
        data[_HISTORY_PROFILES] = kept
    else:
        data.pop(_HISTORY_PROFILES, None)


def _saved_history() -> list[dict]:
    """History as stored: combined searches refer to their profile by id."""
    history = store.read().get("history", [])
    return history if isinstance(history, list) else []


def load_history() -> list[dict]:
    """Return the saved search history (newest first).

    Each entry is ``{"query": str, "provider": str, "timestamp": str}``; a
    combined search also has its ``search_profile``, expanded from the shared
    copy kept in the saved file.
    """
    data = store.read()
    profiles = data.get(_HISTORY_PROFILES)
    history = data.get("history", [])
    if not isinstance(history, list):
        return []
    if not isinstance(profiles, dict):
        return history
    expanded = []
    for entry in history:
        if isinstance(entry, dict) and "search_profile_id" in entry:
            profile = profiles.get(entry["search_profile_id"])
            entry = {key: value for key, value in entry.items() if key != "search_profile_id"}
            if isinstance(profile, dict):
                entry["search_profile"] = deepcopy(profile)
        expanded.append(entry)
    return expanded


def add_history_entry(
    query: str,
    provider_name: str,
    presets: list[str] | None = None,
    kind: str = "keyword",
    facet: str | None = None,
    name: str | None = None,
    search_profile: dict | None = None,
    queries: list[str] | None = None,
) -> None:
    """Record a search, newest on top, deduplicated.

    Keyword searches dedup on query+provider and replay as a normal search.
    ``kind="creator"`` records a by-creator search (``facet`` key + creator
    ``name``, with ``query`` as the display label); those dedup on
    provider+facet+name and replay through the by-creator flow. *presets* are the
    active preset names at search time, shown in the history menu.
    """
    from datetime import datetime, timezone

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
    if search_profile is not None:
        entry["search_profile"] = deepcopy(search_profile)
    if queries:
        entry["queries"] = list(queries)

    def replaces(e: dict) -> bool:
        if kind == "creator":
            return (e.get("kind") == "creator"
                    and e.get("provider") == provider_name
                    and e.get("facet") == facet
                    and (e.get("name", "") or "").lower() == (name or "").lower())
        return (e.get("kind", "keyword") == "keyword"
                and (e.get("query", "") or "").lower() == query.lower()
                and e.get("provider") == provider_name
                and e.get("queries") == queries)

    def change(data):
        history = data.get("history")
        history = [e for e in history if isinstance(e, dict) and not replaces(e)] if isinstance(history, list) else []
        data["history"] = [deepcopy(entry), *history][:store.HISTORY_LIMIT]
        compact_history(data)
    store.update(change)


def history_queries(provider_slug: str) -> list[str]:
    """Past search query strings for one provider, newest first.

    Powers the ↑/↓ history recall in the search prompt. History is already
    deduped per query+provider, so these are unique.
    """
    return [
        e.get("query", "")
        for e in _saved_history()
        if e.get("provider") == provider_slug and e.get("query")
    ]


def history_notes(provider_slug: str) -> dict[str, str]:
    """A short note per past search of one provider, for the search screen's RECENT list.

    ``2h ago``, plus ``3 names`` when it searched several names of one work.
    The newest entry of a query wins.
    """
    from torrent_finder.utils import relative_time
    notes: dict[str, str] = {}
    for entry in _saved_history():
        query = entry.get("query") if isinstance(entry, dict) else None
        if entry.get("provider") != provider_slug or not isinstance(query, str) or query in notes:
            continue
        names = entry.get("queries")
        extra = f"{len(names)} names" if isinstance(names, list) and len(names) > 1 else ""
        notes[query] = " · ".join(filter(None, (relative_time(entry.get("timestamp")), extra)))
    return notes


def creator_history(provider_slug: str, facet_key: str) -> list[str]:
    """Past creator names searched for one provider+facet, newest first — derived
    from the main history's creator entries (powers ↑/↓ recall in the name
    prompt). Already deduped per provider+facet+name at record time.
    """
    return [
        e.get("name", "")
        for e in _saved_history()
        if e.get("kind") == "creator"
        and e.get("provider") == provider_slug
        and e.get("facet") == facet_key
        and e.get("name")
    ]


def clear_history() -> None:
    """Wipe all history entries (keyword + creator).

    Saved immediately; raises ``ValueError`` / ``store.SaveError`` when that
    fails, leaving the history in place.
    """
    def change(data):
        data["history"] = []
        data.pop(_HISTORY_PROFILES, None)
    store.commit(change)
