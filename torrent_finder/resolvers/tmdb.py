"""TMDB resolver — Movies & Series director + studio lookups.

Needs a free **TMDB v3 API key** (`TMDB_API_KEY`, via the Credentials menu or
env). Each function fails soft to None/empty on any network/parse error, matching
the other resolvers, and returns None from ``*_search`` when the API can't be
reached so the UI can say "service unavailable" instead of "not found".

Director = eager (TMDB returns a person's whole filmography in one call).
Studio  = network-paged (TMDB discover is 20/page with a total_pages count).
"""

import concurrent.futures

import requests

from torrent_finder import credentials
from torrent_finder.resolvers.types import Entity, Work

_API = "https://api.themoviedb.org/3"


def _get(path: str, params: dict | None = None) -> dict | None:
    """GET a TMDB endpoint with the configured key; None on failure/missing key."""
    key = credentials.get_credential("TMDB_API_KEY")
    if not key:
        return None
    query = {"api_key": key}
    if params:
        query.update(params)
    try:
        resp = requests.get(f"{_API}{path}", params=query, timeout=12,
                            headers={"Accept": "application/json"})
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _credit_to_work(item: dict) -> Work:
    """Build a Work from a TMDB movie/tv record. English title primary, original
    title as alt (for torrent matching); ``media_type`` picks movie vs tv fields."""
    if item.get("media_type") == "tv":
        title, orig = item.get("name"), item.get("original_name")
        date, kind = item.get("first_air_date") or "", "TV"
    else:
        title, orig = item.get("title"), item.get("original_title")
        date, kind = item.get("release_date") or "", "Movie"

    primary = title or orig or "Unknown"
    alts: list[str] = []
    for cand in (orig, title):
        if cand and cand != primary and cand not in alts:
            alts.append(cand)

    year = int(date[:4]) if date[:4].isdigit() else None
    sub_bits = [str(year)] if year else []
    sub_bits.append(kind)

    return Work(title=primary, alt_titles=tuple(alts), year=year,
                subtitle=" · ".join(sub_bits), role=item.get("job") or "")


# --- Director (person) ------------------------------------------------------

def person_search(name: str) -> "list[Entity] | None":
    """Resolve a person name to candidate people (for disambiguation).

    None when TMDB is unreachable; [] when nobody matches.
    """
    data = _get("/search/person", {"query": name, "include_adult": "false"})
    if data is None:
        return None
    out: list[Entity] = []
    for p in (data.get("results") or [])[:10]:
        pid = p.get("id")
        if pid is None:
            continue
        dept = p.get("known_for_department") or ""
        known: list[str] = []
        for kf in p.get("known_for") or []:
            t = kf.get("title") or kf.get("name")
            if t and t not in known:
                known.append(t)
            if len(known) >= 3:
                break
        bits = []
        if dept:
            bits.append(dept)
        if known:
            bits.append("known for " + ", ".join(known))
        out.append(Entity(id=str(pid), name=p.get("name") or "Unknown", detail=" · ".join(bits)))
    return out


def director_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    """A person's films & shows where they're credited as Director (movies + TV,
    via combined_credits). Eager — returns everything, ``has_more=False``."""
    if page != 1:
        return [], False
    data = _get(f"/person/{int(entity.id)}/combined_credits")
    if data is None:
        return [], False
    seen: set = set()
    works: list[Work] = []
    for c in data.get("crew") or []:
        if (c.get("job") or "") != "Director":
            continue
        key = (c.get("media_type"), c.get("id"))
        if c.get("id") is None or key in seen:
            continue
        seen.add(key)
        works.append(_credit_to_work(c))
    works.sort(key=lambda w: w.year or 0, reverse=True)  # most recent first
    return works, False


# --- Studio (company) -------------------------------------------------------

def company_search(name: str) -> "list[Entity] | None":
    """Resolve a studio/company name to candidates, ranked by film count.

    TMDB often has duplicate company entries with identical names — one populated,
    one a near-empty stub — which are indistinguishable by name alone. So enrich
    each with its film count (one discover call apiece, concurrent), drop the
    empty ones, rank by count, and label it. None when TMDB is unreachable.
    """
    data = _get("/search/company", {"query": name})
    if data is None:
        return None
    candidates = [c for c in (data.get("results") or []) if c.get("id") is not None][:10]
    if not candidates:
        return []

    def _film_count(cid: int) -> int:
        d = _get("/discover/movie", {"with_companies": cid, "page": 1})
        return (d or {}).get("total_results", 0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(candidates))) as ex:
        counts = list(ex.map(lambda c: _film_count(c["id"]), candidates))

    ranked = sorted(((c, n) for c, n in zip(candidates, counts) if n > 0),
                    key=lambda t: t[1], reverse=True)
    return [
        Entity(id=str(co["id"]), name=co.get("name") or "Unknown",
               detail=f"{n} film{'s' if n != 1 else ''}")
        for co, n in ranked
    ]


def company_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    """Films from a company, most-popular first. Network-paged (20/page)."""
    data = _get("/discover/movie", {
        "with_companies": int(entity.id),
        "sort_by": "popularity.desc",
        "include_adult": "false",
        "page": page,
    })
    if data is None:
        return [], False
    works = [_credit_to_work({**m, "media_type": "movie"}) for m in (data.get("results") or [])]
    has_more = page < (data.get("total_pages") or 1)
    return works, has_more


def test_api_key(key: str) -> "tuple[bool | None, str]":
    """Validate a TMDB v3 key. (True, msg) ok · (False, msg) rejected ·
    (None, msg) couldn't verify."""
    try:
        resp = requests.get(f"{_API}/authentication", params={"api_key": key}, timeout=10)
    except requests.RequestException as exc:
        return None, f"couldn't reach TMDB ({exc})"
    if resp.status_code == 200:
        try:
            if (resp.json() or {}).get("success"):
                return True, "key valid"
        except ValueError:
            pass
        return None, "unexpected response"
    if resp.status_code == 401:
        return False, "invalid API key"
    return None, f"unexpected response ({resp.status_code})"
