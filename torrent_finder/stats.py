"""Usage statistics — recorders + storage under the `stats` subtree of filter_state.json.

Persistence goes through ``store.py`` (the filter_state.json owner). Every
`record_*` is an increment applied to whatever the saved file holds when the
session is saved, so counters from two open windows add up instead of one
overwriting the other. Timestamps are taken once, outside the operation.
"""

from datetime import datetime, timezone

from torrent_finder import store


_STATS_KEY = "stats"


def _get_stats() -> dict:
    return store.read().get(_STATS_KEY, {})


def _record(change) -> None:
    """Apply *change* to the stats subtree; saved with the session's other changes."""
    store.update(lambda data: change(store.section(data, _STATS_KEY)))


def _bump(stats: dict, *path: str, by: int = 1) -> None:
    """Increment an int at stats[path[0]][path[1]]...[path[-1]] by `by`.
    A part of the path that isn't the expected kind (a hand-edited file) is reset."""
    d = stats
    for k in path[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    current = d.get(path[-1], 0)
    d[path[-1]] = (current if isinstance(current, int) and not isinstance(current, bool) else 0) + by


# ---------------------------------------------------------------------------
# Public recorders
# ---------------------------------------------------------------------------

def record_session_start() -> None:
    """Bump session counter; set first_use on first ever run."""
    now = datetime.now(timezone.utc).isoformat()

    def change(stats):
        stats.setdefault("first_use", now)
        _bump(stats, "session_count")
    _record(change)


def record_search(provider: str, query: str, active_presets: list[str]) -> None:
    """Called once per successful search (has at least one result)."""
    def change(stats):
        _bump(stats, "searches_by_provider", provider)
        _bump(stats, "searches_total")
        q = query.lower().strip()
        if q:
            _bump(stats, "top_queries", q)
        for name in active_presets:
            _bump(stats, "preset_usage", name)
    _record(change)


def record_creator_search(provider: str, facet: str, name: str, active_presets: list[str]) -> None:
    """Once per by-creator search that returned results. Counts in the search
    totals + per-provider like any search, but tracked separately from keyword
    queries — its own by-facet + top-creators counters; never in top_queries."""
    def change(stats):
        _bump(stats, "searches_by_provider", provider)
        _bump(stats, "searches_total")
        _bump(stats, "creator_searches_by_facet", facet)
        nm = (name or "").strip()
        if nm:
            _bump(stats, "top_creators", nm)
        for preset_name in active_presets:
            _bump(stats, "preset_usage", preset_name)
    _record(change)


def record_torrent_picked(provider: str, seeders: int) -> None:
    def change(stats):
        _bump(stats, "torrents_picked_by_provider", provider)
        _bump(stats, "picked_count")
        _bump(stats, "picked_seeders_sum", by=int(seeders))
    _record(change)


def record_method_pick(method: str) -> None:
    _record(lambda stats: _bump(stats, "method_picks", method))


def record_method_complete(method: str) -> None:
    _record(lambda stats: _bump(stats, "method_completed", method))


def record_magnet_dispatch() -> None:
    _record(lambda stats: _bump(stats, "magnet_dispatches"))


def record_episode_picker_used() -> None:
    _record(lambda stats: _bump(stats, "episode_picker_uses"))


def add_runtime_seconds(seconds: float) -> None:
    if seconds <= 0:
        return
    _record(lambda stats: _bump(stats, "total_runtime_s", by=float(seconds)))


def reset_stats() -> None:
    """Wipe the stats subtree (keeps other state keys intact).

    Saved immediately; raises ``ValueError`` / ``store.SaveError`` when that
    fails, leaving the counters in place.
    """
    store.commit(lambda data: data.pop(_STATS_KEY, None))


# ---------------------------------------------------------------------------
# Read helpers for the viewer
# ---------------------------------------------------------------------------

def get_all_stats() -> dict:
    """Return the raw stats dict."""
    return _get_stats()


def average_seeders() -> float:
    s = _get_stats()
    n = s.get("picked_count", 0)
    return (s.get("picked_seeders_sum", 0) / n) if n else 0.0


def days_since_first_use() -> int:
    s = _get_stats()
    ts = s.get("first_use")
    if not ts:
        return 0
    try:
        dt = datetime.fromisoformat(ts)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return 0
