"""Book provider — Libgen direct downloads plus public torrent trackers.

Libgen (anonymous, no login — see ``libgen.py``) is the primary engine;
Apibay covers the TPB E-books and Audio books categories for torrent
releases; SolidTorrents' eBook category is available opt-in. Every default
engine works without credentials.
"""

from torrent_finder import libgen
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult


class BookProvider(BaseProvider):
    name = "Books"
    slug = "books"
    cli_aliases = ("book",)
    icon = "📖"
    search_note = "Books — Libgen (direct download, no login) + public torrent trackers."
    categories = [601, 102]  # TPB E-books + Audio books
    solidtorrents_category = "eBook"

    # Direct downloads / document torrents — no video features apply.
    supports_subtitles = False
    supports_episode_picker = False
    supports_streaming = False

    presets = [
        FilterPreset("EPUB", FilterConfig(include_keywords=["epub"])),
        FilterPreset("PDF", FilterConfig(include_keywords=["pdf"])),
        FilterPreset("Kindle (MOBI/AZW3)", FilterConfig(include_keywords=["mobi", "azw3", "azw"])),
        FilterPreset("Audiobook", FilterConfig(include_keywords=["audiobook", "m4b", "mp3"])),
        FilterPreset("English", FilterConfig(include_keywords=["english"])),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Libgen + Apibay on by default (both anonymous); SolidTorrents opt-in."""
        return [
            SearchEngine("Libgen", "📖", self._search_libgen, enabled=True),
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine("SolidTorrents", "🔗", self._search_solidtorrents, enabled=False),
        ]

    def _search_libgen(self, query: str) -> list[SearchResult]:
        return libgen.search(query)
