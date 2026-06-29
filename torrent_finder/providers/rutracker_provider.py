"""RuTracker provider — credentialed search of rutracker.org (login + scrape).

A general tracker (great for software, audio, ebooks, rare content). It needs a
RuTracker login; without one it returns nothing and ``search_note`` points the
user at the credentials menu. Search results carry the topic id as a placeholder
``info_hash`` — main.py resolves the real magnet from the topic page when a
result is selected (see rutracker.resolve_info_hash).
"""

from torrent_finder import rutracker
from torrent_finder.providers.base import BaseProvider, SearchEngine


class RuTrackerProvider(BaseProvider):
    name = "RuTracker"
    slug = "rutracker"
    icon = "🧲"
    categories = []  # not Apibay-based; the engine talks to rutracker.org directly
    search_note = "Needs a RuTracker login — add it under the credentials menu on the provider screen."

    supports_subtitles = False
    supports_streaming = False
    supports_episode_picker = False

    def _init_engines(self) -> list[SearchEngine]:
        return [SearchEngine("RuTracker", "🧲", self._search_rutracker, enabled=True)]

    def _search_rutracker(self, query: str) -> list[dict]:
        return rutracker.search(query)
