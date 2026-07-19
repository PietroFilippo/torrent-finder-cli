"""Category-scoped client for the Knaben torrent meta-index API."""

from __future__ import annotations

import re
from html import unescape
from typing import Iterable

import requests

from torrent_finder.search_result import SearchResult


API_URL = "https://api.knaben.org/v1"
_MAX_RESULTS = 50
_INFO_HASH = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")


def search(query: str, categories: Iterable[int]) -> list[SearchResult]:
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
    body = {
        "search_type": "100%",
        "search_field": "title",
        "query": normalized_query,
        "order_by": "seeders",
        "order_direction": "desc",
        "categories": category_ids,
        "from": 0,
        "size": _MAX_RESULTS,
        "hide_unsafe": True,
        "hide_xxx": True,
    }
    try:
        response = requests.post(
            API_URL,
            json=body,
            timeout=15,
            headers={"User-Agent": "torrent-finder-cli"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []

    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
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

    return results
