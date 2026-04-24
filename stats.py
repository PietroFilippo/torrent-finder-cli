"""Usage statistics — recorders + storage under the `stats` subtree of filter_state.json.

Every `record_*` reads the full state, mutates the stats subtree, writes back.
Cheap given the tiny JSON and infrequent events.
"""

from datetime import datetime, timezone

from state import _read_state, _write_state


_STATS_KEY = "stats"


def _get_stats() -> dict:
    return _read_state().get(_STATS_KEY, {})


def _save_stats(stats: dict) -> None:
    data = _read_state()
    data[_STATS_KEY] = stats
    _write_state(data)


def _bump(stats: dict, *path: str, by: int = 1) -> None:
    """Increment an int at stats[path[0]][path[1]]...[path[-1]] by `by`."""
    d = stats
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = d.get(path[-1], 0) + by


# ---------------------------------------------------------------------------
# Public recorders
# ---------------------------------------------------------------------------

def record_session_start() -> None:
    """Bump session counter; set first_use on first ever run."""
    stats = _get_stats()
    if "first_use" not in stats:
        stats["first_use"] = datetime.now(timezone.utc).isoformat()
    _bump(stats, "session_count")
    _save_stats(stats)


def record_search(provider: str, query: str, active_presets: list[str]) -> None:
    """Called once per successful search (has at least one result)."""
    stats = _get_stats()
    _bump(stats, "searches_by_provider", provider)
    stats["searches_total"] = stats.get("searches_total", 0) + 1

    q = query.lower().strip()
    if q:
        _bump(stats, "top_queries", q)

    for name in active_presets:
        _bump(stats, "preset_usage", name)

    _save_stats(stats)


def record_torrent_picked(provider: str, seeders: int) -> None:
    stats = _get_stats()
    _bump(stats, "torrents_picked_by_provider", provider)
    stats["picked_count"] = stats.get("picked_count", 0) + 1
    stats["picked_seeders_sum"] = stats.get("picked_seeders_sum", 0) + int(seeders)
    _save_stats(stats)


def record_method_pick(method: str) -> None:
    stats = _get_stats()
    _bump(stats, "method_picks", method)
    _save_stats(stats)


def record_method_complete(method: str) -> None:
    stats = _get_stats()
    _bump(stats, "method_completed", method)
    _save_stats(stats)


def record_magnet_dispatch() -> None:
    stats = _get_stats()
    _bump(stats, "magnet_dispatches")
    _save_stats(stats)


def record_episode_picker_used() -> None:
    stats = _get_stats()
    _bump(stats, "episode_picker_uses")
    _save_stats(stats)


def add_runtime_seconds(seconds: float) -> None:
    if seconds <= 0:
        return
    stats = _get_stats()
    stats["total_runtime_s"] = stats.get("total_runtime_s", 0.0) + float(seconds)
    _save_stats(stats)


def reset_stats() -> None:
    """Wipe the stats subtree (keeps other state keys intact)."""
    data = _read_state()
    if _STATS_KEY in data:
        del data[_STATS_KEY]
    _write_state(data)


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
