"""Catalog identification and alternate names, separate from release search."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
import unicodedata

from torrent_finder import credentials
from torrent_finder.resolvers import anilist, tmdb, igdb, openlibrary
from torrent_finder.resolvers.types import Work
from torrent_finder.search_errors import SearchError

MAX_ALIASES = 6
MAX_CATALOG_PAGES = 3
PAGE_SIZE = 12


def distinct_names(names):
    out, seen = [], set()
    for value in names:
        if not isinstance(value, str):
            continue
        value = " ".join(unicodedata.normalize("NFKC", value).split())
        if value and value.casefold() not in seen:
            out.append(value)
            seen.add(value.casefold())
    return out


@dataclass(frozen=True)
class TitleMatch:
    catalog: str
    id: str
    work: Work
    note: str = ""


@dataclass(frozen=True)
class Catalog:
    key: str
    label: str
    slugs: tuple[str, ...]
    credential_keys: tuple[str, ...] = ()

    def missing_credentials(self):
        return tuple(k for k in self.credential_keys if not credentials.get_credential(k))


CATALOGS = (
    Catalog("anime", "Anime · AniList", ("anime", "rutracker")),
    Catalog("manga", "Manga · AniList", ("manga", "madokami", "rutracker")),
    Catalog("movies", "Movies / Series · TMDB", ("movies", "rutracker"), ("TMDB_API_KEY",)),
    Catalog("games", "Games · IGDB", ("games", "fitgirl", "online-fix", "rutracker"), ("IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET")),
    Catalog("books", "Books · Open Library", ("books", "rutracker")),
)


def catalogs_for(provider):
    slugs = ({p.slug for p in provider.children if p.slug in provider.selected_slugs}
             if getattr(provider, "is_combined", False) else {provider.slug})
    return [catalog for catalog in CATALOGS if slugs.intersection(catalog.slugs)]


_MEDIA_SEARCH = """
query ($search: String, $type: MediaType, $page: Int) {
  Page(page: $page, perPage: 12) {
    pageInfo { hasNextPage }
    media(search: $search, type: $type, sort: SEARCH_MATCH, isAdult: false) {
      id title { romaji english native } synonyms startDate { year } format
    }
  }
}
"""


def _with_names(work, names):
    names = distinct_names((work.title, *work.alt_titles, *names))
    return replace(work, title=names[0], alt_titles=tuple(names[1:40]))


def search_titles(catalog, query, page=1):
    """One user-requested page; unavailable catalogs are never an empty match."""
    if page < 1 or page > MAX_CATALOG_PAGES:
        raise ValueError("Catalog page outside the bounded range")
    missing = catalog.missing_credentials()
    if missing:
        raise SearchError("Configure " + ", ".join(missing) + " in Credentials to use this catalog.")
    key = catalog.key
    if key in {"anime", "manga"}:
        data = anilist._post(_MEDIA_SEARCH, {"search": query, "type": key.upper(), "page": page})
        if data is None or not isinstance(data.get("Page"), dict):
            raise SearchError("AniList is unavailable or rejected this request. Try again later.")
        result = data["Page"]
        matches = []
        for node in result.get("media") or []:
            if not node.get("id"):
                continue
            work = _with_names(anilist._node_to_work(node),
                               [(node.get("title") or {}).get("native"), *(node.get("synonyms") or [])])
            matches.append(TitleMatch(key, str(node["id"]), work))
        return matches, bool((result.get("pageInfo") or {}).get("hasNextPage")) and page < MAX_CATALOG_PAGES
    if key == "movies":
        data = tmdb._get("/search/multi", {"query": query, "page": page, "include_adult": "false"})
        if data is None:
            raise SearchError("TMDB request failed. Check Credentials or try again later.")
        matches = [TitleMatch(key, f"{row['media_type']}/{row['id']}", tmdb._credit_to_work(row))
                   for row in data.get("results", []) if row.get("media_type") in {"movie", "tv"} and row.get("id")]
        return matches, page < min(MAX_CATALOG_PAGES, data.get("total_pages", 1))
    if key == "games":
        data = igdb._post("games", f'search "{igdb._esc(query)}"; fields name,alternative_names.name,first_release_date,platforms.name,version_title; limit {PAGE_SIZE}; offset {(page - 1) * PAGE_SIZE};')
        if data is None:
            raise SearchError("IGDB request failed. Check Credentials or try again later.")
        matches = []
        for row in data:
            if not row.get("id") or not row.get("name"):
                continue
            stamp = row.get("first_release_date")
            year = datetime.fromtimestamp(stamp, timezone.utc).year if isinstance(stamp, (int, float)) else None
            detail = " · ".join(filter(None, [str(year or ""), row.get("version_title", ""),
                                             ", ".join(p.get("name", "") for p in row.get("platforms", []))]))
            work = _with_names(Work(row["name"], year=year, subtitle=detail),
                               [a.get("name") for a in row.get("alternative_names", [])])
            matches.append(TitleMatch(key, str(row["id"]), work))
        return matches, len(data) == PAGE_SIZE and page < MAX_CATALOG_PAGES
    if key == "books":
        data = openlibrary._get("/search.json", {"title": query, "page": page, "limit": PAGE_SIZE,
            "fields": "key,title,first_publish_year,author_name"})
        if data is None:
            raise SearchError("Open Library request failed. Try again later.")
        matches = []
        for row in data.get("docs", []):
            if not re.fullmatch(r"/works/OL\d+W", row.get("key", "")) or not row.get("title"):
                continue
            year = row.get("first_publish_year")
            detail = " · ".join(filter(None, [str(year or ""), ", ".join(row.get("author_name", [])[:3])]))
            matches.append(TitleMatch(key, row["key"], Work(row["title"], year=year, subtitle=detail,
                                                            authors=tuple(row.get("author_name", [])[:3]))))
        total = data.get("numFound", data.get("num_found", 0))
        return matches, page * PAGE_SIZE < total and page < MAX_CATALOG_PAGES
    raise ValueError("Unknown title catalog")


def resolve_names(match):
    """Fetch extra names only for the chosen work, never all candidates."""
    if match.catalog == "movies":
        data = tmdb._get(f"/{match.id}/alternative_titles")
        if data is None:
            return replace(match, note="Alternative titles could not be fetched; primary/original names are still available.")
        rows = data.get("titles", data.get("results", []))
        # Keep Portuguese/English names accessible ahead of dozens of others.
        rows = sorted(rows, key=lambda r: r.get("iso_3166_1") not in {"BR", "PT", "US", "GB"})
        return replace(match, work=_with_names(match.work, [r.get("title") for r in rows]))
    if match.catalog == "books":
        data = openlibrary._get(match.id + ".json")
        if data is None:
            return replace(match, note="Additional names could not be fetched; the catalog title is still available.")
        return replace(match, work=_with_names(match.work, data.get("alternative_titles") or []))
    return match
