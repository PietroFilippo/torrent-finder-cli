"""Manga torrent provider — searches Nyaa Literature plus Apibay Comics."""

from torrent_finder.i18n import N_

# i18n: converted

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.language_tags import is_raw_release, manga_language_tag
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.search_result import SearchResult
from torrent_finder.resolvers import CreatorFacet, anilist, jikan


_LANGUAGE_PRESETS = {
    "portuguese": (N_("Portuguese"), N_(
        "Portuguese (português, PT-BR) tags in the name. Also searches Nyaa (Non-English), even if saved Off. "
        "Typing the language after a title applies this to that search.")),
    "spanish": (N_("Spanish"), N_(
        "Spanish (español, [es]) tags in the name. Also searches Nyaa (Non-English), even if saved Off. "
        "Typing the language after a title applies this to that search.")),
    "french": (N_("French"), N_(
        "French (français, VF) tags in the name. Also searches Nyaa (Non-English), even if saved Off. "
        "Typing the language after a title applies this to that search.")),
    "italian": (N_("Italian"), N_(
        "Italian (italiano, ITA) tags in the name. Also searches Nyaa (Non-English), even if saved Off. "
        "Typing the language after a title applies this to that search.")),
}


def _language_preset(language: str) -> FilterPreset:
    return FilterPreset(
        _LANGUAGE_PRESETS[language][0], FilterConfig(name_predicate=manga_language_tag(language)),
        require_engines=("Nyaa (Non-English)",),  # i18n: ignore — service/engine identity, including external category values
        description=_LANGUAGE_PRESETS[language][1],
    )


class MangaProvider(BaseProvider):
    # Shown as "General" under the Manga group; slug stays "manga" so the -t
    # flag and existing history/stats keys keep working.
    name = N_("General")
    slug = "manga"
    icon = "📚"
    search_note = N_("Manga from public trackers (Nyaa Literature + Apibay Comics).")
    categories = [602]  # Apibay/TPB Comics
    # Nyaa Literature + Books / Comics.
    knaben_categories = (6_006_000, 9_002_000)
    nyaa_category = "3_1"  # Literature - English-translated (default Nyaa engine)

    supports_subtitles = False
    supports_episode_picker = True  # volume/chapter batches → aria2 file-selection
    supports_streaming = False  # manga isn't video — hide the Stream to VLC section

    presets = [
        FilterPreset(N_("Complete / Full"), FilterConfig(include_keywords=["complete", "full series"])),  # i18n: ignore — literal service or release-name match data
        FilterPreset(N_("By Volume"), FilterConfig(include_keywords=["volume", "vol."])),
        FilterPreset(N_("Color"), FilterConfig(include_keywords=["color", "colour"])),
        FilterPreset(N_("Official / Digital"), FilterConfig(include_keywords=["official", "digital"])),
        FilterPreset(N_("Official Publishers"), FilterConfig(include_keywords=[
            "viz", "kodansha", "yen press", "seven seas", "square enix", "j-novel",  # i18n: ignore — literal service or release-name match data
        ])),
        FilterPreset(N_("Exclude Light Novels"), FilterConfig(exclude_keywords=["light novel"])),  # i18n: ignore — literal service or release-name match data
        _language_preset("portuguese"),
        _language_preset("spanish"),
        _language_preset("french"),
        _language_preset("italian"),
        FilterPreset(N_("Raw (Japanese)"), FilterConfig(name_predicate=is_raw_release),
                     require_engines=("Nyaa (Raw)",),  # i18n: ignore — service/engine identity, including external category values
                     description=N_("Japanese kana or a raw tag in the name. Also searches Nyaa (Raw), even if "
                                 "saved Off. Typing raw after a title applies this to that search.")),
    ]
    # A language typed after the title ("Berserk português") picks that preset
    # for the search.
    typed_presets = {
        "Portuguese": ("portugues", "portuguese", "pt-br", "ptbr", "brazilian"),
        "Spanish": ("espanol", "spanish", "castellano"),
        "French": ("francais", "french"),
        "Italian": ("italiano", "italian"),
        "Raw (Japanese)": ("raw", "raws", "japanese"),
    }
    # An English or alternate title the sources don't use ("Yokohama Shopping
    # Log") is retried under AniList's titles when nothing matched.
    looks_up_aliases = True
    alias_catalog = "manga"

    # Search by creator. AniList resolves the writer/author to their manga; Jikan
    # resolves a Japanese serialization magazine to the manga it ran. Each picked
    # title is then searched on the torrent backends. Both keyless.
    creator_facets = [
        CreatorFacet(
            key="writer", label=N_("Writer"), icon="📝",
            search_entities=anilist.staff_search,
            list_works=anilist.manga_writer_works,
            note=N_("Find a writer's manga via AniList, then search each title."),
        ),
        CreatorFacet(
            key="magazine", label=N_("Magazine"), icon="📰",
            search_entities=jikan.magazine_search,
            list_works=jikan.magazine_works,
            note=N_("Find a magazine's serialized manga via MyAnimeList, then search each title."),
        ),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Nyaa EN + APIBay on, category-scoped Knaben auto, Raw Nyaa off."""
        return [
            SearchEngine("Nyaa (EN)", "🍙", self._search_nyaa, enabled=True),  # i18n: ignore — service/engine identity, including external category values
            SearchEngine("Nyaa (Raw)", "🗾", self._search_nyaa_raw, enabled=False),  # i18n: ignore — service/engine identity, including external category values
            SearchEngine("Nyaa (Non-English)", "🌐", self._search_nyaa_other, enabled=False),  # i18n: ignore — service/engine identity, including external category values
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),  # i18n: ignore — service/engine identity, including external category values
            SearchEngine(
                "Knaben", "🧭", self._search_knaben,  # i18n: ignore — service/engine identity, including external category values
                enabled=False, emergency_fallback=True,
            ),
        ]

    def _search_nyaa_raw(self, query: str) -> list[SearchResult]:
        """Nyaa Literature - Raw, c=3_3. Off by default."""
        return self._search_nyaa_in(query, "3_3")

    def _search_nyaa_other(self, query: str) -> list[SearchResult]:
        """Non-English-translated literature, including Portuguese; not region-specific."""
        return self._search_nyaa_in(query, "3_2")
