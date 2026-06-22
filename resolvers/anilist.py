"""AniList GraphQL resolver — anime director + studio lookups.

Keyless public API (https://anilist.co/graphiql). Each function fails soft to an
empty list on any network/parse error, matching the provider search backends.

Roles come back as free-text strings on the staff↔media edge ("Director",
"Chief Director", "Animation Director", …). We keep only the *show* director
roles and drop the many "<thing> Director" roles that aren't (animation, sound,
art, episode, …).
"""

import requests

from resolvers.types import Entity, Work

_API = "https://graphql.anilist.co"

# Roles whose name contains "director" but which are NOT the show's director.
_DIRECTOR_ROLE_EXCLUDE = (
    "animation", "sound", "art", "episode", "assistant",
    "photography", "technical", "recording",
)


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


def _is_director_role(role: str) -> bool:
    r = (role or "").lower()
    if "director" not in r:
        return False
    return not any(bad in r for bad in _DIRECTOR_ROLE_EXCLUDE)


def _node_to_work(node: dict) -> Work:
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
query ($id: Int) {
  Staff(id: $id) {
    staffMedia(type: ANIME, perPage: 50, sort: START_DATE_DESC) {
      edges {
        staffRole
        node { id title { romaji english native } startDate { year } format }
      }
    }
  }
}
"""


def staff_search(name: str) -> list[Entity]:
    """Resolve a person name to candidate staff entities (for disambiguation)."""
    data = _post(_STAFF_SEARCH_Q, {"search": name})
    if not data:
        return []
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


def director_works(entity: Entity) -> list[Work]:
    """List a person's anime where they hold a show-director role."""
    data = _post(_STAFF_MEDIA_Q, {"id": int(entity.id)})
    if not data:
        return []
    edges = ((data.get("Staff") or {}).get("staffMedia") or {}).get("edges") or []
    seen: set = set()
    works: list[Work] = []
    for edge in edges:
        if not _is_director_role(edge.get("staffRole")):
            continue
        node = edge.get("node") or {}
        nid = node.get("id")
        if nid in seen:
            continue
        seen.add(nid)
        works.append(_node_to_work(node))
    return works


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
query ($id: Int) {
  Studio(id: $id) {
    media(perPage: 50, sort: START_DATE_DESC) {
      edges {
        isMainStudio
        node { id title { romaji english native } startDate { year } format }
      }
    }
  }
}
"""


def studio_search(name: str) -> list[Entity]:
    """Resolve a studio name to candidate studio entities (for disambiguation)."""
    data = _post(_STUDIO_SEARCH_Q, {"search": name})
    if not data:
        return []
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


def studio_works(entity: Entity) -> list[Work]:
    """List a studio's anime (main-studio credits preferred)."""
    data = _post(_STUDIO_MEDIA_Q, {"id": int(entity.id)})
    if not data:
        return []
    edges = ((data.get("Studio") or {}).get("media") or {}).get("edges") or []
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
    return works
