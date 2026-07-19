"""Manga torrent provider — searches Nyaa Literature plus Apibay Comics."""

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult
from torrent_finder.resolvers import CreatorFacet, anilist, jikan


class MangaProvider(BaseProvider):
    # Shown as "General" under the Manga group; slug stays "manga" so the -t
    # flag and existing history/stats keys keep working.
    name = "General"
    slug = "manga"
    icon = "📚"
    search_note = "Manga from public trackers (Nyaa Literature + Apibay Comics)."
    categories = [602]  # Apibay/TPB Comics
    # Nyaa Literature + Books / Comics.
    knaben_categories = (6_006_000, 9_002_000)
    nyaa_category = "3_1"  # Literature - English-translated (default Nyaa engine)

    supports_subtitles = False
    supports_episode_picker = True  # volume/chapter batches → aria2 file-selection
    supports_streaming = False  # manga isn't video — hide the Stream to VLC section

    presets = [
        FilterPreset("Complete / Full", FilterConfig(include_keywords=["complete", "full series"])),
        FilterPreset("By Volume", FilterConfig(include_keywords=["volume", "vol."])),
        FilterPreset("Color", FilterConfig(include_keywords=["color", "colour"])),
        FilterPreset("Official / Digital", FilterConfig(include_keywords=["official", "digital"])),
        FilterPreset("Official Publishers", FilterConfig(include_keywords=[
            "viz", "kodansha", "yen press", "seven seas", "square enix", "j-novel",
        ])),
        FilterPreset("Exclude Light Novels", FilterConfig(exclude_keywords=["light novel"])),
    ]

    # Search by creator. AniList resolves the writer/author to their manga; Jikan
    # resolves a Japanese serialization magazine to the manga it ran. Each picked
    # title is then searched on the torrent backends. Both keyless.
    creator_facets = [
        CreatorFacet(
            key="writer", label="Writer", icon="📝",
            search_entities=anilist.staff_search,
            list_works=anilist.manga_writer_works,
            note="Find a writer's manga via AniList, then search each title.",
        ),
        CreatorFacet(
            key="magazine", label="Magazine", icon="📰",
            search_entities=jikan.magazine_search,
            list_works=jikan.magazine_works,
            note="Find a magazine's serialized manga via MyAnimeList, then search each title.",
        ),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Nyaa EN + APIBay on, category-scoped Knaben auto, Raw Nyaa off."""
        return [
            SearchEngine("Nyaa (EN)", "🍙", self._search_nyaa, enabled=True),
            SearchEngine("Nyaa (Raw)", "🗾", self._search_nyaa_raw, enabled=False),
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine(
                "Knaben", "🧭", self._search_knaben,
                enabled=False, emergency_fallback=True,
            ),
        ]

    def _search_nyaa_raw(self, query: str) -> list[SearchResult]:
        """Nyaa Literature - Raw (Japanese), c=3_2. Off by default."""
        return self._search_nyaa_in(query, "3_2")
