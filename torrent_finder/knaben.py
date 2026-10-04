"""Category-scoped client for the Knaben torrent meta-index API (v2).

Knaben asks API clients to use v2: its GET searches can be cached by the edge
server, where v1's POST bodies could not, and serving API bandwidth strained the
site. The request keeps v1's results (checked on 12 query/page pairs in October
2026: same totals, rows and order). It searches titles, sorted by seeders, 50
rows a page, with unsafe and adult rows hidden (v2's defaults). The ``dead`` flag
keeps zero-seed rows, which v1 returned and v2 otherwise hides.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Iterable
from urllib.parse import urlencode

import requests

from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import search_request


API_URL = "https://api.knaben.org/v2/search"
_MAX_RESULTS = 50
# 40-hex BitTorrent v1 hashes only: magnets here are built as urn:btih, which
# a 64-character (v2) hash would make unusable.
_INFO_HASH = re.compile(r"[0-9a-fA-F]{40}\Z")


def search(query: str, categories: Iterable[int], *, page: int = 1) -> list[SearchResult]:
    """Return safety-filtered, hash-bearing rows for a provider-scoped query."""
    normalized_query = " ".join(query.split())
    if not normalized_query:
        return []

    try:
        category_ids = [int(category) for category in categories]
    except (TypeError, ValueError):
        return []
    if not category_ids:
        return []
    params = {
        "q": normalized_query,
        "sf": "title",
        "o": "seeders",
        "d": "desc",
        "c": ",".join(str(category) for category in category_ids),
        "s": _MAX_RESULTS,
        "f": (max(1, page) - 1) * _MAX_RESULTS,
    }
    try:
        # Flags take no value; "dead" keeps zero-seed rows visible.
        response = search_request(requests.get,
            f"{API_URL}?{urlencode(params)}&dead",
            timeout=15,
            headers={"User-Agent": "torrent-finder-cli"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        from torrent_finder.search_diagnostics import record_failure
        record_failure(error)
        return []

    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        from torrent_finder.search_diagnostics import record_failure
        record_failure(message="The source response did not contain a results list.")
        return []

    results: list[SearchResult] = []
    seen_hashes: set[str] = set()
    for row in hits:
        if not isinstance(row, dict):
            continue
        raw_hash = row.get("hash")
        info_hash = str(raw_hash or "").strip().lower()
        if not _INFO_HASH.fullmatch(info_hash) or info_hash in seen_hashes:
            continue
        seen_hashes.add(info_hash)

        raw_title = row.get("title")
        title = (
            unescape(raw_title)
            if isinstance(raw_title, str) and raw_title
            else "Unknown"
        )
        result = SearchResult(
            name=title,
            info_hash=info_hash,
            seeders=row.get("seeders", 0),
            leechers=row.get("peers", 0),
            size=row.get("bytes", 0),
            source="Knaben",
            page_url=(
                row.get("details")
                if (
                    isinstance(row.get("details"), str)
                    and row["details"].startswith(("https://", "http://"))
                )
                else ""
            ),
        )
        result.extra.update(
            {
                "knaben_tracker": row.get("tracker") or "",
                "knaben_category": row.get("category") or "",
                "knaben_last_seen": row.get("lastSeen") or "",
                "knaben_virus_detection": row.get("virusDetection"),
            }
        )
        results.append(result)

    from torrent_finder.search_session import PageRows
    return PageRows(results, has_more=len(hits) >= _MAX_RESULTS)
