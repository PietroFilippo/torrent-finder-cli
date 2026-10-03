"""Catalog topics identify works; release-name keywords do not establish topics."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache
import re
import unicodedata
from urllib.parse import quote

from torrent_finder.resolvers import anilist, tmdb, igdb, openlibrary
from torrent_finder.resolvers.titles import catalogs_for, TitleMatch, _with_names, distinct_names
from torrent_finder.resolvers.types import Work
from torrent_finder.search_errors import SearchError

MAX_TOPICS = 3
MAX_WORKS = 3
MAX_PAGES = 3
PAGE_SIZE = 12
MIN_TAG_RANK = 60


@dataclass(frozen=True)
class Topic:
    kind: str
    id: str
    name: str
    detail: str = ""


def discovery_catalogs(provider):
    out = []
    for catalog in catalogs_for(provider):
        if catalog.key == "movies":
            out.extend(replace(catalog, key=key, label=label) for key, label in
                       (("movie", "Movies · TMDB"), ("tv", "Series · TMDB")))
        else:
            out.append(catalog)
    return out


def scope_for(provider, catalog):
    if not getattr(provider, "is_combined", False):
        return provider
    from torrent_finder.providers.combined_provider import CombinedProvider
    snapshot = provider.snapshot()
    snapshot["selected"] = [slug for slug in snapshot["selected"] if slug in catalog.slugs]
    scoped = CombinedProvider(provider.templates)
    scoped.restore_history(snapshot)
    return scoped


def scope_label(provider):
    if not getattr(provider, "is_combined", False):
        return provider.name
    from torrent_finder.providers.combined_provider import provider_label
    return ", ".join(provider_label(p) for p in provider.children if p.slug in provider.selected_slugs)


def _check(catalog):
    missing = catalog.missing_credentials()
    if missing:
        raise SearchError("Configure " + ", ".join(missing) + " in Credentials to use this catalog.")


def _require(value, label):
    if value is None:
        raise SearchError(f"{label} could not be reached or rejected the request. Try again or check Credentials.")
    return value


def _rows(data, field, label):
    if not isinstance(data, dict) or not isinstance(data.get(field), list):
        raise SearchError(f"{label} returned an incomplete catalog response.")
    return data[field]


def _normal(text):
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text))


@lru_cache(maxsize=1)
def _anilist_topics():
    data = _require(anilist._post("{ GenreCollection MediaTagCollection { id name description isAdult } }", {}), "AniList")
    if not isinstance(data.get("GenreCollection"), list) or not isinstance(data.get("MediaTagCollection"), list):
        raise SearchError("AniList did not return its topic vocabulary.")
    return tuple([Topic("genre", name, name) for name in data["GenreCollection"]] +
                 [Topic("tag", str(row["id"]), row["name"], row.get("description") or "")
                  for row in data["MediaTagCollection"] if row.get("id") and row.get("name") and not row.get("isAdult")])


def find_topics(catalog, text):
    """Match one phrase to explicit catalog terms. No inferred genre fallback."""
    _check(catalog)
    text = " ".join(text.split())[:100]
    if not text:
        return []
    key = catalog.key
    if key in {"anime", "manga"}:
        tokens = _normal(text).split()
        matches = [t for t in _anilist_topics() if all(word in _normal(t.name + " " + t.detail) for word in tokens)]
        return sorted(matches, key=lambda t: (_normal(t.name) != _normal(text),
                      not all(word in _normal(t.name) for word in tokens), len(t.name)))[:30]
    if key in {"movie", "tv"}:
        genres = _require(tmdb._get(f"/genre/{key}/list"), "TMDB")
        keywords = _require(tmdb._get("/search/keyword", {"query": text, "page": 1}), "TMDB")
        return [Topic("genre", str(r["id"]), r["name"]) for r in _rows(genres, "genres", "TMDB")
                if _normal(text) in _normal(r["name"])] + [
                    Topic("keyword", str(r["id"]), r["name"]) for r in _rows(keywords, "results", "TMDB")[:20]]
    if key == "games":
        phrase = "co-operative" if _normal(text) in {"co op", "coop", "cooperative"} else text
        # One multiquery request respects IGDB's rate limit while checking all vocabularies.
        kinds = ("genres", "themes", "game_modes", "keywords")
        body = "\n".join(f'query {kind} "{kind}" {{ fields name; where name ~ *"{igdb._esc(phrase)}"*; limit 12; }};'
                         for kind in kinds)
        data = _require(igdb._post("multiquery", body), "IGDB")
        if {group.get("name") for group in data} != set(kinds) or any(not isinstance(g.get("result"), list) for g in data):
            raise SearchError("IGDB did not return all requested topic vocabularies.")
        return [Topic(group["name"], str(r["id"]), r["name"]) for group in data for r in group["result"]
                if r.get("id") and r.get("name")]
    if key == "books":
        slug = quote(text.casefold().replace(" ", "_"), safe="")
        data = _require(openlibrary._get(f"/subjects/{slug}.json", {"limit": 0}), "Open Library")
        if not isinstance(data.get("work_count"), int):
            raise SearchError("Open Library returned an incomplete subject response.")
        if not data.get("work_count"):
            return []
        name = data.get("name") or text
        return [Topic("subject", slug, name, f"{data['work_count']} catalog works; one subject per search.")]
    raise SearchError("Topic discovery is unavailable for this category.")


_DISCOVER = """
query ($type: MediaType, $genres: [String], $tags: [String], $page: Int) {
  Page(page: $page, perPage: 12) {
    pageInfo { hasNextPage }
    media(type: $type, genre_in: $genres, tag_in: $tags, minimumTagRank: 60, isAdult: false, sort: POPULARITY_DESC) {
      id title { romaji english native } synonyms startDate { year } format
      genres tags { name rank }
    }
  }
}
"""


def discover(catalog, topics, page=1):
    _check(catalog)
    if not 1 <= page <= MAX_PAGES or not 1 <= len(topics) <= (1 if catalog.key == "books" else MAX_TOPICS):
        raise ValueError("Discovery exceeds the topic/page limit")
    key = catalog.key
    allowed = ({"genre", "tag"} if key in {"anime", "manga"} else {"genre", "keyword"}
               if key in {"movie", "tv"} else {"genres", "themes", "game_modes", "keywords"}
               if key == "games" else {"subject"})
    if any(t.kind not in allowed for t in topics):
        raise ValueError("Topic does not belong to this catalog")
    evidence = "Catalog criteria (all): " + ", ".join(t.name for t in topics)
    if key in {"anime", "manga"}:
        data = _require(anilist._post(_DISCOVER, {"type": key.upper(), "page": page,
            "genres": [t.name for t in topics if t.kind == "genre"] or None,
            "tags": [t.name for t in topics if t.kind == "tag"] or None}), "AniList")
        if not isinstance(data.get("Page"), dict):
            raise SearchError("AniList returned an incomplete discovery response.")
        rows = _rows(data["Page"], "media", "AniList")
        matches = []
        for row in rows:
            tag_ranks = {t.get("name"): t.get("rank", 0) for t in row.get("tags", [])}
            if any((t.kind == "genre" and t.name not in row.get("genres", [])) or
                   (t.kind == "tag" and tag_ranks.get(t.name, 0) < MIN_TAG_RANK) for t in topics):
                continue
            names = row.get("title") or {}
            work = _with_names(anilist._node_to_work(row), [names.get("native"), *(row.get("synonyms") or [])])
            tags = ", ".join(f"{t['name']} ({t.get('rank', 0)}%)" for t in row.get("tags", [])
                             if t.get("name") in {x.name for x in topics})
            matches.append(TitleMatch(key, str(row["id"]), work, evidence + ("\nTag relevance: " + tags if tags else "")))
        more = bool((data["Page"].get("pageInfo") or {}).get("hasNextPage"))
    elif key in {"movie", "tv"}:
        params = {"page": page, "include_adult": "false", "sort_by": "popularity.desc"}
        for kind, field in (("genre", "with_genres"), ("keyword", "with_keywords")):
            ids = [str(int(t.id)) for t in topics if t.kind == kind]
            if ids:
                params[field] = ",".join(ids)  # TMDB comma means AND.
        data = _require(tmdb._get(f"/discover/{key}", params), "TMDB")
        matches = [TitleMatch("movies", f"{key}/{r['id']}", tmdb._credit_to_work(dict(r, media_type=key)), evidence)
                   for r in _rows(data, "results", "TMDB") if r.get("id")]
        more = page < data.get("total_pages", 1)
    elif key == "games":
        clauses = [f"{t.kind} = [{int(t.id)}]" for t in topics]
        data = _require(igdb._post("games", "fields name,first_release_date,alternative_names.name,platforms.name; "
            + "where " + " & ".join(clauses) + "; sort total_rating_count desc; "
            + f"limit {PAGE_SIZE}; offset {(page - 1) * PAGE_SIZE};"), "IGDB")
        matches = []
        for row in data:
            year = datetime.fromtimestamp(row["first_release_date"], timezone.utc).year if row.get("first_release_date") else None
            detail = " · ".join(filter(None, [str(year or ""), ", ".join(p.get("name", "") for p in row.get("platforms", []))]))
            work = _with_names(Work(row["name"], year=year, subtitle=detail), [a.get("name") for a in row.get("alternative_names", [])])
            matches.append(TitleMatch(key, str(row["id"]), work, evidence))
        more = len(data) == PAGE_SIZE
    elif key == "books":
        # ID is a percent-encoded subject path component, never a raw endpoint.
        if not re.fullmatch(r"[\w%\-.~]+", topics[0].id):
            raise ValueError("Invalid subject identifier")
        data = _require(openlibrary._get(f"/subjects/{topics[0].id}.json",
            {"limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE}), "Open Library")
        matches = []
        for row in _rows(data, "works", "Open Library"):
            year = row.get("first_publish_year")
            authors = ", ".join(a.get("name", "") for a in row.get("authors", [])[:3])
            work = Work(row["title"], year=year, subtitle=" · ".join(filter(None, [str(year or ""), authors])))
            matches.append(TitleMatch(key, row["key"], work, evidence))
        more = page * PAGE_SIZE < data.get("work_count", 0)
    else:
        raise SearchError("This category has no topic catalog.")
    return matches, more and page < MAX_PAGES


def query_plan(matches):
    if not 1 <= len(matches) <= MAX_WORKS:
        raise ValueError(f"Choose 1–{MAX_WORKS} works")
    queries, origins = [], {}
    for match in matches:
        for name in distinct_names([match.work.title, *match.work.alt_titles])[:2]:
            if name.casefold() not in {q.casefold() for q in queries}:
                queries.append(name)
                origins[name] = match.work.title
    return queries, origins
