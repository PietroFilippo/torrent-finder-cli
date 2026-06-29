"""AniList GraphQL resolver — anime director/studio + manga writer lookups.

Keyless public API (https://anilist.co/graphiql). Each function fails soft to an
empty list on any network/parse error, matching the provider search backends.

Roles come back as free-text strings on the staff↔media edge ("Director",
"Chief Director", "Animation Director", "Story", "Story & Art", …). For anime we
keep only the *show* director roles (dropping animation/sound/art/episode/…); for
manga we keep the writer/author roles (Story, Story & Art, Original Creator) and
drop the pure "Art" credit.
"""

import requests

from torrent_finder.resolvers.types import Entity, Work

_API = "https://graphql.anilist.co"

# Roles whose name contains "director" but which are NOT the show's director.
_DIRECTOR_ROLE_EXCLUDE = (
    "animation", "sound", "art", "episode", "assistant",
    "photography", "technical", "recording",
)

# Manga writer/author roles. Substring match keeps "Story", "Story & Art" and
# "Original Creator"/"Original Story"; the pure "Art" credit (artist) is dropped.
_WRITER_ROLE_INCLUDE = ("story", "original creator", "original story")


def _post(query: str, variables: dict) -> dict | None:
    """POST a GraphQL query; return the ``data`` object or None on failure."""
    try:
        resp = requests.post(
            _API,
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=12,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _paginate_edges(query: str, base_vars: dict, extract, max_pages: int = 12) -> list:
    """Page through an AniList connection and return all its edges.

    ``extract(data)`` returns the connection dict (``{pageInfo, edges}``) for one
    page, or None. Stops at the last page or ``max_pages``, whichever comes
    first. Prolific staff/studios have many 50-edge pages of credits, and
    staffMedia mixes every role — so a director's older *directed* works only
    surface once we read past the recent (and non-director) credits.
    """
    edges: list = []
    page = 1
    while page <= max_pages:
        data = _post(query, {**base_vars, "page": page})
        if not data:
            break
        conn = extract(data)
        if not conn:
            break
        edges.extend(conn.get("edges") or [])
        if not (conn.get("pageInfo") or {}).get("hasNextPage"):
            break
        page += 1
    return edges


def _is_director_role(role: str) -> bool:
    r = (role or "").lower()
    if "director" not in r:
        return False
    return not any(bad in r for bad in _DIRECTOR_ROLE_EXCLUDE)


def _is_writer_role(role: str) -> bool:
    r = (role or "").lower()
    return any(good in r for good in _WRITER_ROLE_INCLUDE)


def _node_to_work(node: dict, role: str = "") -> Work:
    """Build a Work from a media node, using romaji as primary + english as alt."""
    title = node.get("title") or {}
    romaji = title.get("romaji")
    english = title.get("english")
    primary = romaji or english or "Unknown"

    alts: list[str] = []
    for cand in (english, romaji):
        if cand and cand != primary and cand not in alts:
            alts.append(cand)

    year = (node.get("startDate") or {}).get("year")
    fmt = node.get("format") or ""
    sub_bits = [str(year)] if year else []
    if fmt:
        sub_bits.append(fmt)

    return Work(
        title=primary,
        alt_titles=tuple(alts),
        year=year,
        subtitle=" · ".join(sub_bits),
        role=role,
    )


# --- Director ---------------------------------------------------------------

_STAFF_SEARCH_Q = """
query ($search: String) {
  Page(perPage: 10) {
    staff(search: $search) {
      id
      name { full native }
      primaryOccupations
      staffMedia(perPage: 4, sort: POPULARITY_DESC) {
        edges { node { title { romaji english } } }
      }
    }
  }
}
"""

_STAFF_MEDIA_Q = """
query ($id: Int, $page: Int, $type: MediaType) {
  Staff(id: $id) {
    staffMedia(type: $type, page: $page, perPage: 50, sort: START_DATE_DESC) {
      pageInfo { hasNextPage }
      edges {
        staffRole
        node { id title { romaji english native } startDate { year } format }
      }
    }
  }
}
"""


def staff_search(name: str) -> "list[Entity] | None":
    """Resolve a person name to candidate staff entities (for disambiguation).

    Returns None when AniList can't be reached (caller shows "service
    unavailable"); [] when there's genuinely no matching staff.
    """
    data = _post(_STAFF_SEARCH_Q, {"search": name})
    if data is None:
        return None
    out: list[Entity] = []
    for staff in (data.get("Page") or {}).get("staff") or []:
        nm = staff.get("name") or {}
        full = nm.get("full") or nm.get("native") or "Unknown"
        occ = ", ".join((staff.get("primaryOccupations") or [])[:2])
        known: list[str] = []
        # A person often holds several roles on one title (director + writer + …),
        # which shows up as duplicate edges — dedupe so the hint lists 3 distinct.
        for edge in (staff.get("staffMedia") or {}).get("edges") or []:
            t = (edge.get("node") or {}).get("title") or {}
            tt = t.get("romaji") or t.get("english")
            if tt and tt not in known:
                known.append(tt)
            if len(known) >= 3:
                break
        bits = []
        if occ:
            bits.append(occ)
        if known:
            bits.append("known for " + ", ".join(known))
        out.append(Entity(id=str(staff.get("id")), name=full, detail=" · ".join(bits)))
    return out


def _staff_works(entity: Entity, media_type: str, role_ok) -> list[Work]:
    """List a person's media of ``media_type`` (ANIME/MANGA) whose role passes
    ``role_ok``. Paginated and deduped by media id."""
    edges = _paginate_edges(
        _STAFF_MEDIA_Q, {"id": int(entity.id), "type": media_type},
        lambda d: (d.get("Staff") or {}).get("staffMedia"),
    )
    seen: set = set()
    works: list[Work] = []
    for edge in edges:
        role = edge.get("staffRole") or ""
        if not role_ok(role):
            continue
        node = edge.get("node") or {}
        nid = node.get("id")
        if nid in seen:
            continue
        seen.add(nid)
        works.append(_node_to_work(node, role))
    return works


def director_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    """List a person's anime where they hold a show-director role.

    AniList facets fetch the whole (internally capped) filmography eagerly, so
    there's never a second page — returns ``(works, has_more=False)``.
    """
    if page != 1:
        return [], False
    return _staff_works(entity, "ANIME", _is_director_role), False


def manga_writer_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    """List a person's manga where they're the writer/author (Story / Story & Art
    / Original Creator). Eager, single page — returns ``(works, False)``."""
    if page != 1:
        return [], False
    return _staff_works(entity, "MANGA", _is_writer_role), False


# --- Studio -----------------------------------------------------------------

_STUDIO_SEARCH_Q = """
query ($search: String) {
  Page(perPage: 10) {
    studios(search: $search) {
      id
      name
      isAnimationStudio
      media(perPage: 4, sort: POPULARITY_DESC) {
        nodes { title { romaji english } }
      }
    }
  }
}
"""

_STUDIO_MEDIA_Q = """
query ($id: Int, $page: Int) {
  Studio(id: $id) {
    media(page: $page, perPage: 50, sort: START_DATE_DESC) {
      pageInfo { hasNextPage }
      edges {
        isMainStudio
        node { id title { romaji english native } startDate { year } format }
      }
    }
  }
}
"""


def studio_search(name: str) -> "list[Entity] | None":
    """Resolve a studio name to candidate studio entities (for disambiguation).

    Returns None when AniList can't be reached; [] when no studio matches.
    """
    data = _post(_STUDIO_SEARCH_Q, {"search": name})
    if data is None:
        return None
    out: list[Entity] = []
    for st in (data.get("Page") or {}).get("studios") or []:
        kind = "Animation studio" if st.get("isAnimationStudio") else "Studio"
        known: list[str] = []
        for node in (st.get("media") or {}).get("nodes") or []:
            t = node.get("title") or {}
            tt = t.get("romaji") or t.get("english")
            if tt and tt not in known:
                known.append(tt)
            if len(known) >= 3:
                break
        detail = kind + (" · known for " + ", ".join(known) if known else "")
        out.append(Entity(id=str(st.get("id")), name=st.get("name") or "Unknown", detail=detail))
    return out


def studio_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    """List a studio's anime (main-studio credits preferred). Eager, single page
    — returns ``(works, has_more=False)``."""
    if page != 1:
        return [], False
    edges = _paginate_edges(
        _STUDIO_MEDIA_Q, {"id": int(entity.id)},
        lambda d: (d.get("Studio") or {}).get("media"),
    )
    # Prefer titles where this studio was the main animator; fall back to all
    # credits if none are flagged main (keeps small/young studios usable).
    main = [e for e in edges if e.get("isMainStudio")]
    use = main or edges
    seen: set = set()
    works: list[Work] = []
    for edge in use:
        node = edge.get("node") or {}
        nid = node.get("id")
        if nid in seen:
            continue
        seen.add(nid)
        works.append(_node_to_work(node))
    return works, False
