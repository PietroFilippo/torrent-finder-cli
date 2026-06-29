"""Jikan (MyAnimeList) resolver — manga serialization magazine lookups.

Keyless public API (https://docs.api.jikan.moe). Used for the Manga provider's
"Magazine" facet: a Japanese serialization magazine (Weekly Shōnen Jump, etc.)
resolves to the manga it serialized, which are then searched on the torrent
backends. Fails soft to an empty list on any network/parse error.

Jikan rate-limits (~3 req/s, 60/min), so the works lookup paginates gently and
caps the page count — magazines like Shōnen Jump have hundreds of entries, and a
top-by-popularity slice is plenty for a picker.
"""

import time

import requests

from torrent_finder.resolvers.types import Entity, Work

_API = "https://api.jikan.moe/v4"
_PAGES_PER_CHUNK = 4    # Jikan serves 25/page; 4 pages ≈ 100 titles per "load more"
_PAGE_DELAY_S = 0.2     # spacing between page requests (Jikan ~3 req/s limit)


def _get(path: str, params: dict | None = None, retries: int = 2) -> dict | None:
    """GET a Jikan endpoint; return the parsed JSON or None on failure.

    Retries on transient errors — Jikan's free tier intermittently returns
    502/504 gateway errors, which a short retry usually clears.
    """
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                f"{_API}{path}",
                params=params or {},
                headers={"Accept": "application/json"},
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            return payload if isinstance(payload, dict) else None
        except (requests.RequestException, ValueError):
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            return None
    return None


def magazine_search(name: str) -> "list[Entity] | None":
    """Resolve a magazine name to candidate magazines (for disambiguation).

    Returns None when Jikan can't be reached (its manga/magazine endpoints
    intermittently 502/504) so the caller can say "service unavailable" instead
    of "no match"; [] when there's genuinely no matching magazine.
    """
    data = _get("/magazines", {"q": name, "limit": 10})
    if data is None:
        return None
    out: list[Entity] = []
    for mag in data.get("data") or []:
        mid = mag.get("mal_id")
        if mid is None:
            continue
        count = mag.get("count")
        detail = f"{count} manga" if count else "Serialization magazine"
        out.append(Entity(id=str(mid), name=mag.get("name") or "Unknown", detail=detail))
    return out


def _manga_to_work(manga: dict) -> Work:
    """Build a Work from a Jikan manga entry, English title as primary."""
    title = manga.get("title")
    english = manga.get("title_english")
    primary = english or title or "Unknown"

    alts: list[str] = []
    for cand in (title, english):
        if cand and cand != primary and cand not in alts:
            alts.append(cand)

    frm = ((manga.get("published") or {}).get("prop") or {}).get("from") or {}
    year = frm.get("year")
    mtype = manga.get("type") or ""
    sub_bits = [str(year)] if year else []
    if mtype:
        sub_bits.append(mtype)

    return Work(title=primary, alt_titles=tuple(alts), year=year, subtitle=" · ".join(sub_bits))


def magazine_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    """Return one chunk of a magazine's manga (popularity-ordered) + whether more
    remain.

    A "page" here is ``_PAGES_PER_CHUNK`` Jikan pages (×25 ≈ 100 titles), so each
    load-more step pulls a chunk. Pass page=1, 2, 3, … for successive chunks.
    Returns ``(works, has_more)``; ``has_more`` is False once the magazine's last
    Jikan page is reached.
    """
    seen: set = set()
    works: list[Work] = []
    has_more = False
    start = (page - 1) * _PAGES_PER_CHUNK + 1
    for jp in range(start, start + _PAGES_PER_CHUNK):
        data = _get("/manga", {
            "magazines": int(entity.id),
            "order_by": "members",
            "sort": "desc",
            "page": jp,
            "limit": 25,
        })
        if data is None:
            break
        for manga in data.get("data") or []:
            mid = manga.get("mal_id")
            if mid in seen:
                continue
            seen.add(mid)
            works.append(_manga_to_work(manga))
        has_more = bool((data.get("pagination") or {}).get("has_next_page"))
        if not has_more:
            break
        if jp < start + _PAGES_PER_CHUNK - 1:
            time.sleep(_PAGE_DELAY_S)
    return works, has_more
