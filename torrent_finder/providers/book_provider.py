"""Book provider — Libgen direct downloads plus public torrent trackers.

Libgen (anonymous, no login — see ``libgen.py``) is the primary engine;
Apibay covers the TPB E-books and Audio books categories for torrent
releases; SolidTorrents' eBook category is available opt-in. Every default
engine works without credentials.
"""

from torrent_finder import libgen
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.resolvers import CreatorFacet, openlibrary
from torrent_finder.search_result import SearchResult


class BookProvider(BaseProvider):
    name = "Books"
    slug = "books"
    cli_aliases = ("book",)
    icon = "📖"
    search_note = "Books — Libgen (direct download, no login) + public torrent trackers."
    categories = [601, 102]  # TPB E-books + Audio books
    solidtorrents_category = "eBook"

    # Direct downloads / document torrents — no video features apply, but the
    # file picker does: Apibay book torrents are often bundles ("500 EPUBs",
    # audiobook chapter folders) worth cherry-picking via aria2.
    supports_subtitles = False
    supports_episode_picker = True
    supports_streaming = False

    presets = [
        FilterPreset("EPUB", FilterConfig(include_keywords=["epub"])),
        FilterPreset("PDF", FilterConfig(include_keywords=["pdf"])),
        FilterPreset("Kindle (MOBI/AZW3)", FilterConfig(include_keywords=["mobi", "azw3", "azw"])),
        FilterPreset("Audiobook", FilterConfig(include_keywords=["audiobook", "m4b", "mp3"])),
        FilterPreset("English", FilterConfig(include_keywords=["english"])),
    ]

    # Search by creator. OpenLibrary is keyless; works come back ordered by
    # edition count so an author's known books surface first in the picker.
    creator_facets = [
        CreatorFacet(
            key="author", label="Author", icon="📝",
            search_entities=openlibrary.author_search,
            list_works=openlibrary.author_works,
            note="Find an author's books via OpenLibrary, then search each title.",
        ),
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

    def _sort_results(self, results: list[SearchResult]) -> list[SearchResult]:
        """Libgen rows first (site relevance order), then torrents by seeders.

        The default seeders-descending sort would bury every Libgen row
        (seeders=0, no swarm) under even single-seeder torrent junk.
        """
        direct = [r for r in results if r.source == "Libgen"]
        torrents = [r for r in results if r.source != "Libgen"]
        torrents.sort(key=lambda x: x.seeders, reverse=True)
        return direct + torrents
