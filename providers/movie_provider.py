"""Movie torrent provider — searches video/movie categories."""

from typing import Callable

import requests

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider


class MovieProvider(BaseProvider):
    name = "Movies"
    icon = "🎬"
    categories = [201, 207]  # Movies, HD Movies
    solidtorrents_category = "Movie"

    presets = [
        FilterPreset("HD Only", FilterConfig(quality=["1080p", "bluray"])),
        FilterPreset("Small Size", FilterConfig(quality=["x265", "hevc"])),
    ]

    def search_engines(self) -> list[Callable[[str], list[dict]]]:
        """Return a list of engine search methods to run concurrently."""
        return [self._search_apibay, self._search_solidtorrents, self._search_yts]

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
