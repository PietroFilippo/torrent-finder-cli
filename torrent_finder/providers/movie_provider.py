"""Movie torrent provider — searches video/movie categories."""

from typing import Iterator

import requests

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult
from torrent_finder.resolvers import CreatorFacet, movies


_YTS_API_URLS = (
    "https://movies-api.accel.li/api/v2/list_movies.json",
    "https://yts.gg/api/v2/list_movies.json",
)


def _fetch_yts_movies(query: str) -> list[dict]:
    for api_url in _YTS_API_URLS:
        try:
            response = requests.get(
                api_url,
                params={"query_term": query, "limit": 50},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            movies = data.get("movies") if isinstance(data, dict) else None
            if (
                isinstance(payload, dict)
                and payload.get("status") == "ok"
                and isinstance(movies, list)
            ):
                return movies
        except (requests.RequestException, ValueError):
            continue
    return []


class MovieProvider(BaseProvider):
    name = "Movies & Series"
    slug = "movies"
    cli_aliases = ("movie",)
    icon = "🎬"
    # Movies, DVD movies, TV, HD movies/TV, and 3D movies.
    categories = [201, 202, 205, 207, 208, 209]
    # Apibay's cat=0 search can falsely return no results for movie titles.
    # Restore the category requests used before commit 5d895da9 as fallback.
    apibay_fallback_categories = (201, 207)
    solidtorrents_category = "Movie"
    nyaa_category = "4_1"  # Live Action - English-translated (J-dramas, Asian films/TV)

    supports_subtitles = True
    supports_episode_picker = True

    presets = [
        FilterPreset("720p", FilterConfig(quality=["720p"])),
        FilterPreset("1080p", FilterConfig(quality=["1080p"])),
        FilterPreset("4K / 2160p", FilterConfig(quality=["2160p", "4k"])),
        FilterPreset("With Subtitles", FilterConfig(include_keywords=["sub", "srt"])),
        FilterPreset("x265 / HEVC", FilterConfig(include_keywords=["x265", "hevc"])),
        FilterPreset("HDR", FilterConfig(include_keywords=["hdr", "dolby vision", "dv"])),
        FilterPreset("Remux", FilterConfig(include_keywords=["remux"])),
        FilterPreset("Trusted Uploaders", FilterConfig(include_keywords=[
            "yify", "yts", "rarbg", "fgt", "sparks", "evo",
            "qxr", "tgx", "anoxmous", "etrg", "mkvcage", "galaxy",
        ])),
    ]

    # Search by creator. Always available: uses the keyless Wikidata fallback by
    # default, and richer TMDB data when a TMDB_API_KEY is configured (see
    # resolvers/movies.py). Director = films + TV; Studio = a company's films.
    creator_facets = [
        CreatorFacet(
            key="director", label="Director", icon="🎬",
            search_entities=movies.director_search,
            list_works=movies.director_works,
            note="Find a director's films & shows, then search each title. "
                 "Add a TMDB key (Credentials) for richer results.",
        ),
        CreatorFacet(
            key="studio", label="Studio", icon="🏢",
            search_entities=movies.studio_search,
            list_works=movies.studio_works,
            note="Find a studio/company's films, then search each title. "
                 "Add a TMDB key (Credentials) for richer results.",
        ),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Movies default to Apibay + Nyaa; SolidTorrents and YTS are opt-in."""
        return [
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine("SolidTorrents", "🔗", self._search_solidtorrents, enabled=False),
            SearchEngine("YTS", "🎥", self._search_yts, enabled=False),
            SearchEngine("Nyaa", "🍙", self._search_nyaa, enabled=True),
        ]

    def _search_yts(self, query: str) -> list[SearchResult]:
        """Search the current YTS API, falling back to its prior API host."""
        results: list[SearchResult] = []
        for movie in _fetch_yts_movies(query):
            title = movie.get("title_long", "Unknown")
            for torrent in movie.get("torrents") or []:
                quality = torrent.get("quality", "")
                torrent_type = torrent.get("type", "")
                results.append(SearchResult(
                    name=f"{title} [{quality} {torrent_type}]",
                    info_hash=torrent.get("hash", "").lower(),
                    seeders=torrent.get("seeds", 0),
                    leechers=torrent.get("peers", 0),
                    size=torrent.get("size_bytes", 0),
                    source="YTS",
                    page_url=movie.get("url", ""),
                ))
        return results

    def _apibay_retry_queries(self, query: str) -> Iterator[str]:
        yield from super()._apibay_retry_queries(query)

        query_key = " ".join(query.casefold().split())
        for movie in _fetch_yts_movies(query):
            title = str(movie.get("title", "")).strip()
            if " ".join(title.casefold().split()) != query_key:
                continue
            year = movie.get("year")
            if year:
                yield f"{query.strip()} {year}"
            return
