"""Manga torrent provider — searches Nyaa Literature plus Apibay Comics."""

from torrent_finder.filters import FilterConfig, FilterPreset, strip_accents
from torrent_finder.language_tags import is_raw_release, manga_language_tag
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.result_view import title_score
from torrent_finder.search_result import SearchResult
from torrent_finder.resolvers import CreatorFacet, anilist, jikan

# A language typed after the title ("Berserk português") picks that preset for
# the search; release names rarely contain the word, so the title alone is
# searched too.
_TYPED_LANGUAGES = {
    "Portuguese": ("portugues", "portuguese", "pt-br", "ptbr", "brazilian"),
    "Spanish": ("espanol", "spanish", "castellano"),
    "French": ("francais", "french"),
    "Italian": ("italiano", "italian"),
    "Raw (Japanese)": ("raw", "raws", "japanese"),
}


def _language_preset(language: str, label: str) -> FilterPreset:
    return FilterPreset(
        language.capitalize(), FilterConfig(name_predicate=manga_language_tag(language)),
        require_engines=("Nyaa (Non-English)",),
        description=f"{label} tags in the name. Also searches Nyaa (Non-English), even if saved Off. "
                    "Typing the language after a title applies this to that search.",
    )


def typed_language(query: str) -> "tuple[str, str] | None":
    """(title, preset name) when a language ends the query, else None."""
    words = query.split()
    if len(words) < 2:
        return None
    last = strip_accents(words[-1]).casefold().strip("()[]")
    for preset, typed in _TYPED_LANGUAGES.items():
        if last in typed:
            return " ".join(words[:-1]), preset
    return None


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
        _language_preset("portuguese", "Portuguese (português, PT-BR)"),
        _language_preset("spanish", "Spanish (español, [es])"),
        _language_preset("french", "French (français, VF)"),
        _language_preset("italian", "Italian (italiano, ITA)"),
        FilterPreset("Raw (Japanese)", FilterConfig(name_predicate=is_raw_release),
                     require_engines=("Nyaa (Raw)",),
                     description="Japanese kana or a raw tag in the name. Also searches Nyaa (Raw), even if "
                                 "saved Off. Typing raw after a title applies this to that search."),
    ]
    # An English or alternate title the sources don't use ("Yokohama Shopping
    # Log") is retried under AniList's titles when nothing matched.
    looks_up_aliases = True

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
            SearchEngine("Nyaa (Non-English)", "🌐", self._search_nyaa_other, enabled=False),
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine(
                "Knaben", "🧭", self._search_knaben,
                enabled=False, emergency_fallback=True,
            ),
        ]

    def lookup_aliases(self, query: str) -> tuple:
        from torrent_finder.resolvers.titles import known_aliases
        return known_aliases("manga", query)

    def typed_preset(self, query: str):
        typed = typed_language(query)
        return next((p for p in self.presets if p.name == typed[1]), None) if typed else None

    def expand_queries(self, query: str) -> list[str]:
        queries = super().expand_queries(query)
        typed = typed_language(query)
        if typed and typed[0] not in queries:
            queries.insert(1, typed[0])
        return queries

    def title_relevance(self, row, query: str, authors: tuple = ()) -> int:
        typed = typed_language(query)
        return title_score(row.name, typed[0] if typed else query)

    def _search_nyaa_raw(self, query: str) -> list[SearchResult]:
        """Nyaa Literature - Raw, c=3_3. Off by default."""
        return self._search_nyaa_in(query, "3_3")

    def _search_nyaa_other(self, query: str) -> list[SearchResult]:
        """Non-English-translated literature, including Portuguese; not region-specific."""
        return self._search_nyaa_in(query, "3_2")
