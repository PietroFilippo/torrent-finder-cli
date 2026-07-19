"""Bounded last-known-good cache for intermittent APIBay searches.

Only successful APIBay result sets are stored. When a later live search for
the same provider/query returns nothing, callers can replay the cached magnet
metadata while preserving source="Apibay" for acquisition routing.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterable

from torrent_finder.constants import machine_state_path
from torrent_finder.search_result import SearchResult, normalize_result


CACHE_PATH = machine_state_path("apibay_cache.json")
_VERSION = 1
_MAX_ENTRIES = 128

_lock = threading.RLock()
_cache: dict | None = None
_loaded_path: str | None = None


def _normalized_query(query: str) -> str:
    return " ".join(query.casefold().split())


def _key(provider_slug: str, query: str) -> str:
    return f"{provider_slug.casefold()}\n{_normalized_query(query)}"


def _empty_cache() -> dict:
    return {"version": _VERSION, "entries": {}}


def _read_cache() -> dict:
    global _cache, _loaded_path
    if _cache is not None and _loaded_path == CACHE_PATH:
        return _cache

    data: dict | None = None
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as cache_file:
            candidate = json.load(cache_file)
        if (
            isinstance(candidate, dict)
            and candidate.get("version") == _VERSION
            and isinstance(candidate.get("entries"), dict)
        ):
            data = candidate
    except (OSError, json.JSONDecodeError):
        pass

    _cache = data or _empty_cache()
    _loaded_path = CACHE_PATH
    return _cache


def _write_cache(data: dict) -> None:
    directory = os.path.dirname(CACHE_PATH)
    temp_path = (
        f"{CACHE_PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        os.makedirs(directory, exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as cache_file:
            json.dump(data, cache_file, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp_path, CACHE_PATH)
    except OSError:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _serialized_rows(
    results: Iterable[SearchResult | dict],
) -> list[dict]:
    rows: list[dict] = []
    for raw_result in results:
        result = normalize_result(raw_result)
        if not result.info_hash:
            continue
        rows.append(
            {
                "name": result.name,
                "info_hash": result.info_hash,
                "seeders": result.seeders,
                "leechers": result.leechers,
                "size": result.size,
                "source": "Apibay",
                "page_url": result.page_url,
            }
        )
    return rows


def store(
    provider_slug: str,
    query: str,
    results: Iterable[SearchResult | dict],
    *,
    now: float | None = None,
) -> None:
    """Persist one successful APIBay result set, bounded by query count."""
    rows = _serialized_rows(results)
    normalized = _normalized_query(query)
    if not provider_slug or not normalized or not rows:
        return

    saved_at = float(time.time() if now is None else now)
    with _lock:
        data = _read_cache()
        entries = data["entries"]
        entries[_key(provider_slug, normalized)] = {
            "provider": provider_slug,
            "query": normalized,
            "saved_at": saved_at,
            "results": rows,
        }
        overflow = len(entries) - _MAX_ENTRIES
        if overflow > 0:
            oldest = sorted(
                entries,
                key=lambda entry_key: float(
                    entries[entry_key].get("saved_at", 0) or 0
                ),
            )
            for entry_key in oldest[:overflow]:
                entries.pop(entry_key, None)
        _write_cache(data)


def load(provider_slug: str, query: str) -> list[SearchResult]:
    """Return cached rows marked as stale, or an empty list on any miss."""
    with _lock:
        entry = _read_cache()["entries"].get(_key(provider_slug, query))
        if not isinstance(entry, dict):
            return []
        saved_at = float(entry.get("saved_at", 0) or 0)
        raw_rows = entry.get("results")
        if not isinstance(raw_rows, list):
            return []

        results: list[SearchResult] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            result = normalize_result(raw_row)
            if not result.info_hash:
                continue
            result.source = "Apibay"
            result.extra["apibay_cached_at"] = saved_at
            results.append(result)
        return results


def _reset_for_tests() -> None:
    global _cache, _loaded_path
    with _lock:
        _cache = None
        _loaded_path = None
