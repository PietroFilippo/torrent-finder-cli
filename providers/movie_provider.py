"""Movie torrent provider — searches video/movie categories."""

import requests

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider, SearchEngine


class MovieProvider(BaseProvider):
    name = "Movies & Series"
    icon = "🎬"
    categories = [201, 207]  # Movies, HD Movies
    solidtorrents_category = "Movie"

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

    def _init_engines(self) -> list[SearchEngine]:
        """Movies use Apibay, SolidTorrents, and YTS."""
        return [
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine("SolidTorrents", "🔗", self._search_solidtorrents, enabled=True),
            SearchEngine("YTS", "🎥", self._search_yts, enabled=True),
        ]

    def _search_yts(self, query: str) -> list[dict]:
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
                    results.append({
                        "name": name,
                        "info_hash": t.get("hash", "").lower(),
                        "seeders": str(t.get("seeds", 0)),
                        "leechers": str(t.get("peers", 0)),
                        "size": str(t.get("size_bytes", 0)),
                        "source": "YTS"
                    })
        except Exception:
            pass
        return results
