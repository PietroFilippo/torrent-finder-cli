"""OpenLibrary resolver — book author lookups.

Keyless public API (https://openlibrary.org/developers/api). Used for the
Books provider's "Author" facet: an author resolves to their works ordered by
edition count (a popularity proxy), which are then searched on the book
backends. Fails soft to an empty list on any network/parse error.

OpenLibrary asks for an identifying User-Agent; no rate limit beyond that at
this call volume (one search + one page per picker step).
"""

import requests

from torrent_finder.resolvers.types import Entity, Work

_API = "https://openlibrary.org"
_UA = {
    "User-Agent": "torrent-finder-cli (https://github.com/PietroFilippo/torrent-finder-cli)",
    "Accept": "application/json",
}
_PAGE_SIZE = 50


def _get(path: str, params: dict | None = None) -> dict | None:
    """GET an OpenLibrary endpoint; return the parsed JSON or None on failure."""
    try:
        resp = requests.get(f"{_API}{path}", params=params or {}, headers=_UA, timeout=12)
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, dict) else None
    except (requests.RequestException, ValueError):
        return None


_dominant_authors: dict[str, tuple[str, ...]] = {}


def dominant_author(title: str) -> tuple[str, ...]:
    """Authors of the clearly dominant work titled exactly *title*, or ().

    Dominant means at least 10 editions and three times the editions of any
    same-title work by other authors: Kafka for "Metamorphosis", Zevin for
    "Tomorrow and Tomorrow and Tomorrow", nothing for an ambiguous or rare
    title. Cached for the session; () on any network error.
    """
    from torrent_finder.result_view import words
    key = " ".join(words(title))
    if not key:
        return ()
    if key in _dominant_authors:
        return _dominant_authors[key]
    data = _get("/search.json", {"title": title, "fields": "title,author_name,edition_count", "limit": 20})
    if data is None:
        return ()
    exact = [doc for doc in data.get("docs") or []
             if " ".join(words(doc.get("title") or "")) == key and doc.get("author_name")]
    exact.sort(key=lambda doc: doc.get("edition_count") or 0, reverse=True)
    authors: tuple[str, ...] = ()
    if exact:
        top = exact[0]
        names = {name.casefold() for name in top["author_name"]}
        rival = max((doc.get("edition_count") or 0 for doc in exact[1:]
                     if not names & {name.casefold() for name in doc["author_name"]}), default=0)
        if (top.get("edition_count") or 0) >= max(10, 3 * rival):
            authors = tuple(top["author_name"][:3])
    _dominant_authors[key] = authors
    return authors


def author_search(name: str) -> "list[Entity] | None":
    """Resolve an author name to candidate authors (for disambiguation).

    Returns None when OpenLibrary can't be reached (so the caller can say
    "service unavailable" instead of "no match"); [] when there's genuinely
    no matching author.
    """
    data = _get("/search/authors.json", {"q": name, "limit": 10})
    if data is None:
        return None
    out: list[Entity] = []
    for doc in data.get("docs") or []:
        key = doc.get("key")
        if not key:
            continue
        bits = []
        if doc.get("top_work"):
            bits.append(f"known for {doc['top_work']}")
        if doc.get("work_count"):
            bits.append(f"{doc['work_count']} works")
        out.append(Entity(
            id=str(key),
            name=doc.get("name") or "Unknown",
            detail=" · ".join(bits),
        ))
    return out


def author_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    """Return one page of an author's works (edition-count-ordered) + whether
    more remain.

    Edition count is the best popularity proxy OpenLibrary offers — prolific
    authors have hundreds of obscure entries, and the picker wants the known
    books first. Pass page=1, 2, 3, … for successive pages.
    """
    offset = (page - 1) * _PAGE_SIZE
    data = _get("/search.json", {
        "author_key": entity.id,
        "sort": "editions",
        "fields": "title,first_publish_year",
        "limit": _PAGE_SIZE,
        "offset": offset,
    })
    if data is None:
        return [], False

    works: list[Work] = []
    seen: set[str] = set()
    for doc in data.get("docs") or []:
        title = doc.get("title")
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        year = doc.get("first_publish_year")
        works.append(Work(
            title=title,
            year=year if isinstance(year, int) else None,
            subtitle=str(year) if year else "",
            authors=(entity.name,),
        ))

    try:
        total = int(data.get("numFound") or 0)
    except (TypeError, ValueError):
        total = 0
    has_more = offset + len(data.get("docs") or []) < total
    return works, has_more
