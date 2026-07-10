"""Madokami provider — credentialed search of manga.madokami.al (Basic auth).

A private, curated manga library — direct-download archives, not torrents. It
needs a Madokami login (HTTP Basic auth); without one it returns nothing and
``search_note`` points the user at the credentials menu. Results carry the
library path as a placeholder ``info_hash`` — selecting one downloads the
archive(s) directly (a directory hit opens a volume picker first) instead of
entering the magnet pipeline (see main.py's Madokami branch).
"""

from torrent_finder import madokami
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult


class MadokamiProvider(BaseProvider):
    name = "Madokami"
    slug = "madokami"
    icon = "📕"
    categories = []  # not Apibay-based; the engine talks to manga.madokami.al directly
    search_note = "Needs a Madokami login (Credentials menu). Picks download directly — no torrent client involved."

    # Direct-download archives behind Basic auth — no swarm, no video, so none
    # of the magnet/streaming features apply.
    supports_subtitles = False
    supports_streaming = False
    supports_episode_picker = False

    def _init_engines(self) -> list[SearchEngine]:
        return [SearchEngine("Madokami", "📕", self._search_madokami, enabled=True)]

    def _search_madokami(self, query: str) -> list[SearchResult]:
        return madokami.search(query)
