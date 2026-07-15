"""Movie torrent provider — searches video/movie categories."""

import requests

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult
from torrent_finder.resolvers import CreatorFacet, movies


class MovieProvider(BaseProvider):
    name = "Movies & Series"
    slug = "movies"
    cli_aliases = ("movie",)
    icon = "🎬"
    categories = [201, 207]  # Movies, HD Movies
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
        """Search YTS API for the query."""
        results = []
        try:
            response = requests.get(
                "https://yts.mx/api/v2/list_movies.json",
                params={"query_term": query, "limit": 50},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            movies = data.get("data", {}).get("movies", [])
            for movie in movies:
                title = movie.get("title_long", "Unknown")
                for t in movie.get("torrents", []):
                    quality = t.get("quality", "")
                    _type = t.get("type", "")
                    name = f"{title} [{quality} {_type}]"
                    results.append(SearchResult(
                        name=name,
                        info_hash=t.get("hash", "").lower(),
                        seeders=t.get("seeds", 0),
                        leechers=t.get("peers", 0),
                        size=t.get("size_bytes", 0),
                        source="YTS",
                        page_url=movie.get("url", ""),
                    ))
        except Exception:
            pass
        return results
