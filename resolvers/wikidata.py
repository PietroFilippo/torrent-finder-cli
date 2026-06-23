"""Wikidata resolver — keyless Movies & Series director + studio fallback.

Used when no TMDB key is configured (TMDB gives richer data when a key is set;
`resolvers/movies.py` does the dispatch). Queries the public Wikidata Query
Service (SPARQL, no key — but a descriptive User-Agent is required by policy).
Lower coverage/quality than TMDB, but needs no account.

Director = films/series whose director (P57) is the person.
Studio   = films whose production company (P272) is the company.
Both eager (one capped SPARQL query); the name search filters to real
directors/companies via FILTER EXISTS so it doesn't surface random same-named
items.
"""

import re

import requests

from resolvers.types import Entity, Work

_SPARQL = "https://query.wikidata.org/sparql"
_UA = "torrent-finder-cli/1.0 (creator search; https://github.com/PietroFilippo/movie-finder-cli)"
_WORKS_LIMIT = 300
_QID_RE = re.compile(r"Q\d+")

# mwapi EntitySearch finds candidates by name; FILTER EXISTS keeps only those
# that actually directed a film (P57) / produced one (P272).
_SEARCH_Q = """
SELECT ?item ?itemLabel ?desc WHERE {
  SERVICE wikibase:mwapi {
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam mwapi:search "__SEARCH__" .
    bd:serviceParam mwapi:language "en" .
    ?item wikibase:apiOutputItem mwapi:item .
  }
  FILTER EXISTS { ?f wdt:__PROP__ ?item . }
  ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel) = "en")
  OPTIONAL { ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }
}
LIMIT 10
"""

_WORKS_Q = """
SELECT ?film ?label (MIN(?yr) AS ?year) WHERE {
  ?film wdt:__PROP__ wd:__QID__ .
  ?film rdfs:label ?label . FILTER(LANG(?label) = "en")
  OPTIONAL { ?film wdt:P577 ?date . BIND(YEAR(?date) AS ?yr) }
}
GROUP BY ?film ?label
ORDER BY DESC(?year)
LIMIT __LIMIT__
"""


def _sparql(query: str) -> dict | None:
    try:
        resp = requests.get(
            _SPARQL,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json", "User-Agent": _UA},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _search(name: str, prop: str) -> "list[Entity] | None":
    data = _sparql(_SEARCH_Q.replace("__SEARCH__", _esc(name)).replace("__PROP__", prop))
    if data is None:
        return None
    out: list[Entity] = []
    seen: set = set()
    for b in (data.get("results") or {}).get("bindings") or []:
        qid = (b.get("item") or {}).get("value", "").rsplit("/", 1)[-1]
        if not qid or qid in seen:
            continue
        seen.add(qid)
        out.append(Entity(
            id=qid,
            name=(b.get("itemLabel") or {}).get("value") or qid,
            detail=(b.get("desc") or {}).get("value", ""),
        ))
    return out


def _works(entity: Entity, prop: str) -> "tuple[list[Work], bool]":
    if not _QID_RE.fullmatch(entity.id or ""):
        return [], False
    query = (_WORKS_Q.replace("__PROP__", prop)
             .replace("__QID__", entity.id)
             .replace("__LIMIT__", str(_WORKS_LIMIT)))
    data = _sparql(query)
    if data is None:
        return [], False
    works: list[Work] = []
    for b in (data.get("results") or {}).get("bindings") or []:
        label = (b.get("label") or {}).get("value")
        if not label:
            continue
        yr = (b.get("year") or {}).get("value", "")
        year = int(yr) if yr.lstrip("-").isdigit() else None
        works.append(Work(title=label, alt_titles=(), year=year,
                         subtitle=str(year) if year else ""))
    return works, False


# --- Facet entry points (mirror the tmdb resolver's signatures) -------------

def person_search(name: str) -> "list[Entity] | None":
    return _search(name, "P57")


def director_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    if page != 1:
        return [], False
    return _works(entity, "P57")


def company_search(name: str) -> "list[Entity] | None":
    return _search(name, "P272")


def company_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    if page != 1:
        return [], False
    return _works(entity, "P272")


# --- Games (P178 developer, P123 publisher) — same generic helpers ----------

def developer_search(name: str) -> "list[Entity] | None":
    return _search(name, "P178")


def developer_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    if page != 1:
        return [], False
    return _works(entity, "P178")


def publisher_search(name: str) -> "list[Entity] | None":
    return _search(name, "P123")


def publisher_works(entity: Entity, page: int = 1) -> "tuple[list[Work], bool]":
    if page != 1:
        return [], False
    return _works(entity, "P123")
